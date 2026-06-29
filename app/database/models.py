from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tiktok_id: Mapped[str] = mapped_column(unique=True)
    filename: Mapped[str | None] = mapped_column(nullable=True)
    username: Mapped[str | None] = mapped_column(nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    vk_video_id: Mapped[int | None] = mapped_column(nullable=True)
    vk_owner_id: Mapped[int | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
