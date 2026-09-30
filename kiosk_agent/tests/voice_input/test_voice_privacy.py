"""個人情報とログの要件(声で操作する)。

    - 音声ファイルを残さない
    - 認識した言葉を診断ログ・分析ログへ出さない。画面へも返さない
    - 分析ログに残すのは個人を特定できない数値と固定語彙だけ
    - 外部サービスへ音声も結果も送らない
    - 取り消し・破棄・TTL のいずれでも判定が消える
"""
from __future__ import annotations

import json
import logging
import socket
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voice import metrics, session as session_mod, settings
from voice.api import router
from voice.types import AudioSegment
from voice_audio import silence, tone
from voice_fakes import FakeRecognizer

# 雑談で聞こえた体の言葉。ログにもメトリクスにも画面への返事にも現れてはいけない。
SECRETS = ["荒木", "服部", "ラナソフト", "磯野木工所"]
CHOICES = {"screen": "top", "choices": [{"id": "locker", "phrases": ["ロッカー"]},
                                         {"id": "delivery", "phrases": ["配達"]}]}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def heard(fake_vosk):
    """認識器が秘密の言葉を含む語を返す(実際には [unk] になるが、万一返っても漏らさない)。"""
    FakeRecognizer.words = [("荒木", 0.9, 0.0, 0.3), ("ロッカー", 1.0, 0.3, 0.8)]
    return fake_vosk


def run_once(client):
    sid = client.post("/voice/session").json()["session_id"]
    client.post(f"/voice/session/{sid}/command", json=CHOICES)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in ("done", "error", "cancelled"):
            return sid, state
        time.sleep(0.02)
    pytest.fail("終わらなかった")


# ── 画面への返事・分析ログ ────────────────────────────────────────────────────

