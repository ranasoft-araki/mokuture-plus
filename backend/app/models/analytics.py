"""実証実験・製品改善分析のためのログ用テーブル（匿名）。

設計の全体像は リポジトリ直下の `ANALYTICS.md` を参照。

**個人情報は一切保存しない。** 氏名・会社名・担当者・入力文字列・画像・音声・IPアドレス等は
列そのものが存在しない。自由入力の `metadata` 欄も意図的に作っていない
（保存できる項目はこのファイルのカラム＝ホワイトリストだけ）。

`reception_logs`（＝個人情報を含む受付ログ）とは **結び付けない**。
`reception_log_id` に相当する列はここには無く、通知イベントの紐付けは
`app/services/analytics_link.py` のプロセス内 TTL マップだけで行う（永続化しない）。
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ReceptionSession(Base):
    """受付1回ぶんの匿名セッション。`id` は端末が発行する UUIDv4。

    「誰が」ではなく「この1回の操作」を時系列でつなぐためだけの識別子で、
    受付終了後に再利用しない・訪問者を跨いで再利用しない。
    """

    __tablename__ = "reception_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 拠点ID。現状はテナントIDと同値（1顧客＝1拠点運用）。将来 sites テーブルを足しても列は同じ。
    site_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 端末ID。端末が削除されてもログは残したいので FK にはしない。
    device_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # completed | cancelled | abandoned | timeout | app_error | device_restarted | NULL(進行中)
    outcome: Mapped[Optional[str]] = mapped_column(String(24), nullable=True, index=True)
    # touch | qr | card | voice | smartphone
    entry_method: Mapped[Optional[str]] = mapped_column(String(24), nullable=True, index=True)

    app_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    ui_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    flow_version: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    # 端末ローカル時刻を復元するためのオフセット(分)。時間帯・曜日別の集計に使う。
    client_tz_offset_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    first_screen_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    last_screen_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    screen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    back_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 通知が発火した受付かどうか（受付/配達呼び出し）。通知成功率の分母の補助。
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # スタッフ応答（accepted/phone/declined）と、通知送信からの経過ミリ秒。担当者名は保存しない。
    staff_response: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    staff_response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # アンケート回答（未回答は NULL＝unknown 扱い。行動ログから推測しない）
    answer_clarity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    answer_confidence: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    answer_assistance: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_rsess_tenant_started", "tenant_id", "started_at"),
        Index("ix_rsess_device_started", "device_id", "started_at"),
    )


class ReceptionEvent(Base):
    """行動イベント1件。`event_id` を主キーにして再送の二重登録を防ぐ。

    ここに無い項目は保存できない＝保存可能項目のホワイトリストそのもの。
    """

    __tablename__ = "reception_events"

    # クライアント生成 UUIDv4。再送が来ても主キー衝突で弾ける（＝冪等）。
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # セッション内の連番(1始まり)。サーバは受信順ではなくこれで並べ替える。
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    client_occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    client_tz_offset_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    server_received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # browser | backend | device_agent
    event_source: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    ui_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    flow_version: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)

    event_name: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    screen_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True, index=True)
    previous_screen_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    # 表示文字列ではなく固定ID（data-ev もしくは要素の id）。
    element_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 入力項目ID。値そのものは保存しない。
    field_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True, index=True)
    # touch | keyboard | qr | card | voice | smartphone | auto
    input_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # succeeded | failed | cancelled | timeout | skipped | accepted | phone | declined
    result: Mapped[Optional[str]] = mapped_column(String(24), nullable=True, index=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(48), nullable=True, index=True)

    screen_dwell_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recovered: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    question_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    answer_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_revent_session_seq", "session_id", "sequence_no"),
        Index("ix_revent_tenant_time", "tenant_id", "client_occurred_at"),
        Index("ix_revent_name_time", "event_name", "client_occurred_at"),
        Index("ix_revent_screen_name", "screen_id", "event_name"),
    )


class DeviceEvent(Base):
    """端末稼働イベント（起動・停止・再起動・オフライン・復旧など）。"""

    __tablename__ = "device_events"

    # クライアント(エージェント)生成 UUIDv4。再送の二重登録を防ぐ主キー。
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    event_name: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # 追加の分類コード（固定語彙のみ。自由文は入れない）
    detail_code: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    # offline が続いた秒数・ダウンタイムなど
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # log_dropped の件数など、数値1つで足りるもの
    count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    agent_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ui_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    uptime_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_devevent_device_time", "device_id", "occurred_at"),
        Index("ix_devevent_tenant_time", "tenant_id", "occurred_at"),
    )


class DeviceMetric(Base):
    """端末の定期メトリクス。ハートビート(既定60秒)ごとに1行。

    稼働率の分母は「この行が存在する時間」＝ラズパイの電源が入っていた時間。
    通信断の間もエージェントがローカルスプールへ書き、復旧後に送るので、
    電源ONだがネット断の時間は分母に入り `online=false` として分子から外れる。
    電源OFFの間は行そのものが無いので分母からも自然に外れる。
    """

    __tablename__ = "device_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    measured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # このサンプルが代表する時間(秒)。ハートビート間隔。
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")

    # 稼働率の判定に使う3点
    online: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    app_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    browser_age_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    screen_id: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)

    # 可能であれば取得（非 Linux・取得不可なら NULL）
    cpu_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cpu_temp_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mem_used_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mem_total_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    disk_free_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    disk_total_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uptime_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    touch_connected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    mic_connected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    camera_connected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    agent_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ui_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_devmetric_device_time", "device_id", "measured_at"),
        Index("ix_devmetric_tenant_time", "tenant_id", "measured_at"),
    )
