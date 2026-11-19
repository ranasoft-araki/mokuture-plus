import secrets
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VisitorAppointment(Base):
    __tablename__ = "visitor_appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    visitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    staff: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    meeting_room_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("meeting_rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending | received | expired
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # ── Google カレンダー連携(→ CLAUDE.md「Google カレンダー連携」・models/calendar_integration.py) ──
    # 結び付いている Google のイベント。(tenant_id, gcal_event_id) で一意(main._ensure_schema)。
    gcal_event_id: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    gcal_calendar_id: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # どちらで作られた予定か。"google"=Google から取り込んだ / None=mokuture で登録した。
    gcal_origin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Google のイベントの `updated`(変わったときだけ取り込み直す)。
    gcal_updated: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 書き出しの状態。pending=まだ送っていない / synced=送れた / error=送れなかった(定期同期で再送)。
    gcal_sync_state: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
