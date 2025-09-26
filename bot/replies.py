import os
from datetime import datetime, timezone
from googleapiclient.errors import HttpError

from .common import (
    youtube_service, ensure_db, get_meta, set_meta, match_card,
    already_replied, record_reply, user_recent_reply, load_card_map,
    render_reply, fetch_latest_video_id, fetch_new_comments
)

DAILY_REPLY_BUDGET = int(os.getenv("DAILY_REPLY_BUDGET", "180"))
PER_RUN_REPLY_CAP = int(os.getenv("PER_RUN_REPLY_CAP", "15"))
CHANNEL_ID = os.getenv("CHANNEL_ID")
TARGET_VIDEO_ID = os.getenv("TARGET_VIDEO_ID")  # optional

def main():
    if not CHANNEL_ID:
        raise RuntimeError("Set CHANNEL_ID env var.")
    yt = youtube_service()
    conn = ensure_db()

    # reset daily counter at UTC day start
    today_key = datetime.now(timezone.utc).date().isoformat()
    stored_day = get_meta(conn, "day")
    if stored_day != today_key:
        set_meta(conn, "day", today_key)
        set_meta(conn, "replies_used_today", "0")

    used = int(get_meta(conn, "replies_used_today", "0"))
    if used >= DAILY_REPLY_BUDGET:
        print("Daily budget spent; exiting.")
        return

    video_id = TARGET_VIDEO_ID or fetch_latest_video_id(yt, CHANNEL_ID)
    if not video_id:
        print("No video found.")
        return

    since_iso = get_meta(conn, f"last_checked_{video_id}")
    page_token = None
    to_reply = []
    card_map = load_card_map()

    try:
        while True:
            items, page_token = fetch_new_comments(yt, video_id, page_token, since_iso)
            if not items:
                break
            for it in items:
                c = it["snippet"]["topLevelComment"]
                snip = c["snippet"]
                text = snip.get("textOriginal") or ""
                user_id = snip.get("authorChannelId", {}).get("value") or snip.get("authorDisplayName")
                comment_id = c["id"]
                card_key = match_card(text)
                if not card_key:
                    continue
                if card_key not in card_map:
                    continue  # skip until mapped
                if already_replied(conn, comment_id):
                    continue
                if user_recent_reply(conn, user_id, hours=24):
                    continue
                to_reply.append((comment_id, user_id, card_key))
            if not page_token:
                break
    except HttpError as e:
        print("HTTP error fetching comments:", e)
        return

    allow = min(PER_RUN_REPLY_CAP, DAILY_REPLY_BUDGET - used, len(to_reply))
    if allow <= 0:
        print("No reply slots available.")
        return

    for comment_id, user_id, card_key in to_reply[:allow]:
        url = card_map[card_key]
        reply = render_reply(card_key, url)
        try:
            # parentId is the top-level comment id
            yt.comments().insert(part="snippet", body={
                "snippet": {"parentId": comment_id, "textOriginal": reply}
            }).execute()
            record_reply(conn, comment_id, video_id, user_id, card_key)
            used += 1
        except HttpError as e:
            print("HTTP error replying:", e)
            break

    set_meta(conn, "replies_used_today", str(used))
    set_meta(conn, f"last_checked_{video_id}", datetime.now(timezone.utc).isoformat())
    print(f"Replied to {allow} comments. Used today: {used}/{DAILY_REPLY_BUDGET}")

if __name__ == "__main__":
    main()
