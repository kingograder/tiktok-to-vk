import logging
import os
import sys

import aiohttp

from app.tiktok.scrapper import _parse_collection_url, _parse_cookies
from config.config import config

logger = logging.getLogger(__name__)


def check_prerequisites() -> None:
    if not config.tiktok.COOKIES_FILE or not os.path.exists(config.tiktok.COOKIES_FILE):
        logger.error("Cookies file not found: %s", config.tiktok.COOKIES_FILE)
        sys.exit(1)

    if not config.tiktok.COLLECTION_URL:
        logger.error("TIKTOK_COLLECTION_URL is not set in .env")
        sys.exit(1)

    if not config.vk.TOKEN:
        logger.error("VK_TOKEN is not set in .env")
        sys.exit(1)


async def validate_tiktok() -> bool:
    ok = True

    logger.info("Checking TikTok cookies...")
    cookies = _parse_cookies(config.tiktok.COOKIES_FILE)

    if not cookies:
        logger.error("Cookies file %s is empty or invalid", config.tiktok.COOKIES_FILE)
        return False

    has_ttwid = "ttwid" in cookies
    has_session = "sessionid" in cookies or "sid_tt" in cookies
    if not has_ttwid:
        logger.error("Cookies file missing 'ttwid' cookie — TikTok will block requests")
        ok = False
    if not has_session:
        logger.warning("Cookies file missing session cookies — some features may not work")

    logger.info("Validating collection URLs...")
    urls = [u.strip() for u in config.tiktok.COLLECTION_URL.split(",") if u.strip()]
    for url in urls:
        collection_id = _parse_collection_url(url)
        if not collection_id:
            logger.error("Invalid collection URL format: %s", url)
            logger.error("Expected: https://www.tiktok.com/@user/collection/name-ID")
            ok = False
        else:
            logger.info("Collection OK: %s (id=%s)", url, collection_id)

    logger.info("Testing TikTok connectivity...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.tiktok.com/",
                proxy=config.tiktok.PROXY,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.error("TikTok is unreachable (HTTP %d) — check proxy and network", resp.status)
                    ok = False
                else:
                    logger.info("TikTok: connection OK")
    except Exception as e:
        logger.error("TikTok is unreachable: %s — check proxy and network", e)
        ok = False

    return ok


async def validate_vk() -> bool:
    logger.info("Checking VK token...")
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "access_token": config.vk.TOKEN,
                "v": config.vk.API_VERSION,
            }
            async with session.post(
                "https://api.vk.com/method/users.get",
                data=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()

            if "error" in data:
                error = data["error"]
                code = error.get("error_code") if isinstance(error, dict) else None
                msg = error.get("error_msg", str(error)) if isinstance(error, dict) else str(error)

                if code in (4, 5):
                    logger.error("VK token is invalid or expired: %s", msg)
                elif code == 15:
                    logger.error("VK token access denied: %s", msg)
                else:
                    logger.error("VK API error %s: %s", code, msg)
                return False

            users = data.get("response", [])
            if users:
                user = users[0]
                logger.info(
                    "VK: authenticated as %s %s (id=%s)",
                    user.get("first_name"), user.get("last_name"), user.get("id"),
                )
            return True

    except Exception as e:
        logger.error("VK is unreachable: %s — check network", e)
        return False
