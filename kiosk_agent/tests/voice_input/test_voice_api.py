"""音声入力 API(ブラウザとのやりとり)。

実マイクと whisper.cpp のバイナリは差し替え、セッションの進み方・異常系・
ループバック制限を確かめる。
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voice import capture, session as session_mod, settings, whisper_cpp
from voice.api import router
from voice.types import Transcript
from voice_audio import silence, tone


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def remote_client():
    """端末の外から来たリクエストのふり。"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("192.168.1.50", 50000))


@pytest.fixture
def engine(monkeypatch):
    """whisper.cpp を差し替える。返す文字列はテストごとに変えられる。"""
    state = {"text": "株式会社ラナソフトです", "prob": 0.88, "delay": 0.0, "error": None}

    def fake_transcribe(seg):
        if state["delay"]:
            time.sleep(state["delay"])
        if state["error"] is not None:
            raise state["error"]
        return Transcript(text=state["text"], engine="whisper", model_name="whisper-base-q5",
                          recognition_ms=120, avg_token_prob=state["prob"])

    monkeypatch.setattr(whisper_cpp, "transcribe", fake_transcribe)
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    return state


def wait_for(client, sid, phases=("done", "error", "cancelled"), timeout=15.0):
    """状態が落ち着くまでポーリングする(画面がやっているのと同じこと)。"""
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in phases:
            return state
        time.sleep(0.02)
    pytest.fail(f"状態が {phases} にならなかった: {state.get('phase')}")


def start(client):
    return client.post("/voice/session").json()["session_id"]


# ── 利用可否 ──────────────────────────────────────────────────────────────────

def test_status_shape(client, engine, feed):
    feed(silence(100))
    s = client.get("/voice/status").json()
    assert s["available"] is True
    assert s["features"]["company"] is True
    assert s["features"]["person_name"] is True
    # 第3・4段階はまだ。画面が導線を出さないよう false であること。
    assert s["features"]["staff"] is False
    assert s["fields"]["company"]["prompt_ja"] == "会社名をお話しください"
    assert s["fields"]["person_name"]["prompt_ja"] == "お名前をお話しください"
    assert s["timing"]["silence_sec"] == pytest.approx(0.7)


def test_status_without_microphone_is_unavailable(client, engine):
    """マイクが無い端末では available=false。画面はボタンを出さない。"""
    capture.set_override(None)
    s = client.get("/voice/status").json()
    assert s["available"] is False
    assert s["microphone"]["available"] is False


def test_status_without_engine_is_unavailable(client, feed, monkeypatch):
    feed(silence(100))
    monkeypatch.setattr(whisper_cpp, "available", lambda: (False, "モデルがありません"))
    s = client.get("/voice/status").json()
    assert s["available"] is False


def test_disabled_blocks_session(client, engine, feed):
    feed(silence(100))
    settings.cfg()["enabled"] = False
    assert client.get("/voice/status").json()["available"] is False
    assert client.post("/voice/session").status_code == 404


# ── ループバック制限(§10・§13) ──────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("get", "/voice/status"),
    ("post", "/voice/session"),
    ("get", "/voice/metrics"),
    ("get", "/voice/devices"),
])
def test_remote_requests_are_refused(remote_client, method, path):
    """端末の外から音声 API を触れないこと。"""
    resp = getattr(remote_client, method)(path)
    assert resp.status_code == 403


# ── ふつうの流れ ──────────────────────────────────────────────────────────────

def test_listen_returns_recognised_text(client, engine, feed):
    feed(silence(200) + tone(900) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    state = wait_for(client, sid)
    assert state["phase"] == "done"
    r = state["result"]
    assert r["accepted"] is True
    # 定型表現「です」は落ちるが、法人格は残る(§4)
    assert r["text"] == "株式会社ラナソフト"
    assert r["raw_text"] == "株式会社ラナソフトです"
    assert r["model"] == "whisper-base-q5"
    assert r["audio_ms"] > 0
    assert r["total_ms"] >= 0


def test_person_name_field_uses_its_own_normalisation(client, engine, feed):
    engine["text"] = "荒木秀人と申します"
    feed(silence(200) + tone(900) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "person_name"})
    state = wait_for(client, sid)
    assert state["result"]["text"] == "荒木秀人"


