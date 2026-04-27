import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_color: Mapped[str] = mapped_column(String(7), default="#4a7c4e")
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    font: Mapped[str] = mapped_column(String(64), default="Noto Sans JP / Inter")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Kiosk screen messages
    kiosk_welcome_message: Mapped[str] = mapped_column(String(255), default="ようこそ")
    kiosk_sub_message: Mapped[str] = mapped_column(String(255), default="ご用件をお選びください")
    kiosk_calling_message: Mapped[str] = mapped_column(String(255), default="担当者をお呼びしています。少々お待ちください。")
    kiosk_complete_message: Mapped[str] = mapped_column(String(255), default="担当者がご案内します")
    kiosk_idle_timeout_sec: Mapped[int] = mapped_column(Integer, default=60)
    kiosk_complete_timeout_sec: Mapped[int] = mapped_column(Integer, default=10)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    media = relationship("Media", back_populates="tenant", cascade="all, delete-orphan")
    playlists = relationship("Playlist", back_populates="tenant", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="tenant", cascade="all, delete-orphan")
    reception_logs = relationship("ReceptionLog", back_populates="tenant", cascade="all, delete-orphan")
    lockers = relationship("Locker", back_populates="tenant", cascade="all, delete-orphan")
    notification_settings = relationship("NotificationSetting", back_populates="tenant", cascade="all, delete-orphan")
    push_subscriptions = relationship("PushSubscription", back_populates="tenant", cascade="all, delete-orphan")
