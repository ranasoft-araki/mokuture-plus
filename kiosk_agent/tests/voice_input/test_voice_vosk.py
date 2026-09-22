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

    #: 語彙を絞ったときに返す結果。テストごとに差し替える。
    grammar_payload = {
        "text": "磯野 木工所 の 荒木 です 服部 様 と の 打ち合わせ",
        "result": [{"word": "服部", "conf": 1.0}, {"word": "林", "conf": 0.7}],
    }

    def __init__(self, model, rate, grammar=None):
        self.rate = rate
        self.grammar = grammar
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
        if self.grammar is not None:
            return json.dumps(self.grammar_payload, ensure_ascii=False)
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

    def kaldi(model, rate, grammar=None):
        r = FakeRecognizer(model, rate, grammar)
        made.append(r)
        return r

    # 発音辞書。グラマーに入れられる語はここにある語だけ。
    graph = model_dir / "graph"
    graph.mkdir()
    (graph / "words.txt").write_text(
        "\n".join(f"{w} {i}" for i, w in enumerate(
            ["<eps>", "[unk]", "服部", "田中", "佐藤", "磯野", "荒木", "様", "さん",
             "です", "の", "と", "申し", "ます", "打ち合わせ", "お", "約束", "で"])),
        encoding="utf-8")

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


# ── 語彙を絞った 2 パス目 ─────────────────────────────────────────────────────

def test_姓だけを語彙に入れる(fake_vosk):
    """姓だけ言われるのが普通。辞書にある一番長い並びを採る。"""
    tokens, missing = vosk_engine.grammar_tokens(["服部 健一", "田中太郎"])
    assert set(tokens) == {"服部", "田中"}      # 管理画面の「服部 健一」の空白も畳む
    assert missing == []


def test_辞書に無い名前は入れられないと分かる(fake_vosk):
    """読み仮名を登録しても Vosk の発音辞書には入らない。呼ぶ側が気づけること。"""
    tokens, missing = vosk_engine.grammar_tokens(["服部健一", "陽菜乃丞"])
    assert tokens == ["服部"]
    assert missing == ["陽菜乃丞"]


def test_信頼度が足りない候補は捨てる(fake_vosk):
    """誤って別人を埋めた語は信頼度が落ちる(実測 0.657〜0.871 / 正解は 1.000)。"""
    settings.cfg()["vosk"]["grammar_min_conf"] = 0.9
    text, sure = vosk_engine.transcribe_vocabulary(segment(), ["服部健一", "田中太郎"])
    assert "服部" in text
    assert sure == ["服部"]          # conf 0.7 の「林」は落ちる(そもそも語彙外)


def test_語彙が同じなら認識器を作り直さない(fake_vosk):
    """作り直しは重い。担当者一覧が変わるのは一日に数回で、発話ごとではない。"""
    for _ in range(3):
        vosk_engine.transcribe_vocabulary(segment(), ["服部健一"])
    assert len(fake_vosk) == 1


def test_語彙が変われば作り直す(fake_vosk):
    vosk_engine.transcribe_vocabulary(segment(), ["服部健一"])
    vosk_engine.transcribe_vocabulary(segment(), ["服部健一", "田中太郎"])
    assert len(fake_vosk) == 2


def test_グラマーに入れられる名前が無ければ何もしない(fake_vosk):
    text, sure = vosk_engine.transcribe_vocabulary(segment(), ["陽菜乃丞"])
    assert (text, sure) == ("", [])
    assert fake_vosk == [], "認識器を作ってしまっている"


def test_2パス目はフリー認識の認識器と別に持つ(fake_vosk):
    """片方ずつ暖まっていてほしい。使い回しの効果を潰さない。"""
    vosk_engine.transcribe(segment())
    vosk_engine.transcribe_vocabulary(segment(), ["服部健一"])
    assert len(fake_vosk) == 2
    assert [r.grammar is None for r in fake_vosk] == [True, False]
