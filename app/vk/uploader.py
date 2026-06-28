import asyncio
import logging
import os
import time

import aiohttp

from config.config import config

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method"
_vk_rate_limiter = asyncio.Semaphore(1)
_vk_last_request_time = 0.0
GITHUB_REPO = "https://github.com/kingograder/tiktok-to-vk"


def build_description(tiktok_id: str, username: str | None) -> str:
    lines = [f"Author: {username}"] if username else []
    original_url = f"https://www.tiktok.com/@{username}/video/{tiktok_id}" if username else f"https://www.tiktok.com/video/{tiktok_id}"
    lines += [f"Original: {original_url}", f"Source: {GITHUB_REPO}"]
    return "\n".join(lines)


async def _vk_method(method: str, session: aiohttp.ClientSession, **params) -> dict:
    global _vk_last_request_time
    async with _vk_rate_limiter:
        now = time.monotonic()
        wait = config.vk.MIN_INTERVAL - (now - _vk_last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _vk_last_request_time = time.monotonic()

    payload = {**params, "access_token": config.vk.TOKEN, "v": config.vk.API_VERSION}
    async with session.post(f"{VK_API_URL}/{method}", data=payload) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"VK API HTTP {resp.status}: {text[:200]}")
        data = await resp.json()
    if "error" in data:
        error = data["error"]
        error_msg = error.get("error_msg", str(error)) if isinstance(error, dict) else str(error)
        raise Exception(f"VK API error: {error_msg}")
    return data["response"]


async def upload_clip(video_path: str, description: str) -> tuple[int, int] | None:
    try:
        file_size = os.path.getsize(video_path)
    except OSError as e:
        logger.error("Cannot read file size for %s: %s", video_path, e)
        return None

    try:
        async with aiohttp.ClientSession() as session:
            upload_data = await _vk_method(
                "video.save",
                session,
                file_size=file_size,
                description=description,
                privacy_view=config.vk.CLIP_VISIBILITY,
            )
            upload_url = upload_data["upload_url"]

            with open(video_path, "rb") as f:
                async with session.post(
                    upload_url,
                    data={"file": f},
                    timeout=aiohttp.ClientTimeout(total=config.vk.UPLOAD_TIMEOUT),
                ) as resp:
                    video_info = await resp.json()

            if "error" in video_info:
                logger.error("VK upload error: %s", video_info["error"])
                return None

            vk_video_id = int(video_info["video_id"])
            vk_owner_id = int(video_info["owner_id"])

            for attempt in range(config.vk.POLL_ATTEMPTS):
                await asyncio.sleep(config.vk.POLL_INTERVAL)
                try:
                    result = await _vk_method(
                        "video.get",
                        session,
                        owner_id=vk_owner_id,
                        videos=f"{vk_owner_id}_{vk_video_id}",
                    )
                    if result and result.get("items"):
                        return vk_video_id, vk_owner_id
                except aiohttp.ClientError:
                    pass

            logger.warning("VK processing poll timed out for %s", video_path)

            return vk_video_id, vk_owner_id

    except Exception as e:
        logger.error("Error uploading %s: %s", video_path, e)
        return None
