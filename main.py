import asyncio
import logging
import os
import signal
import sys
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from config.config import config
from app.tiktok.downloader import download_video, extract_username, fetch_video_ids, build_description
from app.vk.uploader import upload_clip
from app.video.processor import ensure_vertical
from app.database.functions import (
    get_new_ids, mark_downloaded, mark_uploaded, get_pending_upload,
    get_pending_delete, mark_deleted,
)
from app.database.functions import init_db

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = config.app.DOWNLOAD_DIR

_shutdown = False
_retries: dict[str, int] = {}
_retries_lock = asyncio.Lock()


def _signal_handler(signum: int, frame) -> None:
    global _shutdown
    if _shutdown:
        logger.warning("Forced exit")
        os._exit(1)
    logger.info("Shutdown signal received, finishing current cycle...")
    _shutdown = True


def _get_db_url() -> str:
    return f"sqlite+aiosqlite:///{config.app.DB_PATH}"


def _load_collections_sync() -> list[str]:
    collections_file = "collections.txt"
    if not os.path.exists(collections_file):
        return [config.tiktok.COLLECTION_URL]

    collections = []
    with open(collections_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            collections.append(line.split()[0])
    return collections


async def _load_collections() -> list[str]:
    return await asyncio.to_thread(_load_collections_sync)


def _cleanup_partial_file_sync(video_id: str, download_dir: str) -> None:
    for f in os.listdir(download_dir):
        stem = f.rsplit(".", 1)[0] if "." in f else f
        if stem == video_id:
            path = os.path.join(download_dir, f)
            try:
                os.remove(path)
                logger.info("Removed partial file %s", f)
            except OSError:
                pass


async def _download_one(
    collection_url: str,
    position: int,
    vid: str,
    username: str | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if _shutdown:
        return

    logger.info("Download %s", vid)

    path, author_name = await download_video(
        collection_url,
        position=position,
        video_id=vid,
        download_dir=DOWNLOAD_DIR,
        cookies_file=config.tiktok.COOKIES_FILE,
        proxy=config.tiktok.PROXY,
        username=username,
    )
    if path is None:
        await asyncio.to_thread(_cleanup_partial_file_sync, vid, DOWNLOAD_DIR)
        return

    path = await ensure_vertical(path)

    async with session_factory() as session:
        await mark_downloaded(session, vid, os.path.basename(path), username, author_name)
        await session.commit()


async def _upload_one(
    sem: asyncio.Semaphore,
    video,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sem:
        if _shutdown:
            return

        path = os.path.join(DOWNLOAD_DIR, video.filename)
        if not os.path.exists(path):
            logger.warning("Missing %s, skip upload", video.filename)
            async with _retries_lock:
                _retries[video.tiktok_id] = _retries.get(video.tiktok_id, 0) + 1
            return

        desc = build_description(video.tiktok_id, video.username, video.author_name)
        result = await upload_clip(
            video_path=path,
            description=desc,
        )
        if result is None:
            async with _retries_lock:
                _retries[video.tiktok_id] = _retries.get(video.tiktok_id, 0) + 1
                if _retries[video.tiktok_id] >= config.app.MAX_RETRIES:
                    logger.error("Giving up on %s after %d retries", video.tiktok_id, _retries[video.tiktok_id])
            return

        vk_video_id, vk_owner_id = result
        async with session_factory() as session:
            await mark_uploaded(session, video.tiktok_id, vk_video_id, vk_owner_id)
            await session.commit()


def _delete_file_sync(path: str) -> bool:
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except OSError:
            logger.warning("Failed to delete %s", path)
    return False


async def process_cycle(session_factory: async_sessionmaker[AsyncSession]) -> None:
    collections = await _load_collections()

    download_sem = asyncio.Semaphore(config.app.CONCURRENT_DOWNLOADS)

    # Phase 1: download all videos from all collections
    for collection_url in collections:
        if _shutdown:
            break

        username = extract_username(collection_url)

        all_video_ids = await fetch_video_ids(
            collection_url,
            cookies_file=config.tiktok.COOKIES_FILE,
            proxy=config.tiktok.PROXY,
        )

        async with session_factory() as session:
            video_ids = await get_new_ids(session, all_video_ids)

        position_map = {vid: i + 1 for i, vid in enumerate(all_video_ids)}
        tasks = [
            _download_one(download_sem, collection_url, position_map[vid], vid, username, session_factory)
            for vid in video_ids
        ]
        await asyncio.gather(*tasks)

    if _shutdown:
        return

    # Phase 2: upload to VK
    upload_sem = asyncio.Semaphore(config.app.CONCURRENT_UPLOADS)

    async with session_factory() as session:
        pending = await get_pending_upload(session)

    tasks = [_upload_one(upload_sem, video, session_factory) for video in pending]
    await asyncio.gather(*tasks)

    if _shutdown:
        return

    # Phase 3: cleanup uploaded files
    async with session_factory() as session:
        pending_delete = await get_pending_delete(session)

    for video in pending_delete:
        if _shutdown:
            break
        path = os.path.join(DOWNLOAD_DIR, video.filename)
        deleted = await asyncio.to_thread(_delete_file_sync, path)
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


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    log_dir = config.app.LOG_DIR
    if log_dir:
        log_dir = os.path.dirname(log_dir) or "."
        os.makedirs(log_dir, exist_ok=True)
        log_filename = datetime.now().strftime("debug_%Y-%m-%d_%H-%M-%S.log")
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

    if not os.path.exists(config.tiktok.COOKIES_FILE):
        logger.error("Cookies file not found: %s", config.tiktok.COOKIES_FILE)
        sys.exit(1)

    os.makedirs(os.path.dirname(config.app.DB_PATH) or ".", exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    engine = create_async_engine(_get_db_url())
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    if args.once:
        asyncio.run(run_once(session_factory, engine))
    else:
        asyncio.run(run_daemon(session_factory, engine))
