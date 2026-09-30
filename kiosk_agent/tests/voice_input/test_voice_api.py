"""声で操作する API の土台(利用可否・セッション・ループバック制限・集計)。

キーワードの聞き取りそのものは test_voice_command.py。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voice import capture, session as session_mod, settings, vosk_engine
from voice.api import router
from voice_audio import silence


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


def start(client):
    return client.post("/voice/session").json()["session_id"]


# ── 利用可否 ──────────────────────────────────────────────────────────────────

def test_status_shape(client, fake_vosk, feed):
    feed(silence(100))
    s = client.get("/voice/status").json()
    assert s["available"] is True
    assert s["features"] == {"command": True}
    assert s["engine"]["engine"] == "vosk" and s["engine"]["grammar"] is True
    assert s["timing"]["poll_interval_ms"] > 0


def test_status_tells_the_screen_to_start_by_itself(client, fake_vosk, feed):
    """既定では画面を開いたら押さなくても聞き取る。設定で押したときだけに戻せる。"""
    feed(silence(100))
    assert client.get("/voice/status").json()["command"]["auto_start"] is True
    settings.cfg()["command"]["auto_start"] = False
    assert client.get("/voice/status").json()["command"]["auto_start"] is False


def test_status_without_microphone_is_unavailable(client, fake_vosk, monkeypatch):
    monkeypatch.setattr(capture, "available", lambda: (False, "録音デバイスが見つかりません"))
    s = client.get("/voice/status").json()
    assert s["available"] is False and s["features"]["command"] is False
    assert s["microphone"]["detail"] == "録音デバイスが見つかりません"


def test_status_without_vosk_is_unavailable(client, feed, monkeypatch):
    feed(silence(100))
    monkeypatch.setattr(vosk_engine, "available", lambda: (False, "vosk が入っていません"))
    s = client.get("/voice/status").json()
    assert s["available"] is False and s["command"]["detail"] == "vosk が入っていません"


def test_語彙を絞れないモデルでは使えない(client, fake_vosk, feed):
    """1GB 版(vosk-model-ja-0.22)は HCLG.fst しか無い。"""
    from pathlib import Path
    feed(silence(100))
    (Path(settings.get("vosk.model_path")) / "graph" / "Gr.fst").unlink()
    s = client.get("/voice/status").json()
    assert s["available"] is False and "語彙を絞れません" in s["command"]["detail"]


def test_disabled_blocks_session(client, fake_vosk, feed):
    feed(silence(100))
    settings.cfg()["enabled"] = False
    assert client.get("/voice/status").json()["available"] is False
    assert client.post("/voice/session").status_code == 404


# ── 外から触らせない ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("get", "/voice/status"),
    ("post", "/voice/session"),
    ("get", "/voice/metrics"),
    ("get", "/voice/devices"),
])
def test_remote_requests_are_refused(remote_client, method, path):
    assert getattr(remote_client, method)(path).status_code == 403


# ── セッション ────────────────────────────────────────────────────────────────

def test_unknown_session_is_404(client):
    assert client.get("/voice/session/" + "a" * 22 + "/state").status_code == 404


def test_malformed_session_id_is_400(client):
    assert client.get("/voice/session/abc/state").status_code == 400
    assert client.delete("/voice/session/../../x").status_code in (400, 404)


def test_delete_session_removes_it(client, fake_vosk, feed):
    feed(silence(100))
    sid = start(client)
    assert client.delete(f"/voice/session/{sid}").status_code == 204
    assert client.get(f"/voice/session/{sid}/state").status_code == 404


def test_session_limit_drops_the_oldest(client, fake_vosk, feed):
    feed(silence(100))
    settings.cfg()["session"]["max_sessions"] = 2
    a, b, c = start(client), start(client), start(client)
    assert client.get(f"/voice/session/{a}/state").status_code == 404
    assert client.get(f"/voice/session/{b}/state").status_code == 200
    assert client.get(f"/voice/session/{c}/state").status_code == 200
    assert session_mod.store.count() == 2


def test_metrics_endpoint_returns_aggregates_only(client):
    s = client.get("/voice/metrics").json()
    assert {"attempts", "matched_rate", "by_screen", "by_choice"} <= set(s)
