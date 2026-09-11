"""設定の解決（既定値 → YAML → 環境変数）と、しきい値がコードに直書きされていないこと。"""
from __future__ import annotations

import pytest

from card import defaults, settings

AGENT_DIR = settings.AGENT_DIR


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def test_設定ファイル例は既定値と完全に一致する():
    """card_reader.yaml.example と defaults.py がずれないようにする。

    片方だけ直すとここで落ちる。運用者が例をコピーして使った時に、既定と違う
    挙動になってしまうのを防ぐため。
    """
    yaml = pytest.importorskip("yaml")
    example = AGENT_DIR / "card_reader.yaml.example"
    assert example.exists(), "設定ファイル例が無い"
    loaded = yaml.safe_load(example.read_text(encoding="utf-8"))
    assert _flatten(loaded) == _flatten(defaults.DEFAULTS)


def test_既定値が読める():
    assert settings.get("ocr.engine") == "paddle_onnx"
    assert settings.get("quality.stable_frames") == 6
    assert settings.get("confidence.ok") == 0.85


def test_存在しないキーは既定値を返す():
    assert settings.get("nope.nothing", "fallback") == "fallback"


@pytest.mark.parametrize("env,path,expected", [
    ("CARD_OCR__ENGINE", "ocr.engine", "tesseract"),
    ("CARD_QUALITY__FOCUS_MIN", "quality.focus_min", 12.5),
    ("CARD_QUALITY__STABLE_FRAMES", "quality.stable_frames", 3),
    ("CARD_ENABLED", "enabled", False),
])
def test_環境変数で上書きできる(monkeypatch, env, path, expected):
    raw = {"tesseract": "tesseract", 12.5: "12.5", 3: "3", False: "false"}[expected]
    monkeypatch.setenv(env, raw)
    settings.reload()
    assert settings.get(path) == expected


def test_環境変数でリストを上書きできる(monkeypatch):
    monkeypatch.setenv("CARD_PREPROCESS__VARIANTS", "color, gray")
    settings.reload()
    assert settings.get("preprocess.variants") == ["color", "gray"]


def test_知らないキーは無視して落ちない(monkeypatch):
    monkeypatch.setenv("CARD_NOSUCH__KEY", "1")
    settings.reload()
    assert settings.get("ocr.engine") == "paddle_onnx"
    assert any("unknown env key" in n for n in settings.notes())


def test_型が合わない値は既定値のまま(monkeypatch):
    monkeypatch.setenv("CARD_QUALITY__STABLE_FRAMES", "たくさん")
    settings.reload()
    assert settings.get("quality.stable_frames") == 6


def test_壊れたYAMLでも起動を止めない(tmp_path, monkeypatch):
    broken = tmp_path / "card_reader.yaml"
    broken.write_text("quality: [これは\n  マッピングではない", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_PATH", broken)
    settings.reload()
    assert settings.get("quality.stable_frames") == 6      # 既定にフォールバック
    assert any("parse failed" in n or "not a mapping" in n for n in settings.notes())


def test_YAMLで上書きできる(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    path = tmp_path / "card_reader.yaml"
    path.write_text("quality:\n  stable_frames: 2\nocr:\n  engine: tesseract\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_PATH", path)
    settings.reload()
    assert settings.get("quality.stable_frames") == 2
    assert settings.get("ocr.engine") == "tesseract"
    assert settings.get("quality.focus_min") == 60.0       # 書かなかった項目は既定のまま


def test_相対パスはエージェント直下を基準に解決する():
    p = settings.resolve_path("models/det.onnx")
    assert p.is_absolute()
    assert p.parent.name == "models"
    assert p.parent.parent == AGENT_DIR


def test_しきい値がコードに直書きされていない():
    """判定モジュールが settings 経由でしきい値を読んでいること。

    数値そのものを禁止はできないので、「設定から読む呼び出しがある」ことと
    「既定値の辞書に全部のキーがある」ことで担保する。
    """
    import inspect
    from card import detect, quality
    for mod in (detect, quality):
        src = inspect.getsource(mod)
        assert "settings.get(" in src, mod.__name__

    flat = _flatten(defaults.DEFAULTS)
    for key in ("detection.canny_low", "detection.aspect_min", "detection.aspect_max",
                "quality.focus_min", "quality.glare_max", "quality.motion_max",
                "quality.stable_frames", "preprocess.output_width",
                "confidence.ok", "confidence.warn"):
        assert key in flat, key
