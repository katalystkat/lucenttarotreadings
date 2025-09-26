import os
from datetime import datetime, timezone
from googleapiclient.errors import HttpError

from .common import (
    youtube_service, ensure_db, top_card_today, load_card_map, fetch_latest_video_id, update_video_title
)

CHANNEL_ID = os.getenv("CHANNEL_ID")
TARGET_VIDEO_ID = os.getenv("TARGET_VIDEO_ID")  # optional
TITLE_PREFIX = os.getenv("TITLE_PREFIX", "")  # optional, e.g., "[Daily Tarot] "

def prettify(card_key: str) -> str:
    pretty = card_key.replace('_', ' ').title().replace(' Of ', ' of ')
    if card_key.endswith('_reversed'):
        pretty = pretty.replace(' Reversed', '') + ' (Reversed)'
    return pretty

def main():
    if not CHANNEL_ID:
        raise RuntimeError("Set CHANNEL_ID env var.")
    yt = youtube_service()
    conn = ensure_db()

    pair = top_card_today(conn)
    if not pair:
        print("No card counts today; not updating title.")
        return
    card_key, count = pair
    video_id = TARGET_VIDEO_ID or fetch_latest_video_id(yt, CHANNEL_ID)
    if not video_id:
        print("No video found.")
        return

    new_title = f"{TITLE_PREFIX}Most drawn today: {prettify(card_key)} ({count})"
    try:
        update_video_title(yt, video_id, new_title)
        print("Updated title:", new_title)
    except HttpError as e:
        print("HTTP error updating title:", e)

if __name__ == "__main__":
    main()
