import asyncio
import logging
import os
import re

import yt_dlp
from gallery_dl import config as gallery_config, job as gallery_job
from yt_dlp.networking.impersonate import ImpersonateTarget

from app.video.slideshow import SLIDESHOW_TMP_DIR, cleanup_slideshow_tmp, render_slideshow

logger = logging.getLogger(__name__)

GITHUB_REPO = "https://github.com/kingograder/tiktok-to-vk"

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv"}

_gallery_dl_configured = False


def _ensure_gallery_dl_config() -> None:
    global _gallery_dl_configured
    if _gallery_dl_configured:
        return
    gallery_config.load()
    gallery_config.set((), "directory", "")
    gallery_config.set(("extractor",), "base-directory", str(SLIDESHOW_TMP_DIR))
    gallery_config.set(
        ("extractor", "tiktok"),
        "filename",
        {"extension == 'mp3'": "audio.mp3", "": "{num}.{extension}"},
    )
    _gallery_dl_configured = True


def extract_username(collection_url: str) -> str | None:
    match = re.search(r"tiktok\.com/@([^/?]+)", collection_url)
    return match.group(1) if match else None


def build_description(tiktok_id: str, username: str | None, author_name: str | None = None) -> str:
    lines = []
    if author_name:
        lines.append(f"Author: {author_name}")
    lines.append(f"Original: https://www.tiktok.com/video/{tiktok_id}")
    if username:
        lines.append(f"Reposted by: https://www.tiktok.com/@{username}")
    lines.append(f"Source code: {GITHUB_REPO}")
    return "\n".join(lines)


def _fetch_video_ids_sync(collection_url: str, cookies_file: str, proxy: str | None = None) -> list[str]:
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "cookiefile": cookies_file,
        "impersonate": ImpersonateTarget.from_str("chrome"),
        "logger": logger,
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    import time
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(collection_url, download=False)
                if not info or "entries" not in info:
                    return []
                return [str(entry["id"]) for entry in info["entries"] if entry.get("id")]
        except yt_dlp.utils.ExtractorError as e:
            err_msg = str(e)
            if any(net_err in err_msg for net_err in NETWORK_ERRORS) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise


async def fetch_video_ids(collection_url: str, cookies_file: str, proxy: str | None = None) -> list[str]:
    return await asyncio.to_thread(_fetch_video_ids_sync, collection_url, cookies_file, proxy)


def _download_slideshow_images_sync(video_id: str, proxy: str | None = None, username: str | None = None) -> bool:
    _ensure_gallery_dl_config()
    cleanup_slideshow_tmp()

    if username:
        url = f"https://www.tiktok.com/@{username}/video/{video_id}"
    else:
        url = f"https://www.tiktok.com/share/video/{video_id}"

    try:
        gallery_job.DownloadJob(url).run()

        image_count = len([f for f in os.listdir(SLIDESHOW_TMP_DIR) if f.endswith(".jpg")])
        has_audio = (SLIDESHOW_TMP_DIR / "audio.mp3").exists()

        if image_count == 0:
            logger.error("No images downloaded for %s", video_id)
            return False
        if not has_audio:
            logger.error("No audio downloaded for %s", video_id)
            return False

        logger.info("Downloaded %d images + audio for %s", image_count, video_id)
        return True

    except Exception:
        logger.exception("gallery-dl failed for %s", video_id)
        return False


async def _download_slideshow_images(video_id: str, proxy: str | None = None, username: str | None = None) -> bool:
    return await asyncio.to_thread(_download_slideshow_images_sync, video_id, proxy, username)


NETWORK_ERRORS = (
    "Connection reset by peer",
    "Connection refused",
    "Read timed out",
    "Failed to resolve",
    "Max retries exceeded",
)


def _download_video_sync(collection_url: str, position: int, video_id: str, download_dir: str, cookies_file: str, proxy: str | None = None) -> dict | None:
    ydl_opts = {
        "format": "bv*+ba/b",
        "outtmpl": f"{download_dir}/%(id)s.%(ext)s",
        "cookiefile": cookies_file,
        "impersonate": ImpersonateTarget.from_str("chrome"),
        "logger": logger,
        "playlist_items": str(position),
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    last_err = None
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(collection_url, download=True)
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            err_msg = str(e)
            if any(net_err in err_msg for net_err in NETWORK_ERRORS):
                if attempt < 2:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue
            raise


def _cleanup_audio_file(video_id: str, download_dir: str) -> None:
    for f in os.listdir(download_dir):
        stem = f.rsplit(".", 1)[0] if "." in f else f
        ext = os.path.splitext(f)[1]
        if stem == video_id and ext in {".m4a", ".mp3", ".opus", ".wav"}:
            os.remove(os.path.join(download_dir, f))


def _find_video_file(video_id: str, download_dir: str) -> str | None:
    for f in os.listdir(download_dir):
        stem = f.rsplit(".", 1)[0] if "." in f else f
        ext = os.path.splitext(f)[1]
        if stem == video_id and ext in VIDEO_EXTENSIONS:
            return os.path.join(download_dir, f)
    return None


async def download_video(collection_url: str, position: int, video_id: str, download_dir: str, cookies_file: str, proxy: str | None = None, username: str | None = None) -> tuple[str | None, str | None]:
    try:
        info = await asyncio.to_thread(_download_video_sync, collection_url, position, video_id, download_dir, cookies_file, proxy)
    except yt_dlp.utils.DownloadError:
        logger.exception("yt-dlp download error for %s", video_id)
        return None, None

    author_name = info.get("uploader") if info else None

    # detect photo post via format_id
    if info and info.get("format_id") == "audio":
        logger.info("Photo post detected: %s", video_id)
        if await _download_slideshow_images(video_id, proxy, username):
            result = await render_slideshow(video_id, download_dir)
            await asyncio.to_thread(cleanup_slideshow_tmp)
            await asyncio.to_thread(_cleanup_audio_file, video_id, download_dir)
            return result, author_name
        else:
            logger.error("Failed to download slideshow images for %s", video_id)
            return None, None

    # normal video - find the file
    path = await asyncio.to_thread(_find_video_file, video_id, download_dir)
    return path, author_name
