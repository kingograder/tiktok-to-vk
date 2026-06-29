# tiktok-to-vk

Sync TikTok collections to VK Clips.

Automatically discovers posts from a TikTok collection, downloads videos, converts horizontal footage to vertical format (1080x1920), and uploads them as VK Clips. Keeps a local SQLite database to track what has been processed.

## Features

- **Collection discovery** -- fetches all posts from a TikTok collection via the internal API
- **Video download** -- downloads via yt-dlp with browser impersonation
- **Vertical conversion** -- pads or rotates horizontal videos to 1080x1920
- **VK upload** -- uploads clips via VK API with rate limiting and processing polling
- **SQLite tracking** -- remembers which posts have been downloaded and uploaded
- **Daemon mode** -- runs in the background with configurable polling interval
- **Graceful shutdown** -- handles SIGINT/SIGTERM, finishes current cycle
- **Multi-collection** -- supports multiple collections via comma-separated URLs in `TIKTOK_COLLECTION_URL`

## Requirements

- Python 3.10+
- ffmpeg (for video processing)
- TikTok session cookies (`cookies.txt` in Netscape format)
- VK access token with video upload permission

## Getting VK Token

1. Open [vkhost.github.io](https://vkhost.github.io/) in browser
2. Click **Kate Mobile**
3. Authorize and copy the token from the URL fragment (`access_token=...`)
4. Paste into `.env` as `VK_TOKEN`

## Getting TikTok Cookies

1. Open tiktok.com in browser and log in
2. Use [cookies-txt](https://github.com/hrdl-github/cookies-txt) extension (or any Netscape cookie exporter)
3. Export cookies to `cookies.txt` in project root

## Installation

```bash
git clone https://github.com/kingograder/tiktok-to-vk.git
cd tiktok-to-vk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `TIKTOK_COLLECTION_URL` | TikTok collection URL |
| `TIKTOK_COOKIES_FILE` | Path to cookies.txt (default: `cookies.txt`) |
| `TIKTOK_PROXY` | Proxy for TikTok requests (optional, recommended for Russian users) |
| `VK_TOKEN` | VK access token with video upload permission |
| `APP_DB_PATH` | SQLite database path (default: `data/clips.db`) |
| `APP_CHECK_INTERVAL` | Seconds between cycles in daemon mode (default: `1800`) |
| `APP_ROTATE_VIDEO` | `True` = rotate 90°, `False` = pad with black bars |

See `.env.example` for all available options.

### Multiple collections

Specify multiple URLs comma-separated in `.env`:

```
TIKTOK_COLLECTION_URL=https://www.tiktok.com/@user/collection/name-123,https://www.tiktok.com/@user/collection/other-456
```

## Usage

Single cycle:

```bash
python main.py --once
```

Daemon mode:

```bash
python main.py
```

### Docker

```bash
docker build -t tiktok-to-vk . --no-cache
docker run --network host --name tiktok-to-vk -d --restart always --env-file .env -e TIKTOK_COOKIES_FILE=/app/cookies.txt -v ./cookies.txt:/app/cookies.txt -v ./data:/app/data tiktok-to-vk -v ./logs:/app/logs
```

## How it works

1. **Discover** -- calls `collection/item_list` API to get posts from the collection
2. **Download** -- downloads videos via yt-dlp
3. **Process** -- converts horizontal videos to vertical 1080x1920 format
4. **Upload** -- uploads to VK Clips via VK API
5. **Cleanup** -- deletes local files after successful upload

Each video gets a description with:
- `Author:` -- TikTok creator name
- `Original:` -- link to the original TikTok video
- `Source:` -- link to this repository

## Limitations

- Photo posts and carousels are **not supported** in current version
- Multiple collections support is experimental

## License

AGPL-3.0
