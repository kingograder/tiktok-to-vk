from datetime import datetime, timezone

from sqlalchemy import text, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.database.base import Base
from app.database.models import Video


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        valid_columns = {
            "username": "TEXT",
            "author_name": "TEXT",
        }
        for col, typedef in valid_columns.items():
            if not col.isidentifier() or typedef not in ("TEXT", "INTEGER", "REAL", "BLOB"):
                continue
            try:
                await conn.execute(text(f"ALTER TABLE videos ADD COLUMN {col} {typedef}"))
            except OperationalError:
                pass
        await conn.commit()


async def get_new_ids(session: AsyncSession, candidate_ids: list[str]) -> list[str]:
    if not candidate_ids:
        return []
    result = await session.execute(
        select(Video.tiktok_id).where(Video.tiktok_id.in_(candidate_ids))
    )
    known = set(result.scalars().all())
    return [vid for vid in candidate_ids if vid not in known]


async def mark_downloaded(session: AsyncSession, tiktok_id: str, filename: str, username: str | None = None, author_name: str | None = None) -> None:
    video = Video(
        tiktok_id=tiktok_id,
        filename=filename,
        username=username,
        author_name=author_name,
        downloaded_at=datetime.now(timezone.utc),
        uploaded_to_vk=False,
        deleted_from_disk=False,
    )
    session.add(video)


async def mark_uploaded(session: AsyncSession, tiktok_id: str, vk_video_id: int, vk_owner_id: int) -> None:
    video = await session.get(Video, tiktok_id)
    if video:
        video.uploaded_to_vk = True
        video.vk_video_id = vk_video_id
        video.vk_owner_id = vk_owner_id


async def mark_deleted(session: AsyncSession, tiktok_id: str) -> None:
    video = await session.get(Video, tiktok_id)
    if video:
        video.deleted_from_disk = True


async def get_pending_upload(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.downloaded_at.isnot(None),
            Video.uploaded_to_vk.is_(False),
        )
    )
    return list(result.scalars().all())


async def get_pending_delete(session: AsyncSession) -> list[Video]:
    result = await session.execute(
        select(Video).where(
            Video.uploaded_to_vk.is_(True),
            Video.deleted_from_disk.is_(False),
        )
    )
    return list(result.scalars().all())
