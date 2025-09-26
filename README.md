# Tarot YouTube Bot (Skeleton)

This repository contains a minimal, ready-to-run **comment reply bot** + **daily title updater**
for your Tarot "Pause to Pick" channel. It is designed to run on **GitHub Actions** or a cron job.

## Features
- Replies to comments that contain a Tarot card (supports reversed).
- Caps replies per run and per day to stay within YouTube API quota.
- Tracks idempotency so you don't double-reply.
- Daily title updater to announce the most-drawn card.
- Simple **SQLite** state file (`state/state.sqlite`) so the bot can resume safely.
- Clean separation: `replies.py` (every 10 min), `title_update.py` (daily).

## Quick Start (Local)
1. **Create Google API credentials** (OAuth client ID for Desktop) and download `client_secret.json`.
2. Export environment variables:
   ```bash
   export OAUTH_JSON_PATH=./client_secret.json
   export CHANNEL_ID=YOUR_CHANNEL_ID
   export DAILY_REPLY_BUDGET=180
   export PER_RUN_REPLY_CAP=15
   # Optional: restrict to a specific video id (or leave unset to scan latest uploads)
   export TARGET_VIDEO_ID=YOUR_VIDEO_ID
   ```
3. Install dependencies & run:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python bot/replies.py
   python bot/title_update.py
   ```

The first run will open a browser for OAuth consent and cache tokens in `state/oauth_token.json`.

## GitHub Actions Setup
- Add the following **Secrets** to your GitHub repo:
  - `OAUTH_JSON_B64` → base64 of your `client_secret.json` (see below).
  - `CHANNEL_ID` → your channel ID.
  - (Optional) `TARGET_VIDEO_ID`
- The workflows in `.github/workflows/` will decode the secret, run on schedule, and keep state in the repo.

### Encode your OAuth client JSON
```bash
base64 -w 0 client_secret.json > client_secret.json.b64
# Copy content into the GitHub Secret OAUTH_JSON_B64
```

## State Persistence
- State lives in `state/state.sqlite` (created on first run).
- In GitHub Actions, the workflow commits the updated `state/` directory back to the repo each run.
  - Alternatively, store state in a small cloud sqlite or Google Sheet.

## Quota Safety (Defaults)
- Daily reply budget: `DAILY_REPLY_BUDGET` (default 180).
- Per run cap: `PER_RUN_REPLY_CAP` (default 15).
- `commentThreads.list` is cheap; `comments.insert` and `videos.update` cost 50 units each.

## Files
- `bot/common.py` — auth, service builders, state, regex, helpers
- `bot/replies.py` — every 10 minutes: fetch comments, reply up to caps
- `bot/title_update.py` — once daily: compute & update title with most-drawn card
- `bot/card_map.json` — (skeleton) mapping from canonical card keys to explainer URLs

## Customization
- Fill `bot/card_map.json` with URLs (video chapters or landing page anchors).
- Edit `render_reply()` in `common.py` to change message style.
- Tune regex and caps via env vars.

---

**DISCLAIMER:** This is a starter skeleton. Test in a private/unlisted video first. Respect YouTube policies and user privacy.
