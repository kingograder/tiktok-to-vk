import asyncio
import logging
import os
import signal
import sys
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.functions import (
    get_undeleted,
    get_undownloaded,
    get_unuploaded,
    init_db,
    mark_deleted,
    mark_discovered,
    mark_downloaded,
    mark_uploaded,
)
from app.database.models import Video
from app.tiktok.downloader import download_video
from app.tiktok.scrapper import discover_posts
from app.validation import validate_tiktok, validate_vk
from app.video.processor import ensure_vertical
from app.vk.uploader import build_description, upload_clip
from config.config import config

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = config.app.DOWNLOAD_DIR

_shutdown = False
_retries: dict[str, int] = {}
_retries_lock = asyncio.Lock()


def _signal_handler(signum: int, frame: None = None) -> None:
    global _shutdown
    if _shutdown:
        logger.warning("Forced exit")
        os._exit(1)
    logger.info("Shutdown signal received, finishing current cycle...")
    _shutdown = True


def _get_db_url() -> str:
    return f"sqlite+aiosqlite:///{config.app.DB_PATH}"


def _parse_collections() -> list[str]:
    return [url.strip() for url in config.tiktok.COLLECTION_URL.split(",") if url.strip()]


def _cleanup_file_sync(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        logger.warning("Failed to delete %s: %s", path, e)
        return False


def _get_retry_count(vid: str) -> int:
    return _retries.get(vid, 0)


def _increment_retry(vid: str) -> int:
    _retries[vid] = _retries.get(vid, 0) + 1
    return _retries[vid]


def _reset_retry(vid: str) -> None:
    _retries.pop(vid, None)


async def _process_one(
    sem: asyncio.Semaphore,
    video: Video,
    item: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sem:
        if _shutdown:
            return

        vid = video.tiktok_id
        username = item.get("author", {}).get("uniqueId", video.username)
        logger.info("Processing %s @%s", vid, username)

        path = None

        if video.filename and not video.deleted_at:
            candidate = os.path.join(DOWNLOAD_DIR, video.filename)
            if os.path.isfile(candidate):
                path = candidate
                logger.info("File already on disk: %s", video.filename)

        if path is None:
            for attempt in range(config.app.MAX_RETRIES):
                if _shutdown:
                    return
                path = await download_video(
                    item,
                    DOWNLOAD_DIR,
                    config.tiktok.COOKIES_FILE,
                    config.tiktok.PROXY,
                )
                if path is not None:
                    break
                if attempt < config.app.MAX_RETRIES - 1:
                    await asyncio.sleep(2 * (attempt + 1))

            if path is None:
                _reset_retry(vid)
                logger.error("Failed to download %s @%s after %d attempts", vid, username, config.app.MAX_RETRIES)
                return

            try:
                path = await ensure_vertical(path)
            except Exception:
                logger.warning("ensure_vertical failed for %s, using original", vid, exc_info=True)

            async with session_factory() as session:
                await mark_downloaded(session, vid, os.path.basename(path))
                await session.commit()

            logger.info("Downloaded %s -> %s", vid, os.path.basename(path))

        for attempt in range(config.app.MAX_RETRIES):
            if _shutdown:
                return
            if not os.path.isfile(path):
                logger.error("File disappeared: %s", path)
                _reset_retry(vid)
                return

            desc = build_description(vid, username)
            result = await upload_clip(video_path=path, description=desc)

            if result is not None:
                vk_video_id, vk_owner_id = result
                async with session_factory() as session:
                    await mark_uploaded(session, vid, vk_video_id, vk_owner_id)
                    await session.commit()
                _reset_retry(vid)
                logger.info("Uploaded %s -> VK %d_%d", vid, vk_owner_id, vk_video_id)

                if config.app.CLEAR_DOWNLOADS:
                    deleted = await asyncio.to_thread(_cleanup_file_sync, path)
                    if deleted:
                        async with session_factory() as session:
                            await mark_deleted(session, vid)
                            await session.commit()
                            logger.info("Deleted %s from disk", os.path.basename(path))
                return

            retries = _increment_retry(vid)
            logger.warning("Upload failed for %s (attempt %d/%d, total retries: %d)",
                           vid, attempt + 1, config.app.MAX_RETRIES, retries)

            if retries >= config.app.MAX_RETRIES:
                logger.error("Giving up upload for %s after %d retries", vid, retries)
                _reset_retry(vid)
                return

            if attempt < config.app.MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))


