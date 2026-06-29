import asyncio
import json
import logging
import os
import re
import time

import yt_dlp
from curl_cffi import requests as cffi_requests
from yt_dlp.networking.impersonate import ImpersonateTarget

from app.tiktok.scrapper import _parse_cookies
from app.video.slideshow import SLIDESHOW_TMP_DIR, _render_slideshow_sync, cleanup_slideshow_tmp
from config.config import config

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv"}

_BAD_COOKIES = {"tt-target-idc"}


def _parse_tiktok_cookies(path: str) -> dict[str, str]:
    cookies = _parse_cookies(path)
    return {k: v for k, v in cookies.items() if k not in _BAD_COOKIES}


def _find_video_file(video_id: str, download_dir: str) -> str | None:
    for ext in VIDEO_EXTENSIONS:
        path = os.path.join(download_dir, f"{video_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _is_photo_post(info: dict) -> bool:
    return info.get("format_id") == "audio" and info.get("vcodec") == "none"


def _fetch_post_data_sync(video_id: str, username: str, cookies_file: str,
                          proxy: str | None = None) -> dict | None:
    url = f"https://www.tiktok.com/@{username}/video/{video_id}"
    cookies = _parse_tiktok_cookies(cookies_file)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    last_err = None
    for attempt in range(config.app.MAX_RETRIES):
        try:
            resp = cffi_requests.get(
                url,
                impersonate="chrome",
                cookies=cookies,
                proxies=proxies,
                timeout=config.tiktok.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.error("Failed to fetch page for %s: HTTP %d", video_id, resp.status_code)
                return None

            match = re.search(
                r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
                resp.text,
            )
            if not match:
                logger.error("No hydration data found for %s", video_id)
                return None

            data = json.loads(match.group(1))
            default = data.get("__DEFAULT_SCOPE__", {})
            return (
                default.get("webapp.video-detail", {})
                .get("itemInfo", {})
                .get("itemStruct", {})
            )

        except Exception as e:
            last_err = e
            if attempt < config.app.MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            logger.exception("Failed to fetch post data for %s", video_id)
            return None

    return None


def _extract_image_urls(item_struct: dict | None) -> list[str]:
    if not item_struct:
        return []
    image_post = item_struct.get("imagePost", {})
    images = image_post.get("images", [])
    urls = []
    for img in images:
        url_list = img.get("imageURL", {}).get("urlList", [])
        if url_list:
            urls.append(url_list[0])
    return urls


def _extract_audio_url(item_struct: dict) -> str | None:
    music = item_struct.get("music", {})
    play_url = music.get("playUrl", "")
    if play_url:
        return play_url

    video = item_struct.get("video", {})
    play_addr = video.get("playAddr", "")
    if isinstance(play_addr, dict):
        url_list = play_addr.get("urlList", [])
        if url_list:
            return url_list[0]
    elif isinstance(play_addr, str) and play_addr:
        return play_addr

    bitrate_info = video.get("BitrateInfo", [])
    for info in bitrate_info:
        if info.get("CodecType") == "audio":
            play_url_list = info.get("PlayAddr", {}).get("UrlList", [])
            if play_url_list:
                return play_url_list[0]
    return None


def _download_file_sync(file_url: str, dest: str, proxy: str | None = None) -> bool:
    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        resp = cffi_requests.get(
            file_url,
            impersonate="chrome",
            proxies=proxies,
            timeout=config.tiktok.REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("Failed to download %s: HTTP %d", file_url[:80], resp.status_code)
            return False

        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(resp.content)
        return True

    except Exception:
        logger.exception("Download failed for %s", file_url[:80])
        return False


def _download_slideshow_sync(video_id: str, item_struct: dict, download_dir: str,
                             cookies_file: str, proxy: str | None = None) -> str | None:
    cleanup_slideshow_tmp(video_id)
    tmp_dir = SLIDESHOW_TMP_DIR / video_id
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_urls = _extract_image_urls(item_struct)
    if not image_urls:
        logger.error("No image URLs found for %s", video_id)
        return None

    for i, img_url in enumerate(image_urls):
        dest = str(tmp_dir / f"{i + 1}.jpg")
        if not _download_file_sync(img_url, dest, proxy):
            logger.error("Failed to download image %d for %s", i + 1, video_id)
            cleanup_slideshow_tmp(video_id)
            return None

    logger.info("Downloaded %d images for %s", len(image_urls), video_id)

    audio_url = _extract_audio_url(item_struct)
    if not audio_url:
        logger.error("No audio URL found for %s", video_id)
        cleanup_slideshow_tmp(video_id)
        return None

    audio_dest = str(tmp_dir / "audio.mp3")
    if not _download_file_sync(audio_url, audio_dest, proxy):
        logger.error("Failed to download audio for %s", video_id)
        cleanup_slideshow_tmp(video_id)
        return None

    logger.info("Downloaded audio for %s", video_id)

    result = _render_slideshow_sync(video_id, download_dir)
    cleanup_slideshow_tmp(video_id)
    return result


def _download_video_sync(item: dict, download_dir: str, cookies_file: str,
                         proxy: str | None = None) -> str | None:
    tiktok_id = str(item.get("id", ""))
    author = item.get("author", {})
    username = author.get("uniqueId", "")

    item_struct = _fetch_post_data_sync(tiktok_id, username, cookies_file, proxy)
    if item_struct:
        image_urls = _extract_image_urls(item_struct)
        if image_urls:
            logger.info("Photo post detected: %s", tiktok_id)
            return _download_slideshow_sync(tiktok_id, item_struct, download_dir, cookies_file, proxy)

    video_url = f"https://www.tiktok.com/@{username}/video/{tiktok_id}"
    ydl_opts = {
        "format": "bv*+ba/b, bv*",
        "outtmpl": os.path.join(download_dir, f"{tiktok_id}.%(ext)s"),
        "cookiefile": cookies_file,
        "impersonate": ImpersonateTarget.from_str("chrome"),
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
