"""端末側の分析ログ（スプール・再送・稼働イベント）。

ANALYTICS.md §15 のうち:
  5. 入力値がログへ保存されない（エージェントは中身を作らない＝ブラウザが送った項目だけ）
  7. 通信断中のイベントが端末内へ保存される
  8. 通信復旧後に正しい順番で再送される
  9. 再送しても二重登録されない（サーバの応答に従って消す）
 12. アプリ異常終了が端末ログから確認できる
 13. ハートビート停止から端末停止を検知できる

新しい依存は増やさないため、非同期テストは `asyncio.run()` で回す
（kiosk_agent の dev 依存は pytest / Pillow だけのまま）。
"""
from __future__ import annotations

import asyncio
import json

import pytest

import analytics as analytics_mod
from analytics import KIND_DEVICE_EVENTS, KIND_EVENTS, KIND_METRICS, DeviceAnalytics, Spool


def run(coro):
    return asyncio.run(coro)


class FakeBrowserState:
    """watchdog.BrowserHeartbeatState の最小スタブ。"""

    def __init__(self, age_sec=1.0, screen="top"):
        self.age_sec = age_sec
        self.screen = screen

    def snapshot(self):
        return {
            "seen_count": 1,
            "last_age_sec": self.age_sec,
            "last_payload": {"screen": self.screen} if self.screen else {},
        }


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class FakeClient:
    """httpx.AsyncClient の差し替え。`script` が各 POST の応答を決める。"""

    calls: list[dict] = []
    script = None  # Callable[[url, body], FakeResponse]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None, timeout=None):
        FakeClient.calls.append({"url": url, "body": json})
        return FakeClient.script(url, json)


def accept_all(url, body):
    ids = [e.get("event_id") or e.get("id") for e in body["events"]]
    return FakeResponse(200, {"accepted": ids, "duplicate": [], "rejected": []})


def network_down(url, body):
    raise OSError("network unreachable")


@pytest.fixture
def agent(tmp_path, monkeypatch):
    FakeClient.calls = []
    FakeClient.script = accept_all
    monkeypatch.setattr(analytics_mod, "httpx", type("M", (), {"AsyncClient": FakeClient}))
    monkeypatch.setattr(analytics_mod, "get_device_token", lambda: "test-device-token")
    spool = Spool(tmp_path / "spool")
    return DeviceAnalytics(FakeBrowserState(), spool=spool)


def _spooled(agent, kind):
    path = agent.spool.dir / f"{kind}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _browser_events(n, start=1):
    """ブラウザが送ってくる形のイベント（**値は一切含まない**）。"""
    return [
        {
            "event_id": f"ev-{i}",
            "session_id": "sess-1",
            "sequence_no": i,
            "client_occurred_at": "2026-11-10T01:15:32.120Z",
            "event_source": "browser",
            "event_name": "action_selected",
            "screen_id": "top",
            "element_id": f"top-tile-{i}",
        }
        for i in range(start, start + n)
    ]


# ── 7. 通信断中のイベントが端末内へ保存される ───────────────────────────────

def test_browser_events_are_written_to_disk_before_ack(agent):
    result = run(agent.submit_browser_events(_browser_events(3)))
    assert result["accepted"] == ["ev-1", "ev-2", "ev-3"]
    # ack した時点で既にディスクに載っている
    assert [r["event_id"] for r in _spooled(agent, KIND_EVENTS)] == ["ev-1", "ev-2", "ev-3"]


def test_malformed_browser_events_are_rejected_not_spooled(agent):
    result = run(agent.submit_browser_events([{"no_id": True}, "notadict"]))
    assert result["accepted"] == []
    assert len(result["rejected"]) == 2
    assert _spooled(agent, KIND_EVENTS) == []


def test_agent_does_not_add_any_content_to_browser_events(agent):
    """エージェントはブラウザが送った項目をそのまま保つ（勝手に増やさない）。"""
    sent = _browser_events(1)[0]
    run(agent.submit_browser_events([dict(sent)]))
    stored = _spooled(agent, KIND_EVENTS)[0]
    assert stored == sent


def test_events_stay_spooled_while_offline(agent):
    FakeClient.script = network_down
    run(agent.submit_browser_events(_browser_events(2)))
    assert run(agent.flush_once()) is False
    # 送れなかったので端末内に残っている
    assert [r["event_id"] for r in _spooled(agent, KIND_EVENTS)] == ["ev-1", "ev-2"]
    assert agent.online is False


