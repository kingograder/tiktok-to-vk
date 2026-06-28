from datetime import datetime, timezone

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.database.base import Base
from app.database.models import Video


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        result = await conn.execute(text("PRAGMA table_info(videos)"))
        columns = {row[1] for row in result.fetchall()}
        if "username" not in columns:
            await conn.execute(text("ALTER TABLE videos ADD COLUMN username TEXT"))
        await conn.commit()


async def _find_video(session: AsyncSession, tiktok_id: str) -> Video | None:
    result = await session.execute(
        select(Video).where(Video.tiktok_id == tiktok_id)
    )
    return result.scalar_one_or_none()


async def mark_discovered(
    session: AsyncSession,
    tiktok_id: str,
    username: str | None = None,
) -> bool:
    existing = await _find_video(session, tiktok_id)
    if existing:
        if not existing.username and username:
            existing.username = username
        return True
    session.add(Video(tiktok_id=tiktok_id, username=username))
    return False


async def get_undownloaded(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.downloaded_at.is_(None),
            Video.uploaded_to_vk.is_(False),
        )
    )
    return list(result.scalars().all())


async def mark_downloaded(session: AsyncSession, tiktok_id: str, filename: str) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.filename = filename
        video.downloaded_at = datetime.now(timezone.utc)


async def mark_download_failed(session: AsyncSession, tiktok_id: str) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.filename = None
        video.downloaded_at = None


async def mark_uploaded(session: AsyncSession, tiktok_id: str, vk_video_id: int, vk_owner_id: int) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.uploaded_to_vk = True
        video.vk_video_id = vk_video_id
        video.vk_owner_id = vk_owner_id


async def mark_deleted(session: AsyncSession, tiktok_id: str) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.deleted_from_disk = True


async def get_pending_delete(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.uploaded_to_vk.is_(True),
            Video.deleted_from_disk.is_(False),
        )
    )
    return list(result.scalars().all())
