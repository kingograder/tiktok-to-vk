import asyncio
import logging
import os
import time

import yt_dlp

from config.config import config

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv"}


def _find_video_file(video_id: str, download_dir: str) -> str | None:
    for ext in VIDEO_EXTENSIONS:
        path = os.path.join(download_dir, f"{video_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _download_video_sync(item: dict, download_dir: str, cookies_file: str,
                         proxy: str | None = None) -> str | None:
    tiktok_id = str(item.get("id", ""))
    author = item.get("author", {})
    username = author.get("uniqueId", "")
    video_url = f"https://www.tiktok.com/@{username}/video/{tiktok_id}"

    ydl_opts = {
        "format": "bv*+ba/b, bv*",
        "outtmpl": os.path.join(download_dir, f"{tiktok_id}.%(ext)s"),
        "cookiefile": cookies_file,
        "impersonate": "chrome",
        "quiet": True,
        "logger": logger,
        "noprogress": True,
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    last_err = None
    for attempt in range(config.app.MAX_RETRIES):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                if info is None:
                    continue
                return _find_video_file(tiktok_id, download_dir)
        except yt_dlp.utils.DownloadError as exc:
            last_err = exc
            err_msg = str(exc)
            is_network_error = any(e in err_msg for e in (
                "Connection reset by peer",
                "Connection refused",
                "Read timed out",
                "Failed to resolve",
                "Max retries exceeded",
            ))
            if is_network_error and attempt < config.app.MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            break

    logger.error("yt-dlp failed for %s: %s", tiktok_id, last_err)
    return None


async def download_video(item: dict, download_dir: str, cookies_file: str,
                         proxy: str | None = None) -> str | None:
    return await asyncio.to_thread(
        _download_video_sync, item, download_dir, cookies_file, proxy
    )
