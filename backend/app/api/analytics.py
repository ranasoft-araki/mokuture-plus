"""分析ログ（実証実験・製品改善）の受信と参照。

- 受信（POST）は **デバイストークン**（`X-Kiosk-Token`）認証。テナント/拠点/端末は
  トークンから確定させ、本文の申告値は使わない。
- 参照（GET）は **運営(operator) JWT のみ**。テナント管理画面には出さない
  （実証実験・製品改善は自社側の分析のため / ANALYTICS.md §13）。
- 個人情報は列そのものが無い。詳細は `ANALYTICS.md`。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.kiosk import get_kiosk_device
from app.database import get_db
from app.middleware.tenant import require_operator
from app.models.analytics import DeviceEvent, DeviceMetric, ReceptionEvent, ReceptionSession
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.user import User
from app.services import analytics as svc
from app.services import analytics_vocab as V
from app.services.timeutil import iso_z

router = APIRouter(prefix="/analytics", tags=["analytics"])

# 参照系(運営)は IP 単位で十分。
_limiter = Limiter(key_func=get_remote_address)


def _device_key(request: Request) -> str:
    """投入系のレート制限キー。**IPではなく端末ごと**に効かせる。

    同じ拠点の複数台が1つのグローバルIPを共有しても互いを枯渇させない。
    トークンそのものを保存しないようハッシュにする（未提示なら IP にフォールバック）。
    """
    token = request.headers.get("X-Kiosk-Token")
    if not token:
        return get_remote_address(request)
    return "dev:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


# 端末1台の投入は 1分あたり最大 12 リクエスト程度（15秒間隔 × 3種類）。
# 再送のまとめ送りを見込んでも十分な余裕をとる。
_ingest_limiter = Limiter(key_func=_device_key)

_JST = timezone(timedelta(hours=9))


# ── 受信 ──────────────────────────────────────────────────────────────────────

class EventBatch(BaseModel):
    """バッチ本体。件数上限を型で縛る（本文サイズは下のガードで見る）。

    要素は `dict` のまま受け取り、1件ずつ検証する＝1件の不正で全体を落とさないため。
    """

    events: list[dict] = Field(default_factory=list, max_length=svc.MAX_BATCH)


def _guard_body_size(request: Request) -> None:
    raw = request.headers.get("content-length")
    if raw and raw.isdigit() and int(raw) > svc.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")


@router.post("/events")
@_ingest_limiter.limit("120/minute")
async def post_events(
    request: Request,
    body: EventBatch,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """行動イベントのバッチ投入。端末(エージェント)からのみ呼ばれる。"""
    _guard_body_size(request)
    tenant, device = ctx
    return await svc.ingest_reception_events(db, tenant, device, body.events)


@router.post("/device-events")
@_ingest_limiter.limit("120/minute")
async def post_device_events(
    request: Request,
    body: EventBatch,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    _guard_body_size(request)
    tenant, device = ctx
    return await svc.ingest_device_events(db, tenant, device, body.events)


@router.post("/device-metrics")
@_ingest_limiter.limit("120/minute")
async def post_device_metrics(
    request: Request,
    body: EventBatch,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    _guard_body_size(request)
    tenant, device = ctx
    return await svc.ingest_device_metrics(db, tenant, device, body.events)


# ── 参照（運営のみ） ─────────────────────────────────────────────────────────

def _jst_day_range(date_from: str | None, date_to: str | None) -> tuple[datetime | None, datetime | None]:
    """"YYYY-MM-DD"(JST) を naive-UTC の [開始, 終了) へ変換する。"""

    def parse(s: str) -> date:
        return date.fromisoformat(s)

    start = end = None
    if date_from:
        d = parse(date_from)
        start = datetime(d.year, d.month, d.day, tzinfo=_JST).astimezone(timezone.utc).replace(tzinfo=None)
    if date_to:
        d = parse(date_to) + timedelta(days=1)
        end = datetime(d.year, d.month, d.day, tzinfo=_JST).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def _apply_session_filters(stmt, tenant_id, device_id, outcome, entry_method, ui_version, start, end):
    if tenant_id:
        stmt = stmt.where(ReceptionSession.tenant_id == tenant_id)
    if device_id:
        stmt = stmt.where(ReceptionSession.device_id == device_id)
    if outcome:
        if outcome == "open":
            stmt = stmt.where(ReceptionSession.outcome.is_(None))
        else:
            stmt = stmt.where(ReceptionSession.outcome == outcome)
    if entry_method:
        stmt = stmt.where(ReceptionSession.entry_method == entry_method)
    if ui_version:
        stmt = stmt.where(ReceptionSession.ui_version == ui_version)
    if start is not None:
        stmt = stmt.where(ReceptionSession.started_at >= start)
    if end is not None:
        stmt = stmt.where(ReceptionSession.started_at < end)
    return stmt


class SessionFilters:
    """一覧・サマリ・エクスポートで共通のクエリパラメータ。"""

    def __init__(
        self,
        tenant_id: Optional[str] = Query(None),
        device_id: Optional[str] = Query(None),
        outcome: Optional[str] = Query(None, description="completed/cancelled/abandoned/timeout/app_error/device_restarted/open"),
        entry_method: Optional[str] = Query(None),
        ui_version: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None, description="YYYY-MM-DD (JST)"),
        date_to: Optional[str] = Query(None, description="YYYY-MM-DD (JST)"),
    ):
        try:
            self.start, self.end = _jst_day_range(date_from, date_to)
        except ValueError:
            raise HTTPException(status_code=422, detail="date_from / date_to は YYYY-MM-DD で指定してください")
        self.tenant_id = tenant_id
        self.device_id = device_id
        self.outcome = outcome
        self.entry_method = entry_method
        self.ui_version = ui_version

    def apply(self, stmt):
        return _apply_session_filters(
            stmt,
            self.tenant_id,
            self.device_id,
            self.outcome,
            self.entry_method,
            self.ui_version,
            self.start,
            self.end,
        )


def _session_out(sess: ReceptionSession, tenant_name: str | None = None, device_name: str | None = None) -> dict:
    return {
        "id": sess.id,
        "tenant_id": sess.tenant_id,
        "tenant_name": tenant_name,
        "site_id": sess.site_id,
        "device_id": sess.device_id,
        "device_name": device_name,
        "started_at": iso_z(sess.started_at),
        "ended_at": iso_z(sess.ended_at),
        "duration_ms": sess.duration_ms,
        "outcome": sess.outcome,
        "entry_method": sess.entry_method,
        "app_version": sess.app_version,
        "ui_version": sess.ui_version,
        "flow_version": sess.flow_version,
        "client_tz_offset_min": sess.client_tz_offset_min,
        "first_screen_id": sess.first_screen_id,
        "last_screen_id": sess.last_screen_id,
        "event_count": sess.event_count,
        "error_count": sess.error_count,
        "screen_count": sess.screen_count,
        "back_count": sess.back_count,
        "notified": sess.notified,
        "staff_response": sess.staff_response,
        "staff_response_ms": sess.staff_response_ms,
        "answer_clarity": sess.answer_clarity,
        "answer_confidence": sess.answer_confidence,
        "answer_assistance": sess.answer_assistance,
    }


def _event_out(ev: ReceptionEvent) -> dict:
    return {
        "event_id": ev.event_id,
        "session_id": ev.session_id,
        "sequence_no": ev.sequence_no,
        "client_occurred_at": iso_z(ev.client_occurred_at),
        "client_tz_offset_min": ev.client_tz_offset_min,
        "server_received_at": iso_z(ev.server_received_at),
        "event_source": ev.event_source,
        "site_id": ev.site_id,
        "device_id": ev.device_id,
        "app_version": ev.app_version,
        "ui_version": ev.ui_version,
        "flow_version": ev.flow_version,
        "event_name": ev.event_name,
        "screen_id": ev.screen_id,
        "previous_screen_id": ev.previous_screen_id,
        "element_id": ev.element_id,
        "field_id": ev.field_id,
        "input_method": ev.input_method,
        "result": ev.result,
        "error_code": ev.error_code,
        "screen_dwell_ms": ev.screen_dwell_ms,
        "duration_ms": ev.duration_ms,
        "retry_count": ev.retry_count,
        "recovered": ev.recovered,
        "question_id": ev.question_id,
        "answer_code": ev.answer_code,
    }


async def _name_maps(db: AsyncSession, sessions: list[ReceptionSession]) -> tuple[dict, dict]:
    tenant_ids = {s.tenant_id for s in sessions}
    device_ids = {s.device_id for s in sessions if s.device_id}
    tenants = {}
    devices = {}
    if tenant_ids:
        tenants = dict((await db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(tenant_ids)))).all())
    if device_ids:
        devices = dict((await db.execute(select(Device.id, Device.name).where(Device.id.in_(device_ids)))).all())
    return tenants, devices


@router.get("/sessions")
@_limiter.limit("60/minute")
async def list_sessions(
    request: Request,
    filters: SessionFilters = Depends(),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """匿名セッション一覧（新しい順）。"""
    total = (
        await db.execute(filters.apply(select(func.count()).select_from(ReceptionSession)))
    ).scalar_one()
    stmt = filters.apply(select(ReceptionSession)).order_by(ReceptionSession.started_at.desc())
    sessions = list((await db.execute(stmt.offset(offset).limit(limit))).scalars().all())
    tenants, devices = await _name_maps(db, sessions)
    return {
        "total": total,
        "items": [_session_out(s, tenants.get(s.tenant_id), devices.get(s.device_id or "")) for s in sessions],
    }


@router.get("/sessions/{session_id}")
@_limiter.limit("60/minute")
async def get_session(
    request: Request,
    session_id: str,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """1セッションの時系列イベント。

    並びは **受信順ではなく** `client_occurred_at` → `sequence_no`。
    バックエンド発のイベント（通知の成否）は `sequence_no=0` で時刻順に混ざる。
    """
    sess = (
        await db.execute(select(ReceptionSession).where(ReceptionSession.id == session_id))
    ).scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = list(
        (
            await db.execute(
                select(ReceptionEvent)
                .where(ReceptionEvent.session_id == session_id)
                .order_by(ReceptionEvent.client_occurred_at, ReceptionEvent.sequence_no)
            )
        )
        .scalars()
        .all()
    )
    tenants, devices = await _name_maps(db, [sess])
    return {
        "session": _session_out(sess, tenants.get(sess.tenant_id), devices.get(sess.device_id or "")),
        "events": [_event_out(e) for e in events],
    }


@router.get("/summary")
@_limiter.limit("60/minute")
async def get_summary(
    request: Request,
    filters: SessionFilters = Depends(),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """主要指標（ANALYTICS.md §14）。"""
    rows = list(
        (
            await db.execute(
                filters.apply(
                    select(
                        ReceptionSession.outcome,
                        ReceptionSession.duration_ms,
                        ReceptionSession.error_count,
                        ReceptionSession.entry_method,
                        ReceptionSession.answer_assistance,
                        ReceptionSession.answer_clarity,
                        ReceptionSession.answer_confidence,
                        ReceptionSession.notified,
                        ReceptionSession.staff_response,
                        ReceptionSession.staff_response_ms,
                    )
                )
            )
        ).all()
    )
    started = len(rows)
    completed = sum(1 for r in rows if r.outcome == "completed")
    abandoned = sum(1 for r in rows if r.outcome in V.ABANDON_OUTCOMES)
    errored = [r for r in rows if (r.error_count or 0) > 0]
    errored_completed = sum(1 for r in errored if r.outcome == "completed")
    durations = [r.duration_ms for r in rows if r.outcome == "completed" and r.duration_ms is not None]
    responded = [r.staff_response_ms for r in rows if r.staff_response_ms is not None]

    assist_answers = [r.answer_assistance for r in rows if r.answer_assistance]
    assist_none = sum(1 for a in assist_answers if a == "none")

    by_entry: dict[str, dict] = {}
    for r in rows:
        key = r.entry_method or "unknown"
        b = by_entry.setdefault(key, {"started": 0, "completed": 0, "durations": []})
        b["started"] += 1
        if r.outcome == "completed":
            b["completed"] += 1
            if r.duration_ms is not None:
                b["durations"].append(r.duration_ms)

    # アンケートの回答分布（質問ごと）
    survey: dict[str, dict] = {}
    for qid, attr in (("clarity", "answer_clarity"), ("confidence", "answer_confidence"), ("assistance", "answer_assistance")):
        counts: dict[str, int] = {}
        answered = 0
        for r in rows:
            val = getattr(r, attr)
            if val:
                answered += 1
                counts[val] = counts.get(val, 0) + 1
        survey[qid] = {
            "answered": answered,
            "response_rate": svc.ratio(answered, started),
            "counts": counts,
        }

    return {
        "sessions_started": started,
        "completed": completed,
        "completion_rate": svc.ratio(completed, started),
        "abandon_rate": svc.ratio(abandoned, started),
        "error_rate": svc.ratio(len(errored), started),
        "error_recovery_rate": svc.ratio(errored_completed, len(errored)),
        "duration_ms": {
            "count": len(durations),
            "avg": round(sum(durations) / len(durations)) if durations else None,
            "median": svc.percentile(durations, 0.5),
            "p90": svc.percentile(durations, 0.9),
        },
        "staff_response_ms": {
            "count": len(responded),
            "avg": round(sum(responded) / len(responded)) if responded else None,
            "median": svc.percentile(responded, 0.5),
            "p90": svc.percentile(responded, 0.9),
        },
        # 自己申告による非介助率。回答率・回答者数を必ず併記する（ANALYTICS.md §14）
        "self_reported_unassisted": {
            "rate": svc.ratio(assist_none, len(assist_answers)),
            "answered": len(assist_answers),
            "response_rate": svc.ratio(len(assist_answers), started),
            "unassisted": assist_none,
        },
        "by_entry_method": {
            k: {
                "started": v["started"],
                "completed": v["completed"],
                "completion_rate": svc.ratio(v["completed"], v["started"]),
                "duration_median": svc.percentile(v["durations"], 0.5),
                "duration_p90": svc.percentile(v["durations"], 0.9),
            }
            for k, v in sorted(by_entry.items())
        },
        "survey": survey,
    }


@router.get("/uptime")
@_limiter.limit("60/minute")
async def get_uptime(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """端末稼働率（ANALYTICS.md §10）。

    分母は **ラズパイの電源が入っていた時間**＝メトリクス行が存在する時間。
    電源OFF中は行が無いので自動的に分母から外れる（夜間・休日・計画停止の除外）。
    """
    try:
        start, end = _jst_day_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from / date_to は YYYY-MM-DD で指定してください")

    stmt = select(
        DeviceMetric.device_id,
        DeviceMetric.tenant_id,
        func.count().label("samples"),
        func.sum(DeviceMetric.interval_sec).label("total_sec"),
        func.sum(
            case((DeviceMetric.app_healthy.is_(True), DeviceMetric.interval_sec), else_=0)
        ).label("healthy_sec"),
        func.sum(
            case((DeviceMetric.online.is_(False), DeviceMetric.interval_sec), else_=0)
        ).label("offline_sec"),
        func.avg(DeviceMetric.cpu_percent).label("cpu_avg"),
        func.max(DeviceMetric.cpu_temp_c).label("temp_max"),
        func.min(DeviceMetric.disk_free_mb).label("disk_free_min"),
    ).group_by(DeviceMetric.device_id, DeviceMetric.tenant_id)
    if tenant_id:
        stmt = stmt.where(DeviceMetric.tenant_id == tenant_id)
    if device_id:
        stmt = stmt.where(DeviceMetric.device_id == device_id)
    if start is not None:
        stmt = stmt.where(DeviceMetric.measured_at >= start)
    if end is not None:
        stmt = stmt.where(DeviceMetric.measured_at < end)
    rows = (await db.execute(stmt)).all()

    restart_stmt = (
        select(DeviceEvent.device_id, func.count().label("cnt"))
        .where(DeviceEvent.event_name.in_(list(V.DEVICE_RESTART_EVENTS)))
        .group_by(DeviceEvent.device_id)
    )
    if start is not None:
        restart_stmt = restart_stmt.where(DeviceEvent.occurred_at >= start)
    if end is not None:
        restart_stmt = restart_stmt.where(DeviceEvent.occurred_at < end)
    restarts = dict((await db.execute(restart_stmt)).all())

    ids = [r.device_id for r in rows]
    names = dict((await db.execute(select(Device.id, Device.name).where(Device.id.in_(ids)))).all()) if ids else {}
    tenants = (
        dict(
            (
                await db.execute(
                    select(Tenant.id, Tenant.name).where(Tenant.id.in_({r.tenant_id for r in rows}))
                )
            ).all()
        )
        if rows
        else {}
    )

    return {
        "items": [
            {
                "device_id": r.device_id,
                "device_name": names.get(r.device_id),
                "tenant_id": r.tenant_id,
                "tenant_name": tenants.get(r.tenant_id),
                "samples": r.samples,
                "powered_sec": int(r.total_sec or 0),
                "healthy_sec": int(r.healthy_sec or 0),
                "offline_sec": int(r.offline_sec or 0),
                "uptime_rate": svc.ratio(int(r.healthy_sec or 0), int(r.total_sec or 0)),
                "restart_count": restarts.get(r.device_id, 0),
                "cpu_percent_avg": round(r.cpu_avg, 1) if r.cpu_avg is not None else None,
                "cpu_temp_max": round(r.temp_max, 1) if r.temp_max is not None else None,
                "disk_free_mb_min": r.disk_free_min,
            }
            for r in rows
        ]
    }


_SESSION_CSV_COLUMNS = [
    "id", "tenant_id", "tenant_name", "site_id", "device_id", "device_name",
    "started_at", "ended_at", "duration_ms", "outcome", "entry_method",
    "app_version", "ui_version", "flow_version", "client_tz_offset_min",
    "first_screen_id", "last_screen_id", "event_count", "error_count",
    "screen_count", "back_count", "notified", "staff_response", "staff_response_ms",
    "answer_clarity", "answer_confidence", "answer_assistance",
]

_EVENT_CSV_COLUMNS = [
    "session_id", "sequence_no", "client_occurred_at", "server_received_at",
    "event_source", "site_id", "device_id", "app_version", "ui_version", "flow_version",
    "event_name", "screen_id", "previous_screen_id", "element_id", "field_id",
    "input_method", "result", "error_code", "screen_dwell_ms", "duration_ms",
    "retry_count", "recovered", "question_id", "answer_code", "event_id",
    "client_tz_offset_min",
]


@router.get("/export")
@_limiter.limit("20/minute")
async def export_analytics(
    request: Request,
    filters: SessionFilters = Depends(),
    kind: str = Query("sessions", pattern="^(sessions|events)$"),
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(5000, ge=1, le=50000),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """CSV / JSON 出力。フィルタは一覧と同じ（対象セッションのイベントも出せる）。"""
    stmt = filters.apply(select(ReceptionSession)).order_by(ReceptionSession.started_at.desc()).limit(limit)
    sessions = list((await db.execute(stmt)).scalars().all())
    tenants, devices = await _name_maps(db, sessions)

    if kind == "sessions":
        rows: list[dict[str, Any]] = [
            _session_out(s, tenants.get(s.tenant_id), devices.get(s.device_id or "")) for s in sessions
        ]
        columns = _SESSION_CSV_COLUMNS
        filename = "reception_sessions"
    else:
        ids = [s.id for s in sessions]
        events: list[ReceptionEvent] = []
        # IN 句が巨大になりすぎないよう分割して取得する
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            events.extend(
                (
                    await db.execute(
                        select(ReceptionEvent)
                        .where(ReceptionEvent.session_id.in_(chunk))
                        .order_by(
                            ReceptionEvent.session_id,
                            ReceptionEvent.client_occurred_at,
                            ReceptionEvent.sequence_no,
                        )
                    )
                )
                .scalars()
                .all()
            )
        rows = [_event_out(e) for e in events]
        columns = _EVENT_CSV_COLUMNS
        filename = "reception_events"

    if fmt == "json":
        return Response(
            content=json.dumps(rows, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    # Excel が UTF-8 と判定できるよう BOM を付ける（既存の受付ログ CSV と同じ扱い）
    body = "﻿" + buf.getvalue()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
