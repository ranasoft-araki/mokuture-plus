import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Integer, ForeignKey, func, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_playlist_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 承認フロー: 端末は接続時に自己登録し pending となる。管理画面での承認で active になる。
    # 既存端末との後方互換のため既定は active（マイグレーションでも DEFAULT 'active'）。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    # 物理端末の安定ID（agent は machine-id / MAC 由来、Web はローカル保存UUID）。
    # (tenant_id, hardware_id) で再登録を冪等化し、承認待ちの重複行を防ぐ。
    hardware_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    force_update_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tenant = relationship("Tenant", back_populates="devices")


class Locker(Base):
    __tablename__ = "lockers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    door_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="locked")  # locked | unlocked | error
    last_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_relock_sec: Mapped[int] = mapped_column(Integer, default=60)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    occupied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="lockers")
