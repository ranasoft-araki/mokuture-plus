"""音声入力テストの共通土台(fixture のみ)。

実マイクも whisper.cpp のバイナリも使わずに、録音ループ・整形・判定・API の流れを
そのまま検証できるようにする。音声は `voice_audio.py` で合成し、
`capture.BufferStream` で流す。
"""
from __future__ import annotations

import pytest

from voice import capture, session as session_mod, settings


@pytest.fixture(autouse=True)
def _reset_voice(tmp_path):
    """テストごとに設定とセッションを初期状態へ戻し、メトリクスを一時領域へ逃がす。

    実験ログを実行環境のホームに書かないためでもある。
    """
    settings.reload()
    cfg = settings.cfg()
    cfg["metrics"]["path"] = str(tmp_path / "metrics.jsonl")
    # whisper の一時ファイルもテスト用の場所へ(/dev/shm は Windows に無い)
    cfg["whisper"]["tmp_dir"] = str(tmp_path)
    session_mod.store.clear()
    capture.set_override(None)
    # 録音デバイスの解決結果はモジュールに覚えるので、テスト間で持ち越さない。
    capture.forget_device()
    yield
    capture.set_override(None)
    capture.forget_device()
    session_mod.store.clear()
    settings.reload()


@pytest.fixture
def feed():
    """PCM を流し込むストリームを capture に差し込むヘルパー。

    既定は実時間で刻む(realtime=True)。API 経由のテストは録音ループを本番と同じ
    条件で回したいため。テストは音の長さぶんだけ実際に待つ。
    """
    created: list[capture.BufferStream] = []

    def _feed(pcm: bytes, *, loop_silence: bool = True, realtime: bool = True):
        def factory():
            s = capture.BufferStream(pcm, loop_silence=loop_silence, realtime=realtime)
            created.append(s)
            return s
        capture.set_override(factory)
        return created

    return _feed
