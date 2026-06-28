import asyncio
import logging
import os
import signal
import sys
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.functions import (
    _find_video,
    get_pending_delete,
    get_undownloaded,
    init_db,
    mark_deleted,
    mark_discovered,
    mark_download_failed,
    mark_downloaded,
    mark_uploaded,
)
from app.database.models import Video
from app.tiktok.downloader import download_video
from app.tiktok.scrapper import discover_posts
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
        return False
    except OSError as e:
        logger.warning("Failed to delete %s: %s", path, e)
        return False


async def _process_one(
    sem: asyncio.Semaphore,
    item: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sem:
        if _shutdown:
            return

        vid = str(item.get("id", ""))
        if not vid:
            logger.warning("Skipping item with empty id")
            return

        username = item.get("author", {}).get("uniqueId")
        logger.info("Processing %s @%s", vid, username)

        path = await download_video(
            item,
            DOWNLOAD_DIR,
            config.tiktok.COOKIES_FILE,
            config.tiktok.PROXY,
        )

        async with session_factory() as session:
            if path is None:
                logger.error("Failed to download %s @%s", vid, username)
                await mark_download_failed(session, vid)
                await session.commit()
                return

            path = await ensure_vertical(path)
            await mark_downloaded(session, vid, os.path.basename(path))
            await session.commit()

        logger.info("Downloaded %s -> %s", vid, os.path.basename(path))

    desc = build_description(vid, username)
    result = await upload_clip(video_path=path, description=desc)

    if result is None:
        async with _retries_lock:
            _retries[vid] = _retries.get(vid, 0) + 1
            retries_count = _retries[vid]
        if retries_count >= config.app.MAX_RETRIES:
            logger.error("Giving up on %s after %d retries", vid, retries_count)
            async with session_factory() as session:
                await mark_download_failed(session, vid)
                await session.commit()
            async with _retries_lock:
                _retries.pop(vid, None)
        return

    async with _retries_lock:
        _retries.pop(vid, None)

    vk_video_id, vk_owner_id = result

    async with session_factory() as session:
        await mark_uploaded(session, vid, vk_video_id, vk_owner_id)
        await session.commit()

    logger.info("Uploaded %s -> VK %d_%d", vid, vk_owner_id, vk_video_id)

    if config.app.CLEAR_DOWNLOADS:
        async with session_factory() as session:
            video_row = await _find_video(session, vid)
            if video_row and video_row.filename:
                deleted = await asyncio.to_thread(_cleanup_file_sync, os.path.join(DOWNLOAD_DIR, video_row.filename))
                if deleted:
                    await mark_deleted(session, vid)
                    await session.commit()
                    logger.info("Deleted %s from disk", video_row.filename)


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
            pending = await get_undownloaded(session)

        item_map = {str(item.get("id", "")): item for item in all_items}

        tasks = []
        logger.info("Collection: %d total, %d new, %d to download", len(all_items), new_count, len(tasks))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if not _shutdown:
        async with session_factory() as session:
            pending_delete = await get_pending_delete(session)

        for video in pending_delete:
            if _shutdown:
                break
            if not video.filename:
                continue
            deleted = await asyncio.to_thread(_cleanup_file_sync, os.path.join(DOWNLOAD_DIR, video.filename))
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

    engine = create_async_engine(_get_db_url())
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    if args.once:
        asyncio.run(run_once(session_factory, engine))
    else:
        asyncio.run(run_daemon(session_factory, engine))
