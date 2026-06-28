import asyncio
import logging
import re

from curl_cffi import requests

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
)


def _parse_cookies(path: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except OSError as e:
        logger.warning("Failed to read cookies from %s: %s", path, e)
    return cookies


def _parse_collection_url(url: str) -> str | None:
    m = _COLLECTION_RE.search(url)
    if not m:
        return None
    return m.group("id")


def _fetch_collection_sync(collection_url: str, cookies_file: str,
                           proxy: str | None = None) -> list[dict]:
    collection_id = _parse_collection_url(collection_url)
    if not collection_id:
        raise ValueError(f"Invalid collection URL: {collection_url}")

    cookies = _parse_cookies(cookies_file)

    all_items: list[dict] = []
    cursor = 0

    for attempt in range(3):
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
                proxies=proxy,
            )
            data = resp.json()
            items = data.get("itemList", [])

            for v in items:
                all_items.append({
                    "id": str(v["id"]),
                    "author": {"uniqueId": v.get("author", {}).get("uniqueId", "")},
                })

            if not data.get("hasMore"):
                break
            cursor += len(items)

        except Exception as e:
            err_msg = str(e)
            if any(n in err_msg for n in _NETWORK_ERRORS) and attempt < 2:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            raise

    return all_items


async def discover_posts(collection_url: str, cookies_file: str,
                         proxy: str | None = None) -> list[dict]:
    items = await asyncio.to_thread(
        _fetch_collection_sync, collection_url, cookies_file, proxy,
    )
    logger.info("Discovered %d entries", len(items))
    return items
