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


def test_statusは言語ごとの可否も返す(client, fake_vosk, feed, tmp_path):
    """英語モデル未導入でも落ちない。古いキオスク画面が読む既存キー(ja の可否)は変わらない。"""
    settings.cfg()["vosk_en"]["model_path"] = str(tmp_path / "ない")
    feed(silence(100))
    s = client.get("/voice/status").json()
    assert s["available"] is True            # 既存キー(日本語)は変わらない
    assert set(s["languages"]) == {"ja", "en"}
    assert s["languages"]["ja"]["available"] is True
    assert s["languages"]["en"]["available"] is False   # 英語モデルは未導入


def test_英語モデルが揃っていれば言語ごとの可否がtrueになる(client, fake_vosk_en, feed):
    feed(silence(100))
    s = client.get("/voice/status").json()
    assert s["languages"]["ja"]["available"] is True
    assert s["languages"]["en"]["available"] is True


def test_commandに英語を指定すると英語モデルで聞く(client, fake_vosk_en, feed):
    feed(silence(100))
    sid = start(client)
    from voice_fakes import FakeRecognizer
    FakeRecognizer.words = [("locker", 1.0)]
    r = client.post(f"/voice/session/{sid}/command", json={
        "screen": "top", "choices": [{"id": "locker", "phrases": ["locker"]}], "lang": "en",
    })
    assert r.status_code == 200


def test_commandのlangは既定で日本語(client, fake_vosk, feed):
    """省略時は日本語(旧バージョンのキオスク画面との互換)。"""
    feed(silence(100))
    sid = start(client)
    r = client.post(f"/voice/session/{sid}/command", json={
        "screen": "top", "choices": [{"id": "back", "phrases": ["戻る"]}],
    })
    assert r.status_code == 200


def test_不正なlangは422(client, fake_vosk, feed):
    feed(silence(100))
    sid = start(client)
    r = client.post(f"/voice/session/{sid}/command", json={
        "screen": "top", "choices": [{"id": "back", "phrases": ["戻る"]}], "lang": "fr",
    })
    assert r.status_code == 422


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
    monkeypatch.setattr(vosk_engine, "available", lambda lang="ja": (False, "vosk が入っていません"))
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
