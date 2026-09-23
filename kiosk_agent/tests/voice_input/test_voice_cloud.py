"""クラウド音声認識への中継。

**鍵は端末に置かない。** キオスクは自社 API を叩き、サーバが AmiVoice を呼ぶ。
発売済みの端末すべてに鍵を配って回る必要がないこと、そしてサーバが無効なときに
**受付が止まらない**ことをここで押さえる。
"""
from __future__ import annotations

import time

import pytest

from voice import cloud, settings
from voice.types import AudioSegment


class FakeResponse:
    def __init__(self, status: int = 200, text: str = "磯野木工所の荒木です"):
        self.status_code = status
        self._text = text

    def json(self):
        return {"text": self._text, "engine": "amivoice", "ms": 900}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def relay(monkeypatch):
    """登録済みの端末に見せかけ、往復を差し替える。"""
    calls: list[dict] = []

    def fake_post(url, files=None, headers=None, timeout=None):
        calls.append({"url": url, "files": files, "headers": headers})
        return calls[-1].get("_response") or FakeResponse()

    cloud.reset()
    monkeypatch.setattr(cloud, "_token", lambda: "device-token")
    monkeypatch.setattr(cloud.httpx, "post", fake_post)
    settings.cfg()["cloud"]["enabled"] = True
    settings.cfg()["cloud"]["api_url"] = "https://example.invalid/api"
    yield calls
    cloud.reset()


def segment(ms: int = 1000) -> AudioSegment:
    pcm = b"\x00\x01" * int(16000 * ms / 1000)
    return AudioSegment(pcm=pcm, sample_rate=16000, total_ms=ms, speech_ms=ms,
                        stop_reason="manual", peak_db=-20.0, noise_floor_db=-60.0)


def test_未登録の端末は問い合わせない(monkeypatch):
    """登録前(承認待ち)の端末が外へ音を出さないこと。"""
    monkeypatch.setattr(cloud, "_token", lambda: "")
    settings.cfg()["cloud"]["enabled"] = True
    settings.cfg()["cloud"]["api_url"] = "https://example.invalid/api"
    ok, detail = cloud.available()
    assert not ok and "登録" in detail
    assert cloud.start(segment(), []) is None


def test_設定で止められる(relay):
    settings.cfg()["cloud"]["enabled"] = False
    ok, detail = cloud.available()
    assert not ok and "cloud.enabled" in detail


def test_端末トークンを付けて自社APIへ送る(relay):
    text = cloud.finish(cloud.start(segment(), ["服部健一 はっとりけんいち"]), 5.0)
    assert text == "磯野木工所の荒木です"
    sent = relay[0]
    assert sent["url"].endswith("/kiosk/voice/transcribe")
    assert sent["headers"]["X-Kiosk-Token"] == "device-token"
    names = [f for f in sent["files"] if f[0] == "words"][0][1][1]
    assert "服部健一 はっとりけんいち" in names


def test_サーバが無効ならしばらく問い合わせない(relay, monkeypatch):
    """鍵が無い・テナント未許可のとき、毎回の無駄な往復をしない。"""
    monkeypatch.setattr(cloud.httpx, "post",
                        lambda *a, **k: (relay.append({"url": a[0] if a else k.get("url")}),
                                         FakeResponse(status=503))[1])
    assert cloud.finish(cloud.start(segment(), []), 5.0) == ""
    tried = len(relay)
    assert cloud.start(segment(), []) is None       # 2 回目は投げない
    assert len(relay) == tried
    ok, detail = cloud.available()
    assert not ok and "サーバ" in detail


def test_間に合わなければローカルを使う(relay, monkeypatch):
    """予算を過ぎたら空文字。呼ぶ側はローカルの結果をそのまま使う。"""
    def slow_post(*a, **k):
        time.sleep(0.5)
        return FakeResponse()

    monkeypatch.setattr(cloud.httpx, "post", slow_post)
    started = time.monotonic()
    assert cloud.finish(cloud.start(segment(), []), 0.05) == ""
    assert time.monotonic() - started < 0.4, "予算を超えて待っている"


def test_失敗しても例外を投げない(relay, monkeypatch):
    """受付を止めないこと。"""
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(cloud.httpx, "post", boom)
    assert cloud.finish(cloud.start(segment(), []), 5.0) == ""


def test_読みの無い担当者は渡さない():
    """読みの推測は禁止。渡す語は「表記 読み」がそろったものだけ。"""
    from voice.extract import Staff

    words = cloud.words_for([Staff("服部 健一", "はっとりけんいち"), Staff("田中 一郎")])
    assert words == ["服部健一 はっとりけんいち"]


# ── セッションに組み込んだときの振る舞い ──────────────────────────────────────

@pytest.fixture
def session_client(monkeypatch):
    """ローカル認識を差し替えた音声サービス。一文の名乗りを流せる。"""
    from concurrent.futures import Future

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from voice import vosk_engine
    from voice.api import router
    from voice.types import Transcript

    monkeypatch.setattr(vosk_engine, "available", lambda: (True, "test"))
    monkeypatch.setattr(vosk_engine, "transcribe", lambda seg: Transcript(
        text="その木工所の荒木です", engine="vosk", model_name="vosk-small-ja-0.22",
        recognition_ms=120, avg_token_prob=0.9))
    monkeypatch.setattr(vosk_engine, "transcribe_vocabulary", lambda seg, names: ("", []))

    def put(text: str | None):
        """クラウドの返事を仕込む。None なら「返らなかった」。"""
        def fake_start(seg, words):
            if text is None:
                return None
            f: Future = Future()
            f.set_result(text)
            return f
        monkeypatch.setattr(cloud, "start", fake_start)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000)), put


def run_reception(client, feed):
    from voice_audio import silence, tone

    feed(silence(120) + tone(700) + silence(900))
    sid = client.post("/voice/session").json()["session_id"]
    client.post(f"/voice/session/{sid}/listen", json={"field": "reception"})
    deadline = time.time() + 15.0
    while time.time() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in ("done", "error", "cancelled"):
            return state
        time.sleep(0.02)
    pytest.fail("認識が終わらなかった")


def test_クラウドが返ればその文字起こしを使う(session_client, feed):
    """固有名詞はクラウドの方が当たる(実測: 会社名 5/10 → 9/10)。"""
    client, put = session_client
    put("磯野木工所の荒木と申します")
    state = run_reception(client, feed)
    assert "磯野木工所" in state["result"]["raw_text"]
    assert state["result"]["extracted"]["visitor_company"] == "磯野木工所"


def test_クラウドが返らなければローカルのまま(session_client, feed):
    """通信できなくても受付は止まらない。"""
    client, put = session_client
    put(None)
    state = run_reception(client, feed)
    assert "その木工所" in state["result"]["raw_text"]
    assert state["phase"] == "done"
