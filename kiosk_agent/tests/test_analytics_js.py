"""キオスク画面のロガー（static/analytics.js）を Node のハーネスで検証する。

ブラウザを立てずに「順番・滞在時間・エラーと回復の結び付き・入力値が乗らないこと・
通信断と再送・再読込後のセッション継続」を確かめる（`tests/analytics_harness.js`）。

Node が入っていない環境（実機 Pi など）では自動で skip する。OCR モデルが無いときに
名刺テストを skip するのと同じ方針で、CI/開発機のどちらでも走らせられるようにしている。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).parent / "analytics_harness.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い環境ではロガーのテストを skip する")
def test_browser_logger_harness():
    result = subprocess.run(
        ["node", str(HARNESS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
