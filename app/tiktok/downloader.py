import asyncio
import logging
import os
import time

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

from config.config import config

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv"}


def _find_video_file(video_id: str, download_dir: str) -> str | None:
    for ext in VIDEO_EXTENSIONS:
        path = os.path.join(download_dir, f"{video_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _parse_cookies_for_ydl(path: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except OSError:
        pass
    return cookies


def _download_video_sync(item: dict, download_dir: str, cookies_file: str,
                         proxy: str | None = None) -> str | None:
    tiktok_id = str(item.get("id", ""))
    author = item.get("author", {})
    username = author.get("uniqueId", "")
    video_url = f"https://www.tiktok.com/@{username}/video/{tiktok_id}"

    cookie_dict = _parse_cookies_for_ydl(cookies_file)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

    ydl_opts = {
        "format": "bv*+ba/b, bv*",
        "outtmpl": os.path.join(download_dir, f"{tiktok_id}.%(ext)s"),
        "impersonate": ImpersonateTarget.from_str("chrome"),
        "quiet": True,
        "logger": logger,
        "noprogress": True,
        "http_headers": {
            "Cookie": cookie_header,
        },
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
