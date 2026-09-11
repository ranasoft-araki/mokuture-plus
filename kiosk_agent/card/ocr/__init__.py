"""OCR エンジンの生成。設定 `ocr.engine` の一語で実装を切り替える。

呼び出し側は get_engine() だけを使う。エンジンの生成は 1 プロセス 1 個に固定する
（ONNX のセッションは数十 MB のメモリを持つので毎回作らない）。
"""
from __future__ import annotations

import threading

from card import settings
from card.ocr.base import OcrEngine

_lock = threading.Lock()
_cache: dict[str, OcrEngine] = {}

ENGINE_NAMES = ("paddle_onnx", "tesseract")


def _build(name: str) -> OcrEngine:
    if name == "paddle_onnx":
        from card.ocr.paddle_onnx import PaddleOnnxEngine
        return PaddleOnnxEngine()
    if name == "tesseract":
        from card.ocr.tesseract import TesseractEngine
        return TesseractEngine()
    raise ValueError(f"unknown ocr engine: {name}")


def get_engine(name: str | None = None) -> OcrEngine:
    """設定（または明示指定）のエンジンを返す。生成済みなら使い回す。"""
    key = name or str(settings.get("ocr.engine"))
    if key not in ENGINE_NAMES:
        key = "paddle_onnx"
    with _lock:
        if key not in _cache:
            _cache[key] = _build(key)
        return _cache[key]


def describe_all() -> list[dict]:
    """全エンジンの利用可否（status API / トラブルシュート用）。"""
    out = []
    for name in ENGINE_NAMES:
        try:
            out.append(get_engine(name).describe())
        except Exception as e:
            out.append({"engine": name, "available": False, "detail": type(e).__name__})
    return out


def reset() -> None:
    """キャッシュを捨てる（テスト用）。"""
    with _lock:
        _cache.clear()
