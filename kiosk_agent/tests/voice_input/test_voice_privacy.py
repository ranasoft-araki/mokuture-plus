"""個人情報とログの要件(§11・§13)。

    - 音声ファイルを恒久保存しない
    - 認識結果・氏名・会社名を診断ログへ出さない
    - 分析ログに残すのは個人を特定できない数値と固定語彙だけ
    - 外部サービスへ音声も結果も送らない
    - 確定・キャンセル・タイムアウトのいずれでも音声と結果が消える
"""
from __future__ import annotations

import json
import logging
import socket
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voice import capture, metrics, session as session_mod, settings, whisper_cpp
from voice.api import router
from voice.types import AudioSegment, Transcript
from voice_audio import silence, tone

# テストに出てくる架空の個人情報。ログにもメトリクスにも現れてはいけない文字列。
SECRETS = [
    "株式会社ラナソフト", "ラナソフト", "荒木秀人", "荒木", "田中太郎", "営業部",
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def engine(monkeypatch):
    def fake_transcribe(seg):
        return Transcript(text="株式会社ラナソフトです", engine="whisper",
                          model_name="whisper-base-q5", recognition_ms=120, avg_token_prob=0.9)

    monkeypatch.setattr(whisper_cpp, "transcribe", fake_transcribe)
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))


def run_once(client, field="company"):
    sid = client.post("/voice/session").json()["session_id"]
    client.post(f"/voice/session/{sid}/listen", json={"field": field})
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in ("done", "error", "cancelled"):
            return sid, state
        time.sleep(0.02)
    pytest.fail("終わらなかった")


# ── 分析ログ(§11・§12) ─────────────────────────────────────────────────────

