"""pytest 共通設定。

kiosk_agent 直下をインポートパスに入れ、架空名刺のフィクスチャを共有する。
OCR モデルが未取得の端末では、モデルを要するテストだけを自動で skip する
（検出・補正・抽出・API のテストはモデル無しでも走る）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(AGENT_DIR / "tests") not in sys.path:
    sys.path.insert(0, str(AGENT_DIR / "tests"))


def pytest_configure(config):
    config.addinivalue_line("markers", "ocr: OCR モデルを必要とするテスト")
    config.addinivalue_line("markers", "slow: 数秒かかるテスト")


@pytest.fixture(scope="session")
def fixtures():
    """架空名刺の画像を作るモジュール。"""
    import make_fixtures
    return make_fixtures


@pytest.fixture(scope="session")
def scene(fixtures):
    """パターン名 → BGR 画像 を返す関数（同じ画像は作り直さない）。"""
    import cv2
    import numpy as np
    cache: dict[str, tuple] = {}

    def build(name: str):
        if name not in cache:
            img, quad, spec = fixtures.build(name)
            bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
            cache[name] = (bgr, quad, spec)
        return cache[name]

    return build


@pytest.fixture(scope="session")
def ocr_engine():
    """利用可能な OCR エンジン。使えなければテストを skip する。"""
    from card.ocr import get_engine
    engine = get_engine()
    ok, reason = engine.available()
    if not ok:
        pytest.skip(f"OCR エンジンが使えない: {reason}")
    engine.warmup()
    return engine


@pytest.fixture(autouse=True)
def _reset_settings():
    """テストごとに設定とセッションを初期状態へ戻す。"""
    from card import dicts, session, settings
    settings.reload()
    dicts.reset()
    session.store.clear()
    yield
    session.store.clear()
    settings.reload()