async def process_cycle(session_factory: async_sessionmaker[AsyncSession]) -> None:
    collections = _parse_collections()
    logger.info("Loaded %d collections", len(collections))

    download_sem = asyncio.Semaphore(config.app.CONCURRENT_DOWNLOADS)

    for collection_url in collections:
        if _shutdown:
            break

        logger.info("Discovering posts from %s", collection_url)

        try:
            all_items = await discover_posts(
                collection_url,
                config.tiktok.COOKIES_FILE,
                config.tiktok.PROXY,
            )
        except ValueError:
            logger.error("Invalid collection URL: %s", collection_url)
            continue
        except Exception:
            logger.exception("Failed to discover posts from %s", collection_url)
            continue

        if not all_items:
            logger.info("Collection is empty or unavailable")
            continue

        async with session_factory() as session:
            new_count = 0
            for item in all_items:
                existed = await mark_discovered(
                    session,
                    str(item.get("id", "")),
                    item.get("author", {}).get("uniqueId"),
                )
                if not existed:
                    new_count += 1
            await session.commit()

        async with session_factory() as session:
            undownloaded = await get_undownloaded(session)
            unuploaded = await get_unuploaded(session)

        item_map = {str(item.get("id", "")): item for item in all_items}

        tasks = []
        processed_ids = set()

        for video in undownloaded:
            item = item_map.get(video.tiktok_id)
            if item:
                processed_ids.add(video.tiktok_id)
                tasks.append(_process_one(download_sem, video, item, session_factory))

        for video in unuploaded:
            if video.tiktok_id in processed_ids:
                continue
            item = item_map.get(video.tiktok_id)
            if not item:
                item = {"id": video.tiktok_id, "author": {"uniqueId": video.username or ""}}
            tasks.append(_process_one(download_sem, video, item, session_factory))

        logger.info("Collection: %d total, %d new, %d to download/upload", len(all_items), new_count, len(tasks))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if not _shutdown and config.app.CLEAR_DOWNLOADS:
        async with session_factory() as session:
            pending_delete = await get_undeleted(session)

        for video in pending_delete:
            if _shutdown:
                break
            if not video.filename:
                continue
            filepath = os.path.join(DOWNLOAD_DIR, video.filename)
            deleted = await asyncio.to_thread(_cleanup_file_sync, filepath)
            if deleted:
                async with session_factory() as session:
                    await mark_deleted(session, video.tiktok_id)
                    await session.commit()


async def run_once(session_factory: async_sessionmaker[AsyncSession], engine) -> None:
    await init_db(engine)
    await process_cycle(session_factory)
    await engine.dispose()


async def run_daemon(session_factory: async_sessionmaker[AsyncSession], engine) -> None:
    await init_db(engine)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler, sig, None)

    while not _shutdown:
        await process_cycle(session_factory)
        if not _shutdown:
            logger.info("Sleeping %d seconds...", config.app.CHECK_INTERVAL)
            await asyncio.sleep(config.app.CHECK_INTERVAL)

    await engine.dispose()
    logger.info("Daemon stopped")


def _check_prerequisites() -> None:
    if not config.tiktok.COOKIES_FILE or not os.path.exists(config.tiktok.COOKIES_FILE):
        logger.error("Cookies file not found: %s", config.tiktok.COOKIES_FILE)
        sys.exit(1)

    if not config.tiktok.COLLECTION_URL:
        logger.error("TIKTOK_COLLECTION_URL is not set in .env")
        sys.exit(1)

    if not config.vk.TOKEN:
        logger.error("VK_TOKEN is not set in .env")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    _check_prerequisites()

    log_file = config.app.LOG_FILE
    if log_file:
        log_dir = os.path.dirname(log_file) or "."
        os.makedirs(log_dir, exist_ok=True)
        log_filename = datetime.now().strftime("app_%Y-%m-%d_%H-%M-%S.log")
        log_path = os.path.join(log_dir, log_filename)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
            handlers=[
                logging.FileHandler(log_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="TikTok collection -> VK Clips")
    parser.add_argument("--once", action="store_true", help="Run single cycle then exit")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(config.app.DB_PATH) or ".", exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(config.app.TEMP_DIR, exist_ok=True)

    tiktok_ok = validate_tiktok()
    vk_ok = asyncio.run(validate_vk())

    if not tiktok_ok:
        logger.error("TikTok validation failed — check cookies, proxy, and collection URL")
        sys.exit(1)
    if not vk_ok:
        logger.error("VK validation failed — check VK_TOKEN")
        sys.exit(1)

    engine = create_async_engine(_get_db_url())
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    if args.once:
        asyncio.run(run_once(session_factory, engine))
    else:
        asyncio.run(run_daemon(session_factory, engine))
