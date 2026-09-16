"""分析ログ受信APIのテスト（ANALYTICS.md §15 のテスト項目に対応）。

ここで確かめているのは主に:
  1. 受付開始→完了の操作が順番どおり復元できる
  2. 画面ごとの滞在時間が記録される
  3. 戻る操作を含む経路が記録される
  4. 入力エラーと修正完了が同じセッションで結び付く
  5. 入力値がログへ保存されない（未知フィールドは拒否される）
  9. 再送しても二重登録されない
 15. 匿名セッションと個人情報が結び付かない
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select

from app.database import AsyncSessionLocal
from app.models.analytics import ReceptionEvent, ReceptionSession

BASE = "/api/analytics"


def _event(session_id: str, seq: int, name: str, at: datetime, **extra) -> dict:
    ev = {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "sequence_no": seq,
        "client_occurred_at": at.isoformat().replace("+00:00", "Z"),
        "client_tz_offset_min": 540,
        "event_source": "browser",
        "app_version": "1.0.3",
        "ui_version": "default",
        "flow_version": "visitor-v1",
        "event_name": name,
    }
    ev.update(extra)
    return ev


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def _post(client, headers, events):
    return await client.post(f"{BASE}/events", json={"events": events}, headers=headers)


# ── 1. 操作が順番どおり復元できる ────────────────────────────────────────────

async def test_timeline_is_reconstructed_in_client_order(client, kiosk_headers, operator_headers):
    """受信順がバラバラでも、セッション内の順序は sequence_no / 端末時刻で復元される。"""
    sid = str(uuid.uuid4())
    t0 = _now()
    flow = [
        (1, "session_started", {"input_method": "touch"}),
        (2, "screen_viewed", {"screen_id": "welcome"}),
        (3, "screen_exited", {"screen_id": "welcome", "screen_dwell_ms": 4200}),
        (4, "screen_viewed", {"screen_id": "top", "previous_screen_id": "welcome"}),
        (5, "action_selected", {"screen_id": "top", "element_id": "top-reception"}),
        (6, "screen_viewed", {"screen_id": "reception", "previous_screen_id": "top"}),
        (7, "notification_requested", {"screen_id": "reception"}),
        (8, "screen_viewed", {"screen_id": "calling", "previous_screen_id": "reception"}),
        (9, "staff_responded", {"screen_id": "calling", "result": "accepted", "duration_ms": 8200}),
        (10, "session_completed", {"screen_id": "result_ok"}),
    ]
    events = [_event(sid, seq, name, t0 + timedelta(seconds=seq), **extra) for seq, name, extra in flow]

    # わざと逆順・2バッチに分けて送る（受信順を操作順として扱っていないことの確認）
    r1 = await _post(client, kiosk_headers, list(reversed(events[5:])))
    r2 = await _post(client, kiosk_headers, list(reversed(events[:5])))
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r1.json()["accepted"]) == 5 and len(r2.json()["accepted"]) == 5

    detail = await client.get(f"{BASE}/sessions/{sid}", headers=operator_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert [e["event_name"] for e in body["events"]] == [name for _, name, _ in flow]
    assert [e["sequence_no"] for e in body["events"]] == list(range(1, 11))

    sess = body["session"]
    assert sess["outcome"] == "completed"
    assert sess["entry_method"] == "touch"
    assert sess["staff_response"] == "accepted"
    assert sess["staff_response_ms"] == 8200
    assert sess["notified"] is True
    assert sess["duration_ms"] == 9000  # seq1 → seq10 の 9 秒


# ── 2. 画面ごとの滞在時間 ────────────────────────────────────────────────────

async def test_screen_dwell_is_stored(client, kiosk_headers, operator_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    await _post(client, kiosk_headers, [
        _event(sid, 1, "session_started", t0, input_method="touch"),
        _event(sid, 2, "screen_viewed", t0 + timedelta(seconds=1), screen_id="reception"),
        _event(sid, 3, "screen_exited", t0 + timedelta(seconds=13), screen_id="reception", screen_dwell_ms=12400),
    ])
    detail = (await client.get(f"{BASE}/sessions/{sid}", headers=operator_headers)).json()
    exited = [e for e in detail["events"] if e["event_name"] == "screen_exited"]
    assert exited[0]["screen_dwell_ms"] == 12400
    assert exited[0]["screen_id"] == "reception"


# ── 3. 戻る操作を含む経路 ────────────────────────────────────────────────────

async def test_back_navigation_is_counted_and_ordered(client, kiosk_headers, operator_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    await _post(client, kiosk_headers, [
        _event(sid, 1, "session_started", t0, input_method="touch"),
        _event(sid, 2, "screen_viewed", t0 + timedelta(seconds=1), screen_id="top"),
        _event(sid, 3, "screen_viewed", t0 + timedelta(seconds=5), screen_id="reception", previous_screen_id="top"),
        _event(sid, 4, "back_selected", t0 + timedelta(seconds=9), screen_id="reception", element_id="rec-back"),
        _event(sid, 5, "screen_viewed", t0 + timedelta(seconds=10), screen_id="top", previous_screen_id="reception"),
        _event(sid, 6, "back_selected", t0 + timedelta(seconds=14), screen_id="top", element_id="top-home"),
    ])
    body = (await client.get(f"{BASE}/sessions/{sid}", headers=operator_headers)).json()
    assert body["session"]["back_count"] == 2
    assert body["session"]["screen_count"] == 3
    path = [e["screen_id"] for e in body["events"] if e["event_name"] == "screen_viewed"]
    assert path == ["top", "reception", "top"]


# ── 4. 入力エラーと修正完了が同じセッションで結び付く ──────────────────────

async def test_validation_error_and_recovery_link_in_one_session(client, kiosk_headers, operator_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    await _post(client, kiosk_headers, [
        _event(sid, 1, "session_started", t0, input_method="touch"),
        _event(sid, 2, "input_started", t0 + timedelta(seconds=2), screen_id="reception", field_id="visitor_name", input_method="keyboard"),
        _event(sid, 3, "validation_error", t0 + timedelta(seconds=6), screen_id="reception",
               field_id="visitor_name", error_code="required", result="failed", retry_count=1),
        _event(sid, 4, "error_recovered", t0 + timedelta(seconds=11), screen_id="reception",
               field_id="visitor_name", error_code="required", recovered=True, retry_count=1, duration_ms=5000),
        _event(sid, 5, "session_completed", t0 + timedelta(seconds=20), screen_id="result_ok"),
    ])
    body = (await client.get(f"{BASE}/sessions/{sid}", headers=operator_headers)).json()
    by_name = {e["event_name"]: e for e in body["events"]}
    assert by_name["validation_error"]["field_id"] == by_name["error_recovered"]["field_id"] == "visitor_name"
    assert by_name["error_recovered"]["recovered"] is True
    assert by_name["error_recovered"]["duration_ms"] == 5000
    # エラー件数は validation_error だけ（error_recovered は「回復」なので数えない）
    assert body["session"]["error_count"] == 1
    assert body["session"]["outcome"] == "completed"


# ── 5. 入力値がログへ保存されない ────────────────────────────────────────────

async def test_unknown_fields_are_rejected(client, kiosk_headers):
    """自由入力の欄が無いこと。氏名などを混ぜた1件だけが reject され、残りは通る。"""
    sid = str(uuid.uuid4())
    t0 = _now()
    good = _event(sid, 1, "session_started", t0, input_method="touch")
    bad = _event(sid, 2, "validation_error", t0, screen_id="reception", field_id="visitor_name", error_code="required")
    bad["visitor_name"] = "山田太郎"       # 個人情報を紛れ込ませる試み
    bad2 = _event(sid, 3, "action_selected", t0, screen_id="top")
    bad2["metadata"] = {"note": "自由入力"}  # metadata 欄は存在しない

    r = await _post(client, kiosk_headers, [good, bad, bad2])
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == [good["event_id"]]
    assert {x["id"] for x in body["rejected"]} == {bad["event_id"], bad2["event_id"]}
    assert all(x["reason"] == "schema" for x in body["rejected"])
    # reject の理由コードに値そのものが載っていないこと
    assert "山田" not in r.text


async def test_event_table_has_no_personal_columns():
    """テーブル定義そのものに個人情報の置き場が無いことを固定する。"""
    forbidden = {
        "visitor_name", "company", "staff", "department", "purpose", "email", "phone",
        "ip_address", "user_agent", "metadata", "payload", "note", "text", "message",
        "reception_log_id", "visitor_id", "cookie",
    }
    for model in (ReceptionEvent, ReceptionSession):
        columns = {c.name for c in inspect(model).columns}
        assert not (columns & forbidden), f"{model.__tablename__} に個人情報の列がある: {columns & forbidden}"


async def test_element_id_must_be_an_identifier(client, kiosk_headers):
    """element_id に表示文字列(日本語ラベル)を入れられないこと。"""
    sid = str(uuid.uuid4())
    ev = _event(sid, 1, "action_selected", _now(), screen_id="top", element_id="ご訪問")
    r = await _post(client, kiosk_headers, [ev])
    assert r.json()["rejected"][0]["reason"] == "element_id_not_identifier"


async def test_unknown_vocabulary_is_rejected(client, kiosk_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    cases = [
        (_event(sid, 1, "mystery_event", t0), "unknown_event_name"),
        (_event(sid, 2, "screen_viewed", t0, screen_id="secret_screen"), "unknown_screen_id"),
        (_event(sid, 3, "validation_error", t0, field_id="credit_card"), "unknown_field_id"),
        (_event(sid, 4, "api_error", t0, error_code="boom"), "unknown_error_code"),
        (_event(sid, 5, "feedback_submitted", t0, question_id="clarity", answer_code="great"), "unknown_answer_code"),
        (_event(sid, 6, "screen_viewed", t0, screen_id="kiosk_settings"), "unknown_screen_id"),
    ]
    r = await _post(client, kiosk_headers, [c[0] for c in cases])
    reasons = {x["id"]: x["reason"] for x in r.json()["rejected"]}
    for ev, expected in cases:
        assert reasons[ev["event_id"]] == expected


# ── 9. 再送しても二重登録されない ────────────────────────────────────────────

async def test_resend_is_idempotent(client, kiosk_headers, operator_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    batch = [
        _event(sid, 1, "session_started", t0, input_method="touch"),
        _event(sid, 2, "screen_viewed", t0 + timedelta(seconds=1), screen_id="top"),
    ]
    first = await _post(client, kiosk_headers, batch)
    second = await _post(client, kiosk_headers, batch)       # そのまま再送
    third = await _post(client, kiosk_headers, batch + batch)  # 同一バッチ内の重複も

    assert len(first.json()["accepted"]) == 2
    assert second.json()["accepted"] == [] and len(second.json()["duplicate"]) == 2
    assert third.json()["accepted"] == []

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(ReceptionEvent).where(ReceptionEvent.session_id == sid))).scalars().all()
        assert len(rows) == 2
        sess = (await db.execute(select(ReceptionSession).where(ReceptionSession.id == sid))).scalar_one()
        assert sess.event_count == 2  # 集計も二重に増えない


# ── 15. 匿名セッションと個人情報が結び付かない ───────────────────────────────

async def test_reception_log_does_not_store_analytics_session_id(client, kiosk_headers, tenant):
    """受付送信で渡した匿名セッションIDが受付ログ(個人情報)に残らないこと。"""
    from app.models.reception import ReceptionLog

    sid = str(uuid.uuid4())
    r = await client.post(
        "/api/kiosk/reception",
        json={
            "visitor_name": "山田太郎",
            "company": "テスト商事",
            "staff": "磯野",
            "method": "form",
            "analytics_session_id": sid,
        },
        headers=kiosk_headers,
    )
    assert r.status_code == 201

    async with AsyncSessionLocal() as db:
        log = (await db.execute(select(ReceptionLog))).scalars().one()
        serialized = " ".join(str(v) for v in vars(log).values())
        assert sid not in serialized, "受付ログに匿名セッションIDが残っている（逆引きできてしまう）"

    # 対応表はプロセス内メモリにだけ存在し、永続化されていない
    from app.services import analytics_link

    ref = analytics_link.lookup(log.id)
    assert ref is not None and ref.session_id == sid
    analytics_link.clear()
    assert analytics_link.lookup(log.id) is None


# ── 認可 ─────────────────────────────────────────────────────────────────────

async def test_ingest_requires_device_token(client):
    r = await client.post(f"{BASE}/events", json={"events": []})
    assert r.status_code in (401, 422)


async def test_reading_requires_operator(client, kiosk_headers):
    r = await client.get(f"{BASE}/sessions")
    assert r.status_code in (401, 403)


async def test_batch_size_is_capped(client, kiosk_headers):
    sid = str(uuid.uuid4())
    t0 = _now()
    too_many = [_event(sid, i + 1, "action_selected", t0, screen_id="top") for i in range(201)]
    r = await _post(client, kiosk_headers, too_many)
    assert r.status_code == 422