# ── 8. 通信復旧後に正しい順番で再送される ───────────────────────────────────

def test_resends_in_order_after_recovery(agent):
    FakeClient.script = network_down
    run(agent.submit_browser_events(_browser_events(3)))
    run(agent.flush_once())
    # 断の間にも操作は続く
    run(agent.submit_browser_events(_browser_events(2, start=4)))
    assert [r["event_id"] for r in _spooled(agent, KIND_EVENTS)] == ["ev-1", "ev-2", "ev-3", "ev-4", "ev-5"]

    FakeClient.calls = []
    FakeClient.script = accept_all
    assert run(agent.flush_once()) is True

    uploads = [c for c in FakeClient.calls if c["url"].endswith("/analytics/events")]
    assert [e["event_id"] for e in uploads[0]["body"]["events"]] == ["ev-1", "ev-2", "ev-3", "ev-4", "ev-5"]
    assert _spooled(agent, KIND_EVENTS) == []
    assert agent.online is True

    # 断・復旧は端末イベントとして送られている（送信済みのぶんはスプールから消えるので
    # 「何が送られたか」で確認する）。
    uploaded_device = [
        e["event_name"]
        for c in FakeClient.calls if c["url"].endswith("/analytics/device-events")
        for e in c["body"]["events"]
    ]
    assert "offline" in uploaded_device
    pending_device = [r["event_name"] for r in _spooled(agent, KIND_DEVICE_EVENTS)]
    assert "network_recovered" in pending_device and "online" in pending_device


# ── 9. サーバが受理/重複と答えたものだけ消す ───────────────────────────────

def test_only_server_confirmed_events_are_removed(agent):
    run(agent.submit_browser_events(_browser_events(3)))

    def partial(url, body):
        return FakeResponse(200, {"accepted": ["ev-1"], "duplicate": ["ev-2"], "rejected": []})

    FakeClient.script = partial
    run(agent.flush_once())
    # 受理も重複も「サーバに載っている」ので消す。返事の無かった ev-3 は残る。
    assert [r["event_id"] for r in _spooled(agent, KIND_EVENTS)] == ["ev-3"]


def test_rejected_events_are_dropped_to_avoid_endless_retry(agent):
    run(agent.submit_browser_events(_browser_events(2)))

    def reject_one(url, body):
        return FakeResponse(200, {"accepted": ["ev-1"], "duplicate": [], "rejected": [{"id": "ev-2", "reason": "schema"}]})

    FakeClient.script = reject_one
    run(agent.flush_once())
    assert _spooled(agent, KIND_EVENTS) == []


def test_unrecoverable_status_drops_batch_and_records_count(agent):
    run(agent.submit_browser_events(_browser_events(2)))
    FakeClient.script = lambda url, body: FakeResponse(413, {"detail": "too large"})
    run(agent.flush_once())
    assert _spooled(agent, KIND_EVENTS) == []
    dropped = [r for r in _spooled(agent, KIND_DEVICE_EVENTS) if r["event_name"] == "log_dropped"]
    assert dropped and dropped[0]["count"] == 2


def test_auth_pending_keeps_events(agent):
    """承認待ち/トークン不正(401)では捨てずに残す（承認後に届く）。"""
    run(agent.submit_browser_events(_browser_events(1)))
    FakeClient.script = lambda url, body: FakeResponse(401, {"detail": "Invalid kiosk token"})
    assert run(agent.flush_once()) is False
    assert [r["event_id"] for r in _spooled(agent, KIND_EVENTS)] == ["ev-1"]


# ── 端末稼働イベント・メトリクス ───────────────────────────────────────────

def test_metric_marks_healthy_when_browser_is_fresh_and_online(agent):
    agent.online = True
    run(agent.record_metric(with_metrics=False))
    row = _spooled(agent, KIND_METRICS)[0]
    assert row["app_healthy"] is True
    assert row["online"] is True
    assert row["screen_id"] == "top"
    assert row["interval_sec"] == analytics_mod.HEARTBEAT_SEC


def test_metric_not_healthy_when_browser_heartbeat_is_stale(agent):
    agent.online = True
    agent.browser_state.age_sec = analytics_mod.BROWSER_STALE_SEC + 10
    run(agent.record_metric(with_metrics=False))
    assert _spooled(agent, KIND_METRICS)[0]["app_healthy"] is False