def test_phases_progress_while_recording(client, engine, feed):
    """処理中に画面が止まって見えないよう、状態が進んでいくこと(§5)。"""
    feed(silence(300) + tone(1200) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    seen = set()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        seen.add(state["phase"])
        if state["phase"] in ("done", "error"):
            break
        time.sleep(0.005)
    assert "done" in seen
    assert seen & {"listening", "speaking", "recognizing"}, seen


# ── 異常系(§7) ─────────────────────────────────────────────────────────────

def test_no_speech_reports_a_retryable_error(client, engine, feed):
    settings.cfg()["vad"]["start_timeout_sec"] = 0.2
    feed(silence(4000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    state = wait_for(client, sid)
    assert state["phase"] == "error"
    assert state["error_code"] == "no_speech"
    assert state["message"]                      # 画面に出す日本語がある
    assert state["result"] is None


def test_microphone_failure_does_not_break_the_session(client, engine):
    """マイクが取れなくても受付は続けられる(§15)。"""
    def boom():
        raise capture.CaptureUnavailable("arecord が見つかりません")

    capture.set_override(boom)
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    state = wait_for(client, sid)
    assert state["phase"] == "error"
    assert state["error_code"] == "mic_unavailable"


def test_recognition_timeout_is_reported(client, engine, feed):
    engine["error"] = whisper_cpp.EngineTimeout("10 秒で終わりませんでした")
    feed(silence(200) + tone(800) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    state = wait_for(client, sid)
    assert state["error_code"] == "timeout"


def test_low_confidence_still_shows_the_text(client, engine, feed):
    """弾いた結果も画面には出す。利用者が直せるようにするため。"""
    engine["prob"] = 0.1
    feed(silence(200) + tone(900) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    state = wait_for(client, sid)
    assert state["phase"] == "done"
    assert state["result"]["accepted"] is False
    assert state["result"]["error_code"] == "low_confidence"
    assert state["result"]["text"] == "株式会社ラナソフト"


def test_unknown_field_is_refused(client, engine, feed):
    feed(silence(100))
    sid = start(client)
    r = client.post(f"/voice/session/{sid}/listen", json={"field": "passport_number"})
    assert r.status_code == 400


def test_second_listen_while_busy_is_refused(client, engine, feed):
    feed(silence(500) + tone(3000) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    r = client.post(f"/voice/session/{sid}/listen", json={"field": "person_name"})
    assert r.status_code == 409
    client.post(f"/voice/session/{sid}/cancel")


def test_unknown_session_is_404(client):
    r = client.get("/voice/session/" + "a" * 20 + "/state")
    assert r.status_code == 404


def test_malformed_session_id_is_400(client):
    assert client.get("/voice/session/short/state").status_code == 400


# ── 操作 ──────────────────────────────────────────────────────────────────────

def test_cancel_stops_and_discards(client, engine, feed):
    feed(silence(300) + tone(6000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    time.sleep(0.05)
    client.post(f"/voice/session/{sid}/cancel")
    state = wait_for(client, sid, phases=("cancelled", "done", "error"))
    assert state["phase"] in ("cancelled", "error")
    assert state["result"] is None


def test_stop_finishes_recording_early(client, engine, feed):
    feed(silence(200) + tone(8000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    time.sleep(0.05)
    client.post(f"/voice/session/{sid}/stop")
    state = wait_for(client, sid)
    assert state["phase"] == "done"


def test_retry_counts_up(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    wait_for(client, sid)
    r = client.post(f"/voice/session/{sid}/retry").json()
    assert r["retry_count"] == 1
    assert client.get(f"/voice/session/{sid}/state").json()["result"] is None


def test_delete_session_removes_it(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    wait_for(client, sid)
    assert client.delete(f"/voice/session/{sid}").status_code == 204
    assert client.get(f"/voice/session/{sid}/state").status_code == 404


def test_session_limit_drops_the_oldest(client, engine, feed):
    feed(silence(100))
    settings.cfg()["session"]["max_sessions"] = 2
    a, b, c = start(client), start(client), start(client)
    assert session_mod.store.count() <= 2
    assert client.get(f"/voice/session/{a}/state").status_code == 404
    assert client.get(f"/voice/session/{c}/state").status_code == 200
    assert b


# ── 実験ログ(§12) ──────────────────────────────────────────────────────────

def test_confirm_event_is_recorded(client, engine, feed):
    from voice import metrics
    feed(silence(200) + tone(800) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    wait_for(client, sid)
    client.post(f"/voice/session/{sid}/event", json={"result": "confirm", "edited": True})
    s = metrics.summary()
    assert s["confirms"] == 1
    assert s["edited_rate"] == 1.0
    assert s["success_rate"] == 1.0


def test_fallback_event_is_recorded(client, engine, feed):
    from voice import metrics
    feed(silence(100))
    sid = start(client)
    client.post(f"/voice/session/{sid}/event", json={"result": "fallback_touch", "field": "company"})
    assert metrics.summary()["fallback_to_touch"] == 1


def test_unknown_event_is_refused(client, engine, feed):
    feed(silence(100))
    sid = start(client)
    r = client.post(f"/voice/session/{sid}/event", json={"result": "exfiltrate"})
    assert r.status_code == 400


def test_metrics_endpoint_returns_aggregates_only(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})
    wait_for(client, sid)
    s = client.get("/voice/metrics").json()
    assert s["attempts"] == 1
    assert "株式会社ラナソフト" not in str(s)
