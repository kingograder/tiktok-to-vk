import asyncio
import logging
import os
import re
import time

from curl_cffi import requests

from config.config import config

logger = logging.getLogger(__name__)

_COLLECTION_RE = re.compile(r"tiktok\.com/@(?P<user>[^/]+)/collection/(?P<title>[^?#]+)-(?P<id>\d+)")

_API_URL = "https://www.tiktok.com/api/collection/item_list/"

_NETWORK_ERRORS = (
    "Connection reset by peer",
    "Connection refused",
    "Read timed out",
    "Failed to resolve",
    "Max retries exceeded",
    "Connection timed out",
)

_COOKIE_ERRORS = (
    "Log in for access",
    "status code 10203",
)


def _parse_collection_url(url: str) -> str | None:
    m = _COLLECTION_RE.search(url)
    if not m:
        return None
    return m.group("id")


def _parse_cookies(path: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not os.path.exists(path):
        logger.warning("Cookies file not found: %s", path)
        return cookies
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies


def _traverse(obj, path, default=None):
    current = obj
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            if key < 0 or key >= len(current):
                return default
            current = current[key]
        else:
            return default
        if current is None:
            return default
    return current


def _fetch_collection_sync(collection_url: str, cookies_file: str, proxy: str | None = None) -> list[dict]:
    collection_id = _parse_collection_url(collection_url)
    if not collection_id:
        raise ValueError(f"Invalid collection URL: {collection_url}")

    cookies = _parse_cookies(cookies_file)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    all_items: list[dict] = []
    cursor = 0

    while True:
        last_error = None
        for attempt in range(config.app.MAX_RETRIES):
            try:
                resp = requests.get(
                    _API_URL,
                    params={
                        "aid": "1988",
                        "collectionId": collection_id,
                        "count": 30,
                        "cursor": cursor,
                        "sourceType": "113",
                    },
                    cookies=cookies,
                    impersonate="chrome",
                    proxies=proxies,
                )
                data = resp.json()

                status_code = data.get("statusCode")
                if status_code and status_code != 0:
                    err_msg = f"TikTok API error: statusCode={status_code}"
                    if status_code == 10203:
                        logger.error("Cookie error — update cookies.txt")
                        raise RuntimeError(err_msg)
                    raise RuntimeError(err_msg)

                items = _traverse(data, ("itemList",)) or []

                for v in items:
                    video_id = _traverse(v, ("id",)) or _traverse(v, ("aweme_id",)) or _traverse(v, ("video", "id"))
                    if not video_id:
                        logger.debug("Skipping item without id: %s", list(v.keys()))
                        continue
                    unique_id = _traverse(v, ("author", "uniqueId")) or ""
                    all_items.append(
                        {
                            "id": str(video_id),
                            "author": {"uniqueId": unique_id},
                        }
                    )

                if not data.get("hasMore"):
                    return all_items

                new_cursor = _traverse(data, ("cursor",))
                if new_cursor is not None and new_cursor != cursor:
                    cursor = new_cursor
                else:
                    cursor += len(items)
                    if not items:
                        return all_items
                break

            except Exception as e:
                last_error = e
                err_msg = str(e)

                if any(c in err_msg for c in _COOKIE_ERRORS):
                    logger.error("Cookie error: %s — update cookies.txt", err_msg)
                    raise

                if any(n in err_msg for n in _NETWORK_ERRORS):
                    if attempt < config.app.MAX_RETRIES - 1:
                        logger.warning(
                            "Network error (attempt %d/%d): %s", attempt + 1, config.app.MAX_RETRIES, err_msg
                        )
                        time.sleep(2 * (attempt + 1))
                        continue
                raise
        else:
            if last_error:
                raise last_error

    return all_items


async def discover_posts(collection_url: str, cookies_file: str, proxy: str | None = None) -> list[dict]:
    items = await asyncio.to_thread(
        _fetch_collection_sync,
        collection_url,
        cookies_file,
        proxy,
    )
    return items
