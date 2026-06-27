from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Video(Base):
    __tablename__ = "videos"

    tiktok_id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    uploaded_to_vk: Mapped[bool] = mapped_column(Boolean, default=False)
    vk_video_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vk_owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_from_disk: Mapped[bool] = mapped_column(Boolean, default=False)
