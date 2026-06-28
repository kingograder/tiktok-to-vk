import asyncio
import json
import logging
import re
import time
import urllib.parse

import yt_dlp
from yt_dlp.networking.common import Request
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import int_or_none

from config.config import config

logger = logging.getLogger(__name__)

_COLLECTION_RE = re.compile(
    r"tiktok\.com/@(?P<user>[^/]+)/collection/(?P<title>[^?#]+)-(?P<id>\d+)"
)

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


def _traverse(obj, path, default=None):
    current = obj
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return default
        else:
            return default
        if current is None:
            return default
    return current


def _fetch_collection_sync(collection_url: str, cookies_file: str,
                           proxy: str | None = None) -> list[dict]:
    collection_id = _parse_collection_url(collection_url)
    if not collection_id:
        raise ValueError(f"Invalid collection URL: {collection_url}")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "cookiefile": cookies_file,
        "impersonate": ImpersonateTarget.from_str("chrome"),
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    all_items: list[dict] = []
    cursor = 0

    while True:
        params = {
            "aid": "1988",
            "collectionId": collection_id,
            "count": "30",
            "cursor": str(cursor),
            "sourceType": "113",
        }
        api_url = f"{_API_URL}?{urllib.parse.urlencode(params)}"

        last_error = None
        for attempt in range(config.app.MAX_RETRIES):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    req = Request(api_url)
                    resp = ydl.urlopen(req)
                    data = json.loads(resp.read())
                break
            except Exception as e:
                last_error = e
                err_msg = str(e)

                if any(c in err_msg for c in _COOKIE_ERRORS):
                    logger.error("Cookie error: %s — update cookies.txt", err_msg)
                    raise

                if any(n in err_msg for n in _NETWORK_ERRORS):
                    if attempt < config.app.MAX_RETRIES - 1:
                        logger.warning("Network error (attempt %d/%d): %s",
                                       attempt + 1, config.app.MAX_RETRIES, err_msg)
                        time.sleep(2 * (attempt + 1))
                        continue
                raise
        else:
            raise RuntimeError("Max retries exceeded for collection API")

        items = _traverse(data, ("itemList",)) or []

        for v in items:
            video_id = _traverse(v, ("id",)) or _traverse(v, ("aweme_id",))
            if not video_id:
                continue
            unique_id = _traverse(v, ("author", "uniqueId")) or ""
            all_items.append({
                "id": str(video_id),
                "author": {"uniqueId": unique_id},
            })

        has_more = _traverse(data, ("hasMore",), default=False)
        if not has_more:
            return all_items

        new_cursor = int_or_none(_traverse(data, ("cursor",)))
        if new_cursor and new_cursor != cursor:
            cursor = new_cursor
        else:
            cursor += len(items)

    return all_items


async def discover_posts(collection_url: str, cookies_file: str,
                         proxy: str | None = None) -> list[dict]:
    items = await asyncio.to_thread(
        _fetch_collection_sync, collection_url, cookies_file, proxy,
    )
    return items