def test_state_never_contains_recognised_words(client, heard, feed):
    feed(silence(200) + tone(600) + silence(1500))
    _, state = run_once(client)
    assert state["command"]["matched"] == "locker"
    body = json.dumps(state, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in body, f"画面への返事に {secret} が入っている"


def test_metrics_file_never_contains_recognised_words(client, heard, feed, tmp_path):
    feed(silence(200) + tone(600) + silence(1500))
    run_once(client)
    written = (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in written, f"分析ログに {secret} が残っている"
    row = json.loads(written.splitlines()[0])
    assert row["screenId"] == "command-top" and row["choiceId"] == "locker"


def test_metrics_drops_anything_that_looks_like_content():
    """うっかり本文を混ぜても書かれないこと(二重の網)。"""
    metrics.record({
        "sessionId": "abcdefghijklmnop", "screenId": "command-top", "result": "success",
        "text": "荒木です", "visitor_name": "荒木", "company": "ラナソフト",
        "transcript": "磯野木工所の荒木", "words": [("荒木", 0.9)],
    })
    written = metrics._path().read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in written
    row = json.loads(written.splitlines()[0])
    assert set(row) <= {"sessionId", "screenId", "result", "timestamp"}


def test_metrics_rejects_overlong_values():
    """固定語彙しか入らない項目に長い文字列が来たら捨てる。"""
    metrics.record({"sessionId": "abcdefghijklmnop", "screenId": "x" * 200, "result": "success"})
    row = json.loads(metrics._path().read_text(encoding="utf-8").splitlines()[0])
    assert "screenId" not in row


def test_session_id_is_not_reused_across_sessions(client, fake_vosk, feed):
    feed(silence(100))
    a = client.post("/voice/session").json()["session_id"]
    b = client.post("/voice/session").json()["session_id"]
    assert a != b


# ── 診断ログ ──────────────────────────────────────────────────────────────────

def test_logs_do_not_contain_recognised_words(client, heard, feed, caplog):
    caplog.set_level(logging.DEBUG)
    feed(silence(200) + tone(600) + silence(1500))
    run_once(client)
    written = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in written, f"ログに {secret} が出ている"


# ── 後始末 ────────────────────────────────────────────────────────────────────

def test_no_audio_file_is_left_behind(client, heard, feed, tmp_path):
    feed(silence(200) + tone(600) + silence(1500))
    run_once(client)
    leftovers = [p.name for p in tmp_path.rglob("*") if p.suffix in (".wav", ".raw", ".pcm", ".mp3", ".ogg")]
    assert leftovers == []


def test_recognizer_keeps_no_audio(client, heard, feed):
    """認識器を使い回すので、中に音を残さない。"""
    feed(silence(200) + tone(600) + silence(1500))
    run_once(client)
    assert all(r.fed == b"" for r in heard), "認識器の中に音が残っている"


def test_cancel_discards_the_result(client, heard, feed):
    feed(silence(200) + tone(600) + silence(1500))
    sid, _ = run_once(client)
    client.post(f"/voice/session/{sid}/cancel")
    assert client.get(f"/voice/session/{sid}/state").json()["command"] is None


def test_delete_discards_the_result(client, heard, feed):
    feed(silence(200) + tone(600) + silence(1500))
    sid, _ = run_once(client)
    session = session_mod.store.get(sid)
    assert session is not None and session.command is not None
    client.delete(f"/voice/session/{sid}")
    assert session.command is None, "破棄しても判定がメモリに残っている"


def test_expired_session_is_purged(client, heard, feed):
    feed(silence(200) + tone(600) + silence(1500))
    sid, _ = run_once(client)
    settings.cfg()["session"]["ttl_sec"] = 0.0
    # 判定が出た直後はワーカーが後始末(音声の破棄)の最中のことがあり、使用中の
    # セッションは捨てない決まりなので、後始末が終わるまで少し待つ。
    deadline = time.monotonic() + 2.0
    purged = 0
    while time.monotonic() < deadline and not purged:
        purged = session_mod.store.purge()
        time.sleep(0.02)
    assert purged >= 1
    assert client.get(f"/voice/session/{sid}/state").status_code == 404


def test_audio_segment_clear_drops_the_pcm():
    seg = AudioSegment(pcm=b"\x01\x02" * 1000, sample_rate=16000, total_ms=100,
                       speech_ms=100, stop_reason="silence", peak_db=-20.0, noise_floor_db=-55.0)
    seg.clear()
    assert seg.pcm == b""


# ── 外へ出さない ──────────────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    """端末の外への通信を塞ぐ。

    ループバックだけは通す。テストクライアント自身(asyncio のイベントループ)が
    127.0.0.1 の socketpair を使うため。外向きの接続を試みたら即座に失敗する。
    """
    attempts: list = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    class Blocked(RuntimeError):
        pass

    def _is_loopback(address) -> bool:
        if not isinstance(address, tuple) or not address:
            return False
        return str(address[0]) in ("127.0.0.1", "::1", "localhost", "0.0.0.0")

    def guard_method(real):
        def wrapper(sock, address, *a, **kw):
            if _is_loopback(address):
                return real(sock, address, *a, **kw)
            attempts.append(address)
            raise Blocked(f"音声サービスが外部へ通信しようとした: {address}")
        return wrapper

    def guard_create_connection(address, *a, **kw):
        if _is_loopback(address):
            return real_create(address, *a, **kw)
        attempts.append(address)
        raise Blocked(f"音声サービスが外部へ通信しようとした: {address}")

    monkeypatch.setattr(socket.socket, "connect", guard_method(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard_method(real_connect_ex))
    monkeypatch.setattr(socket, "create_connection", guard_create_connection)
    return attempts


def test_whole_flow_works_without_network(client, heard, feed, no_network):
    """インターネットが切れていても声の操作が成立する。"""
    feed(silence(200) + tone(600) + silence(1500))
    _, state = run_once(client)
    assert state["phase"] == "done" and state["command"]["matched"] == "locker"
    assert not no_network, f"外部へ接続しようとした: {no_network}"


def test_status_and_metrics_work_without_network(client, fake_vosk, feed, no_network):
    feed(silence(100))
    assert client.get("/voice/status").json()["available"] is True
    assert client.get("/voice/metrics").status_code == 200
    assert not no_network, f"外部へ接続しようとした: {no_network}"


def test_source_has_no_external_urls():
    """クラウド音声認識 API・生成 AI・CDN を呼ぶコードが紛れ込んでいないこと。

    モデル取得スクリプト(scripts/)は導入時だけ動くので対象外。
    """
    import re
    from voice import settings as voice_settings

    url = re.compile(r"https?://[^\s\"')]+")
    loopback = ("http://localhost", "http://127.0.0.1", "http://[::1]")
    for path in sorted((voice_settings.AGENT_DIR / "voice").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in url.findall(line):
                if found.startswith(loopback):
                    continue
                assert False, f"{path.name}:{n} に外部 URL がある: {found}"