def test_metrics_file_never_contains_recognised_text(client, engine, feed, tmp_path):
    feed(silence(200) + tone(800) + silence(2000))
    sid, state = run_once(client)
    assert state["result"]["text"] == "株式会社ラナソフト"       # 画面には出る
    client.post(f"/voice/session/{sid}/event", json={"result": "confirm", "edited": True})

    written = (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in written, f"分析ログに {secret} が残っている"


def test_metrics_row_matches_the_agreed_shape(client, engine, feed, tmp_path):
    """§11 で指定されたレコード形。余計な項目を増やさない。"""
    feed(silence(200) + tone(800) + silence(2000))
    run_once(client)
    rows = [json.loads(l) for l in (tmp_path / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    row = rows[0]
    for key in ("sessionId", "screenId", "inputMethod", "model", "audioDurationMs",
                "recognitionDurationMs", "result", "retryCount", "errorCode", "timestamp"):
        assert key in row, key
    assert row["screenId"] == "company-input"
    assert row["inputMethod"] == "voice"
    assert row["result"] == "success"
    assert isinstance(row["sessionId"], str) and len(row["sessionId"]) >= 16


def test_metrics_drops_anything_that_looks_like_content():
    """うっかり本文を混ぜても書かれないこと(二重の網)。"""
    metrics.record({
        "sessionId": "abcdefghijklmnop", "screenId": "company-input", "result": "success",
        "text": "株式会社ラナソフト", "visitor_name": "荒木秀人", "company": "ラナソフト",
        "transcript": "荒木秀人と申します", "words": [("荒木", 0.9)],
    })
    written = metrics._path().read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in written
    row = json.loads(written.splitlines()[0])
    assert set(row) <= {"sessionId", "screenId", "result", "timestamp", "inputMethod"}


def test_metrics_rejects_overlong_values():
    """固定語彙しか入らない項目に長い文字列が来たら捨てる。"""
    metrics.record({"sessionId": "abcdefghijklmnop", "screenId": "x" * 200, "result": "success"})
    row = json.loads(metrics._path().read_text(encoding="utf-8").splitlines()[0])
    assert "screenId" not in row


def test_session_id_is_not_reused_across_sessions(client, engine, feed):
    feed(silence(100))
    a = client.post("/voice/session").json()["session_id"]
    b = client.post("/voice/session").json()["session_id"]
    assert a != b


# ── 診断ログ(§13) ──────────────────────────────────────────────────────────

def test_logs_do_not_contain_recognised_text(client, engine, feed, caplog):
    caplog.set_level(logging.DEBUG)
    feed(silence(200) + tone(800) + silence(2000))
    run_once(client)
    written = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in written, f"ログに {secret} が出ている"


def test_error_logs_do_not_contain_recognised_text(client, engine, feed, caplog):
    caplog.set_level(logging.DEBUG)
    settings.cfg()["vad"]["start_timeout_sec"] = 0.2
    feed(silence(4000))
    run_once(client)
    written = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in written


# ── 音声の後始末(§11) ──────────────────────────────────────────────────────

def test_no_audio_file_is_left_behind(client, engine, feed, tmp_path):
    """処理後に音声ファイルが残らない。"""
    feed(silence(200) + tone(800) + silence(2000))
    run_once(client)
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.suffix in (".wav", ".raw", ".pcm", ".mp3", ".ogg")]
    assert leftovers == []


def test_whisper_cleans_up_its_temp_files(monkeypatch, tmp_path):
    """whisper.cpp へ渡す WAV と JSON は、成功しても失敗しても必ず消える(§11)。"""
    import subprocess

    cfg = settings.cfg()
    cfg["whisper"]["tmp_dir"] = str(tmp_path)
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    monkeypatch.setattr(whisper_cpp, "binary_path", lambda: tmp_path / "whisper-cli")
    monkeypatch.setattr(whisper_cpp, "model_path", lambda: tmp_path / "model.bin")

    def fake_run(cmd, **kw):
        # 本物と同じく <出力ベース>.json を書く
        out_base = cmd[cmd.index("-of") + 1]
        (tmp_path / (out_base.split("\\")[-1].split("/")[-1] + ".json")).write_text(
            json.dumps({"transcription": [{"text": "株式会社ラナソフト",
                                           "tokens": [{"text": "株", "p": 0.9}]}]}),
            encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    seg = AudioSegment(pcm=b"\x00\x00" * 16000, sample_rate=16000, total_ms=1000,
                       speech_ms=800, stop_reason="silence", peak_db=-20.0, noise_floor_db=-55.0)
    result = whisper_cpp.transcribe(seg)
    assert result.text == "株式会社ラナソフト"
    assert list(tmp_path.iterdir()) == [], "一時ファイルが残っている"


def test_whisper_cleans_up_after_timeout(monkeypatch, tmp_path):
    import subprocess

    cfg = settings.cfg()
    cfg["whisper"]["tmp_dir"] = str(tmp_path)
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    monkeypatch.setattr(whisper_cpp, "binary_path", lambda: tmp_path / "whisper-cli")
    monkeypatch.setattr(whisper_cpp, "model_path", lambda: tmp_path / "model.bin")

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    seg = AudioSegment(pcm=b"\x00\x00" * 16000, sample_rate=16000, total_ms=1000,
                       speech_ms=800, stop_reason="silence", peak_db=-20.0, noise_floor_db=-55.0)
    with pytest.raises(whisper_cpp.EngineTimeout):
        whisper_cpp.transcribe(seg)
    assert list(tmp_path.iterdir()) == [], "タイムアウト後に一時ファイルが残っている"


def test_cancel_discards_the_result(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid, _ = run_once(client)
    client.post(f"/voice/session/{sid}/cancel")
    assert client.get(f"/voice/session/{sid}/state").json()["result"] is None


def test_delete_discards_the_result(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid, _ = run_once(client)
    session = session_mod.store.get(sid)
    assert session is not None and session.result is not None
    client.delete(f"/voice/session/{sid}")
    assert session.result is None, "破棄しても認識結果がメモリに残っている"


def test_expired_session_is_purged(client, engine, feed):
    feed(silence(200) + tone(800) + silence(2000))
    sid, _ = run_once(client)
    settings.cfg()["session"]["ttl_sec"] = 0.0
    assert session_mod.store.purge() >= 1
    assert client.get(f"/voice/session/{sid}/state").status_code == 404


def test_audio_segment_clear_drops_the_pcm():
    seg = AudioSegment(pcm=b"\x01\x02" * 1000, sample_rate=16000, total_ms=100,
                       speech_ms=100, stop_reason="silence", peak_db=-20.0, noise_floor_db=-55.0)
    seg.clear()
    assert seg.pcm == b""


# ── 外部へ出さない(§13) ────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    """端末の外への通信を塞ぐ。

    ループバックだけは通す。テストクライアント自身(asyncio のイベントループ)が
    127.0.0.1 の socketpair を使うため。塞ぎたいのは「端末の外」であって、
    ここを塞ぐとテストの土台が動かない。外向きの接続を試みたら即座に失敗する。
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
        host = str(address[0])
        return host in ("127.0.0.1", "::1", "localhost", "0.0.0.0")

    def guard_method(real):
        """socket.socket.connect / connect_ex 用(第1引数が self)。"""
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


def test_whole_flow_works_without_network(client, engine, feed, no_network):
    """インターネットが切れていても音声入力が成立する(§15)。"""
    feed(silence(200) + tone(800) + silence(2000))
    sid, state = run_once(client)
    assert state["phase"] == "done"
    assert state["result"]["text"] == "株式会社ラナソフト"
    client.post(f"/voice/session/{sid}/event", json={"result": "confirm", "edited": False})
    assert not no_network, f"外部へ接続しようとした: {no_network}"


def test_status_and_metrics_work_without_network(client, engine, feed, no_network):
    feed(silence(100))
    assert client.get("/voice/status").json()["available"] is True
    assert client.get("/voice/metrics").status_code == 200
    assert not no_network, f"外部へ接続しようとした: {no_network}"


def test_source_has_no_external_urls():
    """クラウド音声認識 API・生成 AI・CDN を呼ぶコードが紛れ込んでいないこと(§13)。

    モデル取得スクリプト(scripts/)は導入時だけ動くので対象外。
    """
    import re
    from voice import settings as voice_settings

    url = re.compile(r"https?://[^\s\"')]+")
    loopback = ("http://localhost", "http://127.0.0.1", "http://[::1]")
    for path in sorted((voice_settings.AGENT_DIR / "voice").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in url.findall(line):
                # 端末自身(CORS の許可オリジン)は外部ではない。
                if found.startswith(loopback):
                    continue
                assert False, f"{path.name}:{n} に外部 URL がある: {found}"
