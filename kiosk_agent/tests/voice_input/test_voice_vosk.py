"""Vosk の読み込みと利用可否。

実モデルを読む試験は環境に左右されるので、ここでは**差し替えたモデルで経路と後始末を
確かめる**。当たり方そのものは scripts/voice_command_eval.py で測る。
"""
from __future__ import annotations

from voice import settings, vosk_engine


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
