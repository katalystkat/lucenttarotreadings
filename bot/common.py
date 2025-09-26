import os
import re
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional, List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.oauth2.credentials as oauth2

STATE_DIR = Path(os.getenv("STATE_DIR", "state"))
STATE_DIR.mkdir(exist_ok=True, parents=True)
DB_PATH = STATE_DIR / "state.sqlite"
TOKEN_PATH = STATE_DIR / "oauth_token.json"

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

CARD_MAP_PATH = Path(__file__).parent / "card_map.json"

CARD_REGEX = re.compile(r"""(?ix)\b(
  the\s+(fool|magician|high\s+priestess|empress|emperor|hierophant|lovers|chariot|strength|hermit|wheel\s+of\s+fortune|justice|hanged\s+man|death|temperance|devil|tower|star|moon|sun|judgement|world)
  |(ace|two|three|four|five|six|seven|eight|nine|ten|page|knight|queen|king)\s+of\s+(wands|cups|swords|pentacles)
)\b(\s*\(reversed\))?
""")

MAJOR_CANON = {
  "fool":"the_fool","magician":"the_magician","high priestess":"the_high_priestess","empress":"the_empress",
  "emperor":"the_emperor","hierophant":"the_hierophant","lovers":"the_lovers","chariot":"the_chariot",
  "strength":"strength","hermit":"the_hermit","wheel of fortune":"wheel_of_fortune","justice":"justice",
  "hanged man":"the_hanged_man","death":"death","temperance":"temperance","devil":"the_devil","tower":"the_tower",
  "star":"the_star","moon":"the_moon","sun":"the_sun","judgement":"judgement","world":"the_world"
}

RANKS = {"ace":"ace","two":"two","three":"three","four":"four","five":"five","six":"six","seven":"seven","eight":"eight","nine":"nine","ten":"ten","page":"page","knight":"knight","queen":"queen","king":"king"}
SUITS = {"wands":"wands","cups":"cups","swords":"swords","pentacles":"pentacles"}

def load_card_map() -> Dict[str, str]:
    with open(CARD_MAP_PATH, "r") as f:
        return json.load(f)

def canonicalize(name: str) -> str:
    s = name.lower().strip()
    is_reversed = s.endswith("(reversed)")
    s = s.replace("(reversed)", "").strip()
    # majors
    if s.startswith("the "):
        key = MAJOR_CANON.get(s[4:], None)
        if key is None:
            key = s.replace(" ", "_")
    elif s in MAJOR_CANON:
        key = MAJOR_CANON[s]
    else:
        # minors: 'five of cups'
        m = re.match(r"(?i)(ace|two|three|four|five|six|seven|eight|nine|ten|page|knight|queen|king)\s+of\s+(wands|cups|swords|pentacles)", s)
        if m:
            key = f"{RANKS[m.group(1).lower()]}_of_{SUITS[m.group(2).lower()]}"
        else:
            key = s.replace(" ", "_")
    if is_reversed:
        key += "_reversed"
    return key

def match_card(text: str) -> Optional[str]:
    m = CARD_REGEX.search(text or "")
    if not m:
        return None
    raw = m.group(0)
    return canonicalize(raw)

def get_credentials():
    # 1) If OAUTH_JSON provided as path
    json_path = os.getenv("OAUTH_JSON_PATH")
    if json_path and Path(json_path).exists():
        return _oauth_flow(json_path)

    # 2) If OAUTH_JSON_B64 provided (decode to temp file)
    b64 = os.getenv("OAUTH_JSON_B64")
    if b64:
        content = base64.b64decode(b64).decode("utf-8")
        temp_path = STATE_DIR / "client_secret.json"
        temp_path.write_text(content)
        return _oauth_flow(str(temp_path))

    raise RuntimeError("Provide OAUTH_JSON_PATH or OAUTH_JSON_B64 env var.")

