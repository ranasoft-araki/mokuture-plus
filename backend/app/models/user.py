import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="staff")  # operator | reseller | admin | staff | kiosk
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # パスワードを最後に変更した時刻(naive-UTC・秒に切り捨て)。これより前に発行された
    # トークンは受け付けない(services/auth.token_predates_password_change)。
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="users")
    push_subscriptions = relationship("PushSubscription", back_populates="user", cascade="all, delete-orphan")