def test_metric_not_healthy_on_pending_screen(agent):
    """承認待ち画面は「受付アプリが正常表示されている」に数えない。"""
    agent.online = True
    agent.browser_state.screen = "pending"
    run(agent.record_metric(with_metrics=False))
    row = _spooled(agent, KIND_METRICS)[0]
    assert row["app_healthy"] is False
    assert row["screen_id"] == "pending"


def test_kiosk_settings_screen_is_not_recorded(agent):
    """スタッフ専用の設定画面は画面名ごと記録しない。"""
    agent.online = True
    agent.browser_state.screen = "kiosk-settings"
    run(agent.record_metric(with_metrics=False))
    assert _spooled(agent, KIND_METRICS)[0]["screen_id"] is None


def test_app_crash_is_recorded_once(agent):
    agent.browser_state.age_sec = analytics_mod.BROWSER_STALE_SEC + 30
    run(agent.check_browser_health())
    run(agent.check_browser_health())
    crashes = [r for r in _spooled(agent, KIND_DEVICE_EVENTS) if r["event_name"] == "app_crashed"]
    assert len(crashes) == 1
    assert crashes[0]["detail_code"] == "heartbeat_stale"


def test_browser_restart_is_detected_by_page_id(agent):
    run(agent.on_browser_heartbeat({"page_id": "p1", "screen": "idle"}))
    run(agent.on_browser_heartbeat({"page_id": "p1", "screen": "top"}))
    run(agent.on_browser_heartbeat({"page_id": "p2", "screen": "idle"}))
    names = [r["event_name"] for r in _spooled(agent, KIND_DEVICE_EVENTS)]
    assert names == ["browser_started", "page_reloaded"]


def test_startup_reports_boot_when_uptime_is_short(agent, monkeypatch):
    monkeypatch.setattr(analytics_mod.sysinfo, "uptime_sec", lambda: 20)
    monkeypatch.setattr(analytics_mod, "_RUNNING_MARK", agent.spool.dir / "running.mark")
    run(agent.on_startup())
    names = [r["event_name"] for r in _spooled(agent, KIND_DEVICE_EVENTS)]
    assert names[0] == "agent_started"
    assert "device_boot" in names


def test_startup_reports_restart_after_unclean_shutdown(agent, monkeypatch):
    mark = agent.spool.dir / "running.mark"
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text("1")  # 前回の停止マークが残っている＝正常停止しなかった
    monkeypatch.setattr(analytics_mod.sysinfo, "uptime_sec", lambda: 20)
    monkeypatch.setattr(analytics_mod, "_RUNNING_MARK", mark)
    run(agent.on_startup())
    events = {r["event_name"]: r for r in _spooled(agent, KIND_DEVICE_EVENTS)}
    assert "device_restart" in events
    assert events["device_restart"]["detail_code"] == "unclean_shutdown"


def test_shutdown_records_clean_stop_and_clears_mark(agent, monkeypatch):
    mark = agent.spool.dir / "running.mark"
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text("1")
    monkeypatch.setattr(analytics_mod, "_RUNNING_MARK", mark)
    run(agent.on_shutdown())
    assert not mark.exists()
    # 停止イベントは送信まで試みる（送れた場合はスプールから消えるので送信内容で確認する）。
    uploaded = [
        e["event_name"]
        for c in FakeClient.calls if c["url"].endswith("/analytics/device-events")
        for e in c["body"]["events"]
    ]
    spooled = [r["event_name"] for r in _spooled(agent, KIND_DEVICE_EVENTS)]
    assert "device_shutdown" in uploaded + spooled
    assert "agent_stopped" in uploaded + spooled


# ── スプールの上限 ───────────────────────────────────────────────────────────

def test_spool_drops_oldest_when_over_limit(agent, monkeypatch):
    monkeypatch.setattr(analytics_mod, "MAX_SPOOL_LINES", 5)
    run(agent.submit_browser_events(_browser_events(8)))
    ids = [r["event_id"] for r in _spooled(agent, KIND_EVENTS)]
    assert ids == ["ev-4", "ev-5", "ev-6", "ev-7", "ev-8"]  # 古いものから捨てる
    assert agent.spool.dropped[KIND_EVENTS] == 3
