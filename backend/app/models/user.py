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


class UserInvitation(Base):
    """管理画面から送った招待(まだユーザーになっていない人)。

    招待メールのリンクを開いた本人がパスワードを決めると User が作られ、accepted_at が入る。
    リンクのトークンそのものは保存せず sha256 だけを持つ(DB が漏れてもリンクを作れない)。
    招待し直すとトークンを作り直す＝前に送ったリンクは使えなくなる。
    日時は naive-UTC で書く(本番 Neon では aware で読み戻ることがあるので比べる前に to_naive_utc)。
    """
    __tablename__ = "user_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 送った管理者の users.id(外部キーは張らない)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 最後に送った時刻
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
