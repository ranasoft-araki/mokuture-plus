import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StaffNotificationRoute(Base):
    """訪問先担当者ごとの通知先と代理通知(エスカレーション)設定。

    `staff_name` は `tenants.staff_list`(キオスクの訪問先ドロップダウン)の1件＝
    `reception_logs.staff` に入る文字列と突き合わせる。行が無い担当者は従来どおり
    テナント共通の通知先だけに送る（後方互換）。

    宛先(`config_json`)は Webhook URL を含むため `services/crypto.py`(Fernet)で暗号化保存する
    （CLAUDE.md「秘密情報の暗号化」）。Slack は既存の OAuth 連携(type="slack" の Bot Token)を
    使い回し、チャンネルだけ担当者ごとに差し替える＝追加スコープ不要。
    """

    __tablename__ = "staff_notification_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    staff_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 暗号化 JSON: {slack_channel_id, slack_channel_name, email, webhook_url}
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    # テナント共通の通知先(Slack/Webhook/プッシュ)へも送るか。既定 True＝従来の動きを維持。
    include_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 代理通知先＝別の担当者名。応答が無いとき、その担当者の通知先へ1段だけ転送する(連鎖しない)。
    fallback_staff_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 応答が無いと判断するまでの秒数。0 = 代理通知しない。
    escalate_after_sec: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="staff_notification_routes")
