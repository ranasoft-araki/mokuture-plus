"""端末稼働ログ・未終了セッションの後始末・稼働率のテスト。

ANALYTICS.md §15 のうち:
 11. タイムアウト時にセッションが正しく終了する
 12. アプリ異常終了が端末ログから確認できる
 13. ハートビート停止から端末停止を検知できる
 14. 電源が入っていなかった時間が稼働率の分母から除外される
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.analytics import DeviceMetric, ReceptionSession
from app.services.analytics import sweep_stale_sessions

BASE = "/api/analytics"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def _start_session(client, headers, sid: str, at: datetime) -> None:
    await client.post(
        f"{BASE}/events",
        json={
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "session_id": sid,
                    "sequence_no": 1,
                    "client_occurred_at": _iso(at),
                    "event_source": "browser",
                    "event_name": "session_started",
                    "input_method": "touch",
                    "screen_id": "top",
                }
            ]
        },
        headers=headers,
    )


async def _device_event(client, headers, name: str, at: datetime, **extra) -> dict:
    payload = {"id": str(uuid.uuid4()), "occurred_at": _iso(at), "event_name": name}
    payload.update(extra)
    r = await client.post(f"{BASE}/device-events", json={"events": [payload]}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _metric(client, headers, at: datetime, *, online=True, healthy=True, interval=60, **extra) -> dict:
    payload = {
        "id": str(uuid.uuid4()),
        "measured_at": _iso(at),
        "interval_sec": interval,
        "online": online,
        "app_healthy": healthy,
    }
    payload.update(extra)
    r = await client.post(f"{BASE}/device-metrics", json={"events": [payload]}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ── 11. タイムアウト ─────────────────────────────────────────────────────────

async def test_browser_reported_timeout_sets_outcome(client, kiosk_headers, operator_headers):
    """ブラウザが無操作タイマーで申告した場合は outcome=timeout になる。"""
    sid = str(uuid.uuid4())
    t0 = _now()
    await _start_session(client, kiosk_headers, sid, t0)
    await client.post(
        f"{BASE}/events",
        json={
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "session_id": sid,
                    "sequence_no": 2,
                    "client_occurred_at": _iso(t0 + timedelta(seconds=60)),
                    "event_source": "browser",
                    "event_name": "session_timeout",
                    "screen_id": "reception",
                }
            ]
        },
        headers=kiosk_headers,
    )
    body = (await client.get(f"{BASE}/sessions/{sid}", headers=operator_headers)).json()
    assert body["session"]["outcome"] == "timeout"
    assert body["session"]["duration_ms"] == 60000


async def test_sweeper_closes_silent_session_as_abandoned(client, kiosk_headers, tenant):
    """終了イベントが来ないまま音沙汰が無いセッションは abandoned として畳まれる。

    （ブラウザ自身が申告しなかった＝タイムアウトと断定できないので abandoned にする）
    """
    sid = str(uuid.uuid4())
    t0 = _now() - timedelta(minutes=30)
    await _start_session(client, kiosk_headers, sid, t0)

    closed = await sweep_stale_sessions(now=_now())
    assert closed == 1
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(select(ReceptionSession).where(ReceptionSession.id == sid))).scalar_one()
        assert sess.outcome == "abandoned"
        assert sess.ended_at is not None


async def test_sweeper_keeps_recent_session_open(client, kiosk_headers):
    """まだ猶予内（idle_timeout + 120秒）のセッションは畳まない。"""
    sid = str(uuid.uuid4())
    await _start_session(client, kiosk_headers, sid, _now())
    assert await sweep_stale_sessions(now=_now()) == 0


# ── 12. アプリ異常終了・端末再起動 ───────────────────────────────────────────

async def test_app_crash_marks_session_as_app_error(client, kiosk_headers):
    sid = str(uuid.uuid4())
    t0 = _now() - timedelta(minutes=30)
    await _start_session(client, kiosk_headers, sid, t0)
    await _device_event(client, kiosk_headers, "app_crashed", t0 + timedelta(minutes=1),
                        detail_code="heartbeat_stale", duration_ms=60000)

    await sweep_stale_sessions(now=_now())
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(select(ReceptionSession).where(ReceptionSession.id == sid))).scalar_one()
        assert sess.outcome == "app_error"


async def test_device_restart_marks_session_as_device_restarted(client, kiosk_headers):
    sid = str(uuid.uuid4())
    t0 = _now() - timedelta(minutes=30)
    await _start_session(client, kiosk_headers, sid, t0)
    await _device_event(client, kiosk_headers, "device_restart", t0 + timedelta(minutes=2),
                        detail_code="unclean_shutdown", uptime_sec=12)

    await sweep_stale_sessions(now=_now())
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(select(ReceptionSession).where(ReceptionSession.id == sid))).scalar_one()
        assert sess.outcome == "device_restarted"


async def test_device_events_are_deduplicated(client, kiosk_headers):
    at = _now()
    payload = {"id": str(uuid.uuid4()), "occurred_at": _iso(at), "event_name": "device_boot"}
    first = await client.post(f"{BASE}/device-events", json={"events": [payload]}, headers=kiosk_headers)
    second = await client.post(f"{BASE}/device-events", json={"events": [payload]}, headers=kiosk_headers)
    assert len(first.json()["accepted"]) == 1
    assert second.json()["accepted"] == [] and len(second.json()["duplicate"]) == 1


async def test_unknown_device_event_is_rejected(client, kiosk_headers):
    payload = {"id": str(uuid.uuid4()), "occurred_at": _iso(_now()), "event_name": "exfiltrate"}
    r = await client.post(f"{BASE}/device-events", json={"events": [payload]}, headers=kiosk_headers)
    assert r.json()["rejected"][0]["reason"] == "unknown_event_name"


# ── 13 / 14. 稼働率 ──────────────────────────────────────────────────────────

async def test_uptime_uses_powered_time_as_denominator(client, kiosk_headers, operator_headers, device):
    """分母は「ハートビートが残っている時間」＝端末の電源が入っていた時間。

    - 電源OFF（＝行が無い）区間は分母にも分子にも入らない
    - 電源ONだが通信断（online=false, app_healthy=false）は分母に入り分子から外れる
    """
    base = _now().replace(second=0, microsecond=0) - timedelta(hours=2)
    # 10分ぶん(=10サンプル)正常稼働
    for i in range(10):
        await _metric(client, kiosk_headers, base + timedelta(minutes=i), online=True, healthy=True)
    # 5分ぶん通信断（電源は入っているのでスプールに溜まり、後から届く）
    for i in range(10, 15):
        await _metric(client, kiosk_headers, base + timedelta(minutes=i), online=False, healthy=False)
    # ここで1時間の電源OFF（サンプルが存在しない）
    # 再開後 5分ぶん正常稼働
    for i in range(75, 80):
        await _metric(client, kiosk_headers, base + timedelta(minutes=i), online=True, healthy=True)

    r = await client.get(f"{BASE}/uptime", headers=operator_headers)
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["device_id"] == device.id)

    assert item["samples"] == 20
    assert item["powered_sec"] == 20 * 60      # 電源OFFの1時間は分母に入っていない
    assert item["healthy_sec"] == 15 * 60
    assert item["offline_sec"] == 5 * 60       # 通信障害時間
    assert item["uptime_rate"] == 0.75


async def test_uptime_counts_restarts(client, kiosk_headers, operator_headers, device):
    t0 = _now() - timedelta(hours=1)
    await _metric(client, kiosk_headers, t0)
    await _device_event(client, kiosk_headers, "device_boot", t0)
    await _device_event(client, kiosk_headers, "device_restart", t0 + timedelta(minutes=10))
    await _device_event(client, kiosk_headers, "offline", t0 + timedelta(minutes=20))

    r = await client.get(f"{BASE}/uptime", headers=operator_headers)
    item = next(i for i in r.json()["items"] if i["device_id"] == device.id)
    assert item["restart_count"] == 2  # device_boot + device_restart（offline は数えない）


async def test_metrics_store_hardware_values(client, kiosk_headers, device):
    at = _now()
    await _metric(
        client, kiosk_headers, at,
        cpu_percent=23.5, cpu_temp_c=54.2, mem_used_mb=700, mem_total_mb=3800,
        disk_free_mb=12000, disk_total_mb=30000, uptime_sec=86400,
        touch_connected=True, mic_connected=True, camera_connected=False,
        screen_id="idle", browser_age_sec=3.2, agent_version="abc123", os_version="Debian 12 / 6.6",
    )
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(DeviceMetric).where(DeviceMetric.device_id == device.id))).scalars().one()
        assert row.cpu_percent == 23.5
        assert row.cpu_temp_c == 54.2
        assert row.touch_connected is True
        assert row.camera_connected is False
        assert row.screen_id == "idle"


async def test_metric_screen_id_outside_vocabulary_is_dropped(client, kiosk_headers, device):
    """スタッフ専用画面などの未知の画面名はメトリクスにも残さない。"""
    await _metric(client, kiosk_headers, _now(), screen_id="kiosk_settings")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(DeviceMetric).where(DeviceMetric.device_id == device.id))).scalars().one()
        assert row.screen_id is None


async def test_device_versions_mirror_to_devices_table(client, kiosk_headers, device):
    from app.models.device import Device

    await _device_event(client, kiosk_headers, "agent_started", _now(),
                        agent_version="v42", os_version="Debian GNU/Linux 12 / 6.6.51", ui_version="default")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Device).where(Device.id == device.id))).scalar_one()
        assert row.agent_version == "v42"
        assert row.os_version.startswith("Debian")
        assert row.ui_version == "default"
