import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Media(Base):
    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant = relationship("Tenant", back_populates="media")
    playlist_items = relationship("PlaylistItem", back_populates="media", cascade="all, delete-orphan")


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    transition_type: Mapped[str] = mapped_column(String(32), default="fade")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant = relationship("Tenant", back_populates="playlists")
    items = relationship("PlaylistItem", back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistItem.display_order")
    schedules = relationship("Schedule", back_populates="playlist")


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id: Mapped[str] = mapped_column(String(36), ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id: Mapped[str] = mapped_column(String(36), ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[int] = mapped_column(Integer, default=10)

    playlist = relationship("Playlist", back_populates="items")
    media = relationship("Media", back_populates="playlist_items")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    playlist_id: Mapped[str] = mapped_column(String(36), ForeignKey("playlists.id", ondelete="SET NULL"), nullable=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon … 6=Sun, -1=everyday
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)    # "HH:MM"

    playlist = relationship("Playlist", back_populates="schedules")
