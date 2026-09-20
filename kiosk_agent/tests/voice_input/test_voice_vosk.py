"""Vosk エンジン。一文の名乗りはこちらを使う。

実モデルを読む試験は環境に左右されるので、ここでは**差し替えたモデルで経路と
後始末を確かめる**。精度そのものは scripts/voice_eval.py で測る。
"""
from __future__ import annotations

import json

import pytest

from voice import engines, settings, vosk_engine, whisper_cpp
from voice.types import AudioSegment


@pytest.fixture(autouse=True)
def _forget_model():
    """テストごとにモデルと認識器を手放す。使い回しの状態を持ち越さない。"""
    vosk_engine.unload()
    yield
    vosk_engine.unload()


class FakeRecognizer:
    """語ごとの信頼度を返す Vosk の認識器のふり。"""

    def __init__(self, model, rate):
        self.rate = rate
        self.words = True
        self.resets = 0
        self.fed = b""

    def SetWords(self, on):
        self.words = on

    def Reset(self):
        self.resets += 1
        self.fed = b""

    def AcceptWaveform(self, pcm):
        self.fed += pcm
        return True

    def FinalResult(self):
        return json.dumps({
            "text": "磯野 木工所 の 荒木 です",
            "result": [{"word": "磯野", "conf": 0.9}, {"word": "荒木", "conf": 0.7}],
        }, ensure_ascii=False)


@pytest.fixture
def fake_vosk(monkeypatch, tmp_path):
    """vosk パッケージとモデルを差し替える。"""
    model_dir = tmp_path / "vosk-model"
    model_dir.mkdir()
    settings.cfg()["vosk"]["model_path"] = str(model_dir)

    made = []

    class FakeModel:
        def __init__(self, path):
            self.path = path

    def kaldi(model, rate):
        r = FakeRecognizer(model, rate)
        made.append(r)
        return r

    import types
    mod = types.SimpleNamespace(Model=FakeModel, KaldiRecognizer=kaldi, SetLogLevel=lambda n: None)
    monkeypatch.setitem(__import__("sys").modules, "vosk", mod)
    return made


def segment(ms: int = 1000, rate: int = 16000) -> AudioSegment:
    pcm = b"\x00\x01" * int(rate * ms / 1000)
    return AudioSegment(pcm=pcm, sample_rate=rate, total_ms=ms, speech_ms=ms,
                        stop_reason="manual", peak_db=-20.0, noise_floor_db=-60.0)


# ── 利用可否 ──────────────────────────────────────────────────────────────────

def test_モデルが無ければ取得方法を案内する(tmp_path):
    settings.cfg()["vosk"]["model_path"] = str(tmp_path / "ない")
    ok, detail = vosk_engine.available()
    assert not ok and "fetch_voice_models.py" in detail


def test_パッケージが無ければ導入方法を案内する(monkeypatch):
    monkeypatch.setattr(vosk_engine, "_probe_package",
                        lambda: (False, "vosk が入っていません (uv pip install vosk)"))
    ok, detail = vosk_engine.available()
    assert not ok and "vosk" in detail


# ── 文字起こし ────────────────────────────────────────────────────────────────

def test_日本語の語間の空白を詰める(fake_vosk):
    tr = vosk_engine.transcribe(segment())
    assert tr.text == "磯野木工所の荒木です"
    assert tr.engine == "vosk"


def test_語ごとの信頼度を平均して返す(fake_vosk):
    tr = vosk_engine.transcribe(segment())
    assert tr.avg_token_prob == pytest.approx(0.8)
    assert ("磯野", 0.9) in tr.words


def test_認識器は使い回す(fake_vosk):
    """毎回作り直すと 3 倍以上遅くなる(実測 4.45秒 → 1.28秒)。"""
    for _ in range(3):
        vosk_engine.transcribe(segment())
    assert len(fake_vosk) == 1, f"認識器を {len(fake_vosk)} 個作っている"


def test_発話ごとに状態を消す(fake_vosk):
    """前の来訪者の音声や結果を持ち越さない(§11)。"""
    vosk_engine.transcribe(segment())
    assert fake_vosk[0].resets >= 1
    assert fake_vosk[0].fed == b"", "認識器の中に音が残っている"


def test_サンプリングレートが変われば作り直す(fake_vosk):
    vosk_engine.transcribe(segment(rate=16000))
    vosk_engine.transcribe(segment(rate=8000))
    assert len(fake_vosk) == 2


def test_失敗したら認識器を捨てる(fake_vosk):
    """壊れた認識器を使い回すと、以後ずっと失敗し続ける。"""
    vosk_engine.transcribe(segment())
    broken = fake_vosk[0]
    good = broken.AcceptWaveform

    def boom(pcm):
        raise RuntimeError("こわれた")

    broken.AcceptWaveform = boom
    with pytest.raises(vosk_engine.EngineFailed):
        vosk_engine.transcribe(segment())
    broken.AcceptWaveform = good

    # 失敗した回は作り直さない。**次の回で新しい個体になる**のが正しい。
    vosk_engine.transcribe(segment())
    assert len(fake_vosk) == 2, "壊れた認識器を使い回している"
    assert fake_vosk[1] is not broken


# ── 項目ごとのエンジン選択 ────────────────────────────────────────────────────

def test_一文はvoskを選ぶ(fake_vosk):
    assert engines.pick("reception") is vosk_engine


def test_voskが使えなければwhisperに落ちる(monkeypatch):
    monkeypatch.setattr(vosk_engine, "available", lambda: (False, "無い"))
    assert engines.pick("reception") is whisper_cpp


def test_名前で指定したら黙って別のエンジンに変えない(monkeypatch):
    """auto でない指定を勝手に差し替えると、精度が変わった理由が分からなくなる。"""
    settings.cfg()["fields"]["reception"]["engine"] = "vosk"
    monkeypatch.setattr(vosk_engine, "available", lambda: (False, "無い"))
    assert engines.pick("reception") is vosk_engine


def test_会社名単独はwhisperのまま():
    """辞書に無い社名は Vosk だと別の実在語に化けて読みごと失われる。"""
    assert engines.pick("company") is whisper_cpp
