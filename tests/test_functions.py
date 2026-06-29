import pytest
from sqlalchemy import select

from app.database.functions import bulk_mark_discovered, mark_downloaded, mark_uploaded
from app.database.models import Video


class TestBulkMarkDiscovered:
    async def test_inserts_new_videos(self, session):
        items = [
            {"id": "100", "author": {"uniqueId": "user_a"}},
            {"id": "200", "author": {"uniqueId": "user_b"}},
        ]
        new_count = await bulk_mark_discovered(session, items)
        await session.commit()

        assert new_count == 2
        result = await session.execute(select(Video))
        videos = {v.tiktok_id: v for v in result.scalars().all()}
        assert "100" in videos
        assert "200" in videos
        assert videos["100"].username == "user_a"

    async def test_skips_existing(self, session):
        session.add(Video(tiktok_id="100", username="existing"))
        await session.commit()

        items = [{"id": "100", "author": {"uniqueId": "new_name"}}]
        new_count = await bulk_mark_discovered(session, items)
        await session.commit()

        assert new_count == 0
        result = await session.execute(select(Video))
        video = result.scalar_one()
        assert video.username == "existing"

    async def test_updates_missing_username(self, session):
        session.add(Video(tiktok_id="100", username=None))
        await session.commit()

        items = [{"id": "100", "author": {"uniqueId": "filled_name"}}]
        new_count = await bulk_mark_discovered(session, items)
        await session.commit()

        assert new_count == 0
        result = await session.execute(select(Video))
        video = result.scalar_one()
        assert video.username == "filled_name"

    async def test_empty_items(self, session):
        new_count = await bulk_mark_discovered(session, [])
        assert new_count == 0

    async def test_items_without_id(self, session):
        items = [{"author": {"uniqueId": "user_a"}}]
        new_count = await bulk_mark_discovered(session, items)
        assert new_count == 0

    async def test_mixed_new_and_existing(self, session):
        session.add(Video(tiktok_id="100", username="old"))
        await session.commit()

        items = [
            {"id": "100", "author": {"uniqueId": "old"}},
            {"id": "200", "author": {"uniqueId": "new_user"}},
        ]
        new_count = await bulk_mark_discovered(session, items)
        await session.commit()

        assert new_count == 1
        result = await session.execute(select(Video))
        videos = {v.tiktok_id: v for v in result.scalars().all()}
        assert len(videos) == 2
        assert videos["200"].username == "new_user"


class TestMarkDownloaded:
    async def test_sets_filename_and_timestamp(self, session):
        session.add(Video(tiktok_id="vid1"))
        await session.commit()

        await mark_downloaded(session, "vid1", "vid1.mp4")
        await session.commit()

        result = await session.execute(select(Video).where(Video.tiktok_id == "vid1"))
        video = result.scalar_one()
        assert video.filename == "vid1.mp4"
        assert video.downloaded_at is not None

    async def test_nonexistent_video(self, session):
        await mark_downloaded(session, "nonexistent", "file.mp4")
        await session.commit()


class TestMarkUploaded:
    async def test_sets_vk_ids_and_timestamp(self, session):
        session.add(Video(tiktok_id="vid1"))
        await session.commit()

        await mark_uploaded(session, "vid1", vk_video_id=12345, vk_owner_id=67890)
        await session.commit()

        result = await session.execute(select(Video).where(Video.tiktok_id == "vid1"))
        video = result.scalar_one()
        assert video.vk_video_id == 12345
        assert video.vk_owner_id == 67890
        assert video.uploaded_at is not None
