"""Google カレンダー連携(来社予定 ⇔ Google カレンダー)。→ CLAUDE.md「Google カレンダー連携」節。

テナントにつき 1 行(= 連携できる Google アカウントは 1 つ)。方向はどちらか一方:
  - `to_google`   … mokuture の来社予定を Google カレンダーへ書き出す
  - `from_google` … Google カレンダーの予定を来社予定として取り込む
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DIRECTIONS = ("to_google", "from_google")


class CalendarIntegration(Base):
    __tablename__ = "calendar_integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="google")
    # Fernet 暗号化した {refresh_token, access_token, access_expires_at}。API・ログには一切出さない。
    # 連携を解除すると "{}" に戻す(行は残して、同じアカウントで結び直したときに設定を引き継ぐ)。
    credentials_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    account_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # active=同期する / reauth_required=Google 側で許可が取り消された・期限切れ / disconnected=解除済み
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    direction: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # DIRECTIONS / 未選択=None
    calendar_id: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    calendar_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 取り込み(from_google)のときだけ使う。タイトルにこの言葉を含む予定だけ取り込む(空=全部)。
    import_keyword: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 取り込んだ予定に最初に入れる担当者(受付設定の担当者リストの1件)。空=入れない。
    default_staff: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # naive-UTC
    last_error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # naive-UTC
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CalendarEventTombstone(Base):
    """来社予定を mokuture で消したときの後始末を覚えておく行。

    - kind="delete" … 書き出し(to_google)中に消した予定。Google 側のイベントを消すまで残し、
      消せたら行を消す(再デプロイ・通信断で取りこぼさないよう、定期同期が拾い直す)。
    - kind="ignore" … 取り込み(from_google)した予定を mokuture で消した。次の取り込みで
      同じイベントを作り直さないための印。予定の日時を過ぎたら掃除する。
    """

    __tablename__ = "calendar_event_tombstones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # delete | ignore
    calendar_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    event_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # JST 壁時計(来社予定と同じ)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
