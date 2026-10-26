"""分析ログ受信APIの入力スキーマ。

**`extra="forbid"`** が要。ここに書いていないフィールドを含むイベントは
その1件だけ reject される＝「自由に任意の値を保存できる metadata」を作らない、
という ANALYTICS.md の方針をスキーマ層で強制する。

文字列はすべて `max_length` を持つ（長大な本文が紛れ込むのを防ぐ）。
語彙（event_name / screen_id / error_code など）の検証は
`app/services/analytics_vocab.py` を使って `services/analytics.py` 側で行う
（1件だけ reject して残りは通すため、Pydantic では型と長さだけを見る）。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReceptionEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(max_length=36)
    session_id: str = Field(max_length=36)
    sequence_no: int = Field(ge=1, le=100_000)
    client_occurred_at: datetime
    client_tz_offset_min: int | None = Field(default=None, ge=-1440, le=1440)

    event_source: str = Field(default="browser", max_length=16)
    app_version: str | None = Field(default=None, max_length=32)
    ui_version: str | None = Field(default=None, max_length=32)
    flow_version: str | None = Field(default=None, max_length=48)

    event_name: str = Field(max_length=48)
    screen_id: str | None = Field(default=None, max_length=48)
    previous_screen_id: str | None = Field(default=None, max_length=48)
    element_id: str | None = Field(default=None, max_length=64)
    field_id: str | None = Field(default=None, max_length=48)
    input_method: str | None = Field(default=None, max_length=16)
    result: str | None = Field(default=None, max_length=24)
    error_code: str | None = Field(default=None, max_length=48)

    screen_dwell_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    retry_count: int | None = Field(default=None, ge=0, le=10_000)
    recovered: bool | None = None

    question_id: str | None = Field(default=None, max_length=32)
    answer_code: str | None = Field(default=None, max_length=32)


class DeviceEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=36)
    occurred_at: datetime
    sequence_no: int | None = Field(default=None, ge=1, le=100_000_000)
    event_name: str = Field(max_length=48)
    detail_code: str | None = Field(default=None, max_length=48)
    duration_ms: int | None = Field(default=None, ge=0, le=2_147_483_647)
    count: int | None = Field(default=None, ge=0, le=10_000_000)
    agent_version: str | None = Field(default=None, max_length=32)
    ui_version: str | None = Field(default=None, max_length=32)
    os_version: str | None = Field(default=None, max_length=64)
    uptime_sec: int | None = Field(default=None, ge=0, le=2_147_483_647)


class DeviceMetricIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=36)
    measured_at: datetime
    interval_sec: int = Field(default=60, ge=1, le=3600)

    online: bool | None = None
    app_healthy: bool | None = None
    browser_age_sec: float | None = Field(default=None, ge=0, le=1_000_000)
    screen_id: str | None = Field(default=None, max_length=48)

    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    cpu_temp_c: float | None = Field(default=None, ge=-50, le=200)
    mem_used_mb: int | None = Field(default=None, ge=0, le=1_048_576)
    mem_total_mb: int | None = Field(default=None, ge=0, le=1_048_576)
    disk_free_mb: int | None = Field(default=None, ge=0, le=100_000_000)
    disk_total_mb: int | None = Field(default=None, ge=0, le=100_000_000)
    uptime_sec: int | None = Field(default=None, ge=0, le=2_147_483_647)
    touch_connected: bool | None = None
    mic_connected: bool | None = None
    camera_connected: bool | None = None

    agent_version: str | None = Field(default=None, max_length=32)
    ui_version: str | None = Field(default=None, max_length=32)
    os_version: str | None = Field(default=None, max_length=64)


class IngestResult(BaseModel):
    accepted: list[str] = []
    duplicate: list[str] = []
    rejected: list[dict] = []
