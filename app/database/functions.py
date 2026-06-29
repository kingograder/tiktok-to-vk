from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.database.base import Base
from app.database.models import Video


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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


async def bulk_mark_discovered(
    session: AsyncSession,
    items: list[dict],
) -> int:
    tiktok_ids = [str(item.get("id", "")) for item in items if item.get("id")]
    if not tiktok_ids:
        return 0

    result = await session.execute(
        select(Video).where(Video.tiktok_id.in_(tiktok_ids))
    )
    existing = {v.tiktok_id: v for v in result.scalars().all()}

    new_count = 0
    for item in items:
        vid = str(item.get("id", ""))
        if not vid:
            continue
        username = item.get("author", {}).get("uniqueId")
        if vid in existing:
            if not existing[vid].username and username:
                existing[vid].username = username
        else:
            session.add(Video(tiktok_id=vid, username=username))
            new_count += 1

    return new_count


async def get_undownloaded(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(Video.downloaded_at.is_(None))
    )
    return list(result.scalars().all())


async def get_unuploaded(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.downloaded_at.is_not(None),
            Video.uploaded_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_undeleted(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.uploaded_at.is_not(None),
            Video.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def mark_downloaded(session: AsyncSession, tiktok_id: str, filename: str) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.filename = filename
        video.downloaded_at = datetime.now(timezone.utc)


async def mark_uploaded(session: AsyncSession, tiktok_id: str, vk_video_id: int, vk_owner_id: int) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.uploaded_at = datetime.now(timezone.utc)
        video.vk_video_id = vk_video_id
        video.vk_owner_id = vk_owner_id


async def mark_deleted(session: AsyncSession, tiktok_id: str) -> None:
    video = await _find_video(session, tiktok_id)
    if video:
        video.deleted_at = datetime.now(timezone.utc)
