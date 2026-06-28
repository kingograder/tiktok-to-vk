import asyncio
import logging

import yt_dlp
from yt_dlp.extractor.tiktok import TikTokCollectionIE

from config.config import config

logger = logging.getLogger(__name__)


def _fetch_collection_sync(collection_url: str, cookies_file: str,
                           proxy: str | None = None) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "cookiefile": cookies_file,
        "impersonate": "chrome",
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    last_err = None
    for attempt in range(config.app.MAX_RETRIES):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ie = TikTokCollectionIE(ydl)
                result = ie.extract(collection_url)
            break
        except Exception as e:
            last_err = e
            err_msg = str(e)
            is_cookie = any(c in err_msg for c in (
                "Log in for access",
                "status code 10203",
            ))
            if is_cookie:
                logger.error("Cookie error: %s — update cookies.txt", err_msg)
                raise
            import time
            if attempt < config.app.MAX_RETRIES - 1:
                logger.warning("Attempt %d/%d failed: %s",
                               attempt + 1, config.app.MAX_RETRIES, err_msg)
                time.sleep(2 * (attempt + 1))
                continue
            raise
    else:
        raise last_err

    items = []
    for entry in result.get("entries") or []:
        video_id = entry.get("id") or entry.get("url", "")
        unique_id = entry.get("uploader") or ""
        if not video_id:
            continue
        items.append({
            "id": str(video_id),
            "author": {"uniqueId": unique_id},
        })
    return items


async def discover_posts(collection_url: str, cookies_file: str,
                         proxy: str | None = None) -> list[dict]:
    items = await asyncio.to_thread(
        _fetch_collection_sync, collection_url, cookies_file, proxy,
    )
    return items
