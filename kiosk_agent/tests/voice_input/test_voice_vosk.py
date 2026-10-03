"""Vosk の読み込みと利用可否。

実モデルを読む試験は環境に左右されるので、ここでは**差し替えたモデルで経路と後始末を
確かめる**。当たり方そのものは scripts/voice_command_eval.py で測る。
"""
from __future__ import annotations

from voice import settings, vosk_engine
from voice_fakes import FakeRecognizer


def test_モデルが無ければ取得方法を案内する(tmp_path):
    settings.cfg()["vosk"]["model_path"] = str(tmp_path / "ない")
    ok, detail = vosk_engine.available()
    assert not ok and "fetch_voice_models.py" in detail


def test_パッケージが無ければ導入方法を案内する(monkeypatch):
    monkeypatch.setattr(vosk_engine, "_probe_package",
                        lambda: (False, "vosk が入っていません (uv pip install vosk)"))
    ok, detail = vosk_engine.available()
    assert not ok and "vosk" in detail


def test_モデルは一度だけ読む(fake_vosk, monkeypatch):
    loaded = []
    import sys
    real = sys.modules["vosk"].Model
    monkeypatch.setattr(sys.modules["vosk"], "Model", lambda p: loaded.append(p) or real(p))
    vosk_engine.load()
    vosk_engine.load()
    assert len(loaded) == 1


def test_起動時の暖機は語彙を絞らない認識器で行い音を残さない(fake_vosk):
    vosk_engine.warmup()
    assert len(fake_vosk) == 1 and fake_vosk[0].grammar is None
    assert fake_vosk[0].fed == b""


def test_暖機はモデルが無くても起動を止めない(tmp_path):
    settings.cfg()["vosk"]["model_path"] = str(tmp_path / "ない")
    vosk_engine.warmup()          # 例外にならない


def test_語彙を絞れるかはモデルのファイルで決まる(fake_vosk):
    assert vosk_engine.describe()["grammar"] is True


# ── 英語(lang="en") ───────────────────────────────────────────────────────────
# `vosk.*`(日本語)とは別の設定節(`vosk_en.*`)を見る。既存の日本語の経路・設定は
# 一切変えない(ネストしない)ことの確認。

def test_英語モデルが無くても日本語は影響を受けない(fake_vosk, tmp_path):
    settings.cfg()["vosk_en"]["model_path"] = str(tmp_path / "ない")
    ok_ja, _ = vosk_engine.available()
    ok_en, detail_en = vosk_engine.available("en")
    assert ok_ja is True
    assert ok_en is False and "fetch_voice_models.py" in detail_en


def test_日英は別のモデルとして読み込まれる(fake_vosk_en):
    m_ja = vosk_engine.load("ja")
    m_en = vosk_engine.load("en")
    assert m_ja is not m_en
    # 2 回目は読み直さない(言語ごとに1回だけ)。
    assert vosk_engine.load("ja") is m_ja
    assert vosk_engine.load("en") is m_en


def test_describe_allは両言語を返す(fake_vosk_en):
    info = vosk_engine.describe_all()
    assert set(info) == {"ja", "en"}
    assert info["ja"]["lang"] == "ja" and info["en"]["lang"] == "en"
    assert info["ja"]["available"] and info["en"]["available"]


def test_言語ごとに認識器のキャッシュが分かれる(fake_vosk_en):
    choices = [("locker", ["ロッカー"])]
    choices_en = [("locker", ["locker"])]
    from voice.types import AudioSegment

    def seg():
        return AudioSegment(pcm=b"\x00\x01" * 9600, sample_rate=16000, total_ms=600, speech_ms=600,
                            stop_reason="silence", peak_db=-20.0, noise_floor_db=-60.0)

    FakeRecognizer.words = [("ロッカー", 1.0)]
    r1 = vosk_engine.recognize_command(seg(), choices, lang="ja")
    FakeRecognizer.words = [("locker", 1.0)]
    r2 = vosk_engine.recognize_command(seg(), choices_en, lang="en")
    assert r1.matched == "locker" and r2.matched == "locker"
    # それぞれの言語のモデルで作った認識器が別々に残る(同じキーで取り違えない)。
    cmd_rec_keys = [k for k in vosk_engine._cmd_recs]
    assert any(k[0] == "ja" for k in cmd_rec_keys)
    assert any(k[0] == "en" for k in cmd_rec_keys)


# ── OTA配信のzip展開(英語モデルはzipのまま配り、初回だけ展開する) ──────────────────

def test_zipが届いていれば展開する(tmp_path):
    import zipfile
    model_dir = tmp_path / "vosk-model-en-us-0.22-lgraph"
    zip_path = tmp_path / "vosk-model-en-us-0.22-lgraph.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("vosk-model-en-us-0.22-lgraph/graph/words.txt", "hello 1\n")
    settings.cfg()["vosk_en"]["model_path"] = str(model_dir)
    assert not model_dir.is_dir()
    vosk_engine._ensure_extracted("en")
    assert (model_dir / "graph" / "words.txt").is_file()


def test_zipが無ければ何もしない(tmp_path):
    model_dir = tmp_path / "vosk-model-en-us-0.22-lgraph"
    settings.cfg()["vosk_en"]["model_path"] = str(model_dir)
    vosk_engine._ensure_extracted("en")  # 例外にならない
    assert not model_dir.exists()


def test_展開済みなら展開し直さない(tmp_path):
    import zipfile
    model_dir = tmp_path / "vosk-model-en-us-0.22-lgraph"
    model_dir.mkdir()
    (model_dir / "marker.txt").write_text("existing")
    zip_path = tmp_path / "vosk-model-en-us-0.22-lgraph.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("vosk-model-en-us-0.22-lgraph/other.txt", "new")
    settings.cfg()["vosk_en"]["model_path"] = str(model_dir)
    vosk_engine._ensure_extracted("en")
    assert (model_dir / "marker.txt").read_text() == "existing"
    assert not (model_dir / "other.txt").exists()


def test_危険なパスを含むzipは展開しない(tmp_path):
    import zipfile
    model_dir = tmp_path / "vosk-model-en-us-0.22-lgraph"
    zip_path = tmp_path / "vosk-model-en-us-0.22-lgraph.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("../evil.txt", "oops")
    settings.cfg()["vosk_en"]["model_path"] = str(model_dir)
    vosk_engine._ensure_extracted("en")
    assert not model_dir.exists()
    assert not (tmp_path.parent / "evil.txt").exists()


def test_ensure_models_extractedは1言語失敗してももう片方を試す(monkeypatch):
    calls = []

    def fake(lang):
        calls.append(lang)
        if lang == "ja":
            raise RuntimeError("boom")

    monkeypatch.setattr(vosk_engine, "_ensure_extracted", fake)
    vosk_engine.ensure_models_extracted()  # 例外にならない
    assert calls == ["ja", "en"]


def test_unloadは言語を指定して片方だけ消せる(fake_vosk_en):
    vosk_engine.load("ja")
    vosk_engine.load("en")
    vosk_engine.unload("en")
    assert vosk_engine._models.get("en") is None
    assert vosk_engine._models.get("ja") is not None
