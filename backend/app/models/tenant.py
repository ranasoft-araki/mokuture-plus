import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_color: Mapped[str] = mapped_column(String(7), default="#4a7c4e")
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    media = relationship("Media", back_populates="tenant", cascade="all, delete-orphan")
    playlists = relationship("Playlist", back_populates="tenant", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="tenant", cascade="all, delete-orphan")
    reception_logs = relationship("ReceptionLog", back_populates="tenant", cascade="all, delete-orphan")
    lockers = relationship("Locker", back_populates="tenant", cascade="all, delete-orphan")
    notification_settings = relationship("NotificationSetting", back_populates="tenant", cascade="all, delete-orphan")
    push_subscriptions = relationship("PushSubscription", back_populates="tenant", cascade="all, delete-orphan")