def _oauth_flow(json_path: str):
    creds = None
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text())
        creds = oauth2.Credentials.from_authorized_user_info(data, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(json_path, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return creds

def youtube_service():
    creds = get_credentials()
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS replies (
      comment_id TEXT PRIMARY KEY,
      video_id TEXT,
      user_id TEXT,
      card_key TEXT,
      replied_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY,
      last_reply_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS counters (
      date TEXT,
      card_key TEXT,
      count INTEGER,
      PRIMARY KEY(date, card_key)
    );
    """)
    conn.commit()
    return conn

def get_meta(conn, key: str, default: Optional[str]=None) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default

def set_meta(conn, key: str, value: str):
    cur = conn.cursor()
    cur.execute("REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))
    conn.commit()

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def start_of_today_utc() -> str:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return start.isoformat()

def increment_card(conn, card_key: str, dt: Optional[datetime]=None):
    dt = dt or datetime.now(timezone.utc)
    date = dt.date().isoformat()
    cur = conn.cursor()
    cur.execute("SELECT count FROM counters WHERE date=? AND card_key=?", (date, card_key))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE counters SET count=count+1 WHERE date=? AND card_key=?", (date, card_key))
    else:
        cur.execute("INSERT INTO counters(date, card_key, count) VALUES(?,?,1)", (date, card_key))
    conn.commit()

def top_card_today(conn) -> Optional[Tuple[str,int]]:
    cur = conn.cursor()
    cur.execute("SELECT card_key, count FROM counters WHERE date=? ORDER BY count DESC LIMIT 1", (datetime.now(timezone.utc).date().isoformat(),))
    row = cur.fetchone()
    return (row[0], row[1]) if row else None

def already_replied(conn, comment_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM replies WHERE comment_id=?", (comment_id,))
    return cur.fetchone() is not None

def record_reply(conn, comment_id: str, video_id: str, user_id: str, card_key: str):
    cur = conn.cursor()
    cur.execute("REPLACE INTO replies(comment_id, video_id, user_id, card_key, replied_at) VALUES(?,?,?,?,?)",
                (comment_id, video_id, user_id, card_key, iso_now()))
    cur.execute("REPLACE INTO users(user_id, last_reply_at) VALUES(?,?)", (user_id, iso_now()))
    increment_card(conn, card_key)
    conn.commit()

def user_recent_reply(conn, user_id: str, hours: int=24) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT last_reply_at FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row: return False
    last = datetime.fromisoformat(row[0])
    return (datetime.now(timezone.utc) - last) < timedelta(hours=hours)

def render_reply(card_key: str, url: str) -> str:
    # Very short templates; customize as desired
    pretty = card_key.replace('_', ' ').title().replace(' Of ', ' of ')
    if card_key.endswith('_reversed'):
        pretty = pretty.replace(' Reversed', '') + ' (Reversed)'
        return f"You pulled **{pretty}** 🌙 Shadow focus + guidance → {url}"
    else:
        return f"You pulled **{pretty}** ✨ Quick hits + explainer → {url}"

def fetch_latest_video_id(youtube, channel_id: str) -> Optional[str]:
    resp = youtube.search().list(
        part="id", channelId=channel_id, order="date", maxResults=1, type="video"
    ).execute()
    items = resp.get("items", [])
    if not items: return None
    return items[0]["id"]["videoId"]

def fetch_new_comments(youtube, video_id: str, page_token: Optional[str]=None, since_iso: Optional[str]=None) -> Tuple[List[dict], Optional[str]]:
    # commentThreads.list always returns newest first when order='time'
    params = dict(part="snippet", videoId=video_id, maxResults=50, order="time")
    if page_token:
        params["pageToken"] = page_token
    resp = youtube.commentThreads().list(**params).execute()
    items = []
    for it in resp.get("items", []):
        top = it["snippet"]["topLevelComment"]["snippet"]
        published = top.get("publishedAt") or top.get("updatedAt")
        if since_iso and published <= since_iso:
            continue
        items.append(it)
    return items, resp.get("nextPageToken")

def reply_to_comment(youtube, parent_id: str, text: str):
    body = {"snippet": {"parentId": parent_id, "textOriginal": text}}
    return youtube.comments().insert(part="snippet", body=body).execute()

def update_video_title(youtube, video_id: str, new_title: str):
    # Need current snippet to update title
    v = youtube.videos().list(part="snippet", id=video_id).execute()
    items = v.get("items", [])
    if not items: return None
    snippet = items[0]["snippet"]
    snippet["title"] = new_title
    body = {"id": video_id, "snippet": snippet}
    return youtube.videos().update(part="snippet", body=body).execute()
