import asyncio
import logging
import os

import aiohttp

from config.config import config

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method"


async def _vk_method(method: str, session: aiohttp.ClientSession, **params) -> dict:
    params["access_token"] = config.vk.TOKEN
    params["v"] = config.vk.API_VERSION
    async with session.post(f"{VK_API_URL}/{method}", data=params) as resp:
        data = await resp.json()
    if "error" in data:
        raise Exception(f"VK API error: {data['error']}")
    return data["response"]


def _get_file_size(video_path: str) -> int:
    return os.path.getsize(video_path)


async def upload_clip(video_path: str, description: str) -> tuple[int, int] | None:
    file_size = await asyncio.to_thread(_get_file_size, video_path)

    try:
        async with aiohttp.ClientSession() as session:
            # 1. get upload url
            upload_data = await _vk_method("video.save", session, file_size=file_size, clip=1)
            upload_url = upload_data["upload_url"]

            # 2. upload file (with proper context manager)
            with open(video_path, "rb") as f:
                async with session.post(
                    upload_url,
                    data={"file": f},
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as resp:
                    video_info = await resp.json()

            if "error" in video_info:
                logger.error("VK upload error: %s", video_info["error"])
                return None

            vk_video_id = int(video_info["video_id"])
            vk_owner_id = int(video_info["owner_id"])

            # 3. poll until VK finishes processing
            for attempt in range(config.vk_upload.POLL_ATTEMPTS):
                await asyncio.sleep(config.vk_upload.POLL_INTERVAL)
                try:
                    result = await _vk_method("video.get", session, owner_id=vk_owner_id, videos=f"{vk_owner_id}_{vk_video_id}")
                    if result and result.get("items"):
                        break
                except Exception:
                    if attempt == config.vk_upload.POLL_ATTEMPTS - 1:
                        logger.warning("VK processing poll timed out for %s", video_path)

            # 4. edit description
            await _vk_method(
                "video.edit",
                session,
                video_id=vk_video_id,
                owner_id=vk_owner_id,
                description=description,
                privacy_view=config.vk.CLIP_VISIBILITY,
            )

            # 5. publish
            await _vk_method(
                "video.publish",
                session,
                video_id=vk_video_id,
                owner_id=vk_owner_id,
            )

            return vk_video_id, vk_owner_id

    except Exception as e:
        logger.error("Error uploading %s: %s", video_path, e)
        return None
