import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReceptionLog(Base):
    __tablename__ = "reception_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    visitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(512), nullable=True)
    staff: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str] = mapped_column(String(32), default="form")  # form | qr | calendar
    state: Mapped[str] = mapped_column(String(32), default="received")  # received | notified | accepted(受付) | phone(電話) | declined(お断り) | completed | cancelled
    staff_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("visitor_appointments.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # スタッフが OK/NG を押した時刻
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant = relationship("Tenant", back_populates="reception_logs")
