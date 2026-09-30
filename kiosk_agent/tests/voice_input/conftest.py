"""声で操作するテストの共通土台(fixture のみ)。

実マイクも実モデルも使わずに、録音ループ・語彙・照合・API の流れをそのまま検証
できるようにする。音声は `voice_audio.py` で合成し、`capture.BufferStream` で流す。
Vosk は `voice_fakes.py` のふりに差し替える。
"""
from __future__ import annotations

import sys
import types

import pytest

from voice import capture, session as session_mod, settings, vosk_engine
from voice_fakes import LEXICON, FakeRecognizer


@pytest.fixture(autouse=True)
def _reset_voice(tmp_path):
    """テストごとに設定とセッションを初期状態へ戻し、メトリクスを一時領域へ逃がす。

    実験ログを実行環境のホームに書かないためでもある。
    """
    settings.reload()
    cfg = settings.cfg()
    cfg["metrics"]["path"] = str(tmp_path / "metrics.jsonl")
    session_mod.store.clear()
    capture.set_override(None)
    # 録音デバイスの解決結果はモジュールに覚えるので、テスト間で持ち越さない。
    capture.forget_device()
    vosk_engine.unload()
    yield
    vosk_engine.unload()
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


@pytest.fixture
def fake_vosk(monkeypatch, tmp_path):
    """vosk パッケージとモデル(語彙を絞れる版)を差し替える。作った認識器の一覧を返す。"""
    model_dir = tmp_path / "vosk-model"
    graph = model_dir / "graph"
    graph.mkdir(parents=True)
    (graph / "words.txt").write_text("\n".join(f"{w} {i}" for i, w in enumerate(LEXICON)), encoding="utf-8")
    (graph / "Gr.fst").write_bytes(b"")
    (graph / "HCLr.fst").write_bytes(b"")
    settings.cfg()["vosk"]["model_path"] = str(model_dir)
    made: list[FakeRecognizer] = []

    def kaldi(model, rate, grammar=None):
        r = FakeRecognizer(model, rate, grammar)
        made.append(r)
        return r

    mod = types.SimpleNamespace(Model=lambda path: object(), KaldiRecognizer=kaldi, SetLogLevel=lambda n: None)
    monkeypatch.setitem(sys.modules, "vosk", mod)
    FakeRecognizer.words = []
    FakeRecognizer.free_words = []
    return made
