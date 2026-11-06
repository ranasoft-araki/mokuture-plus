"""GPIO が実機か模擬かを、デバイスチェック画面に出せる形で返すこと。

gpiozero が入らないと gpio.py は黙って模擬に落ちる。以前はこれが画面に出ず、
Pi で「ドアは常に開放中・電子錠はトグルの表示だけ変わる」原因が分からなかった。
"""
from __future__ import annotations

import asyncio
import importlib

import pytest

import gpio


@pytest.fixture(autouse=True)
def _restore_gpio():
    yield
    importlib.reload(gpio)  # 後続のテストへ模擬の状態を持ち越さない


def _reload(monkeypatch, mock_env: str | None):
    if mock_env is None:
        monkeypatch.delenv("MOCK_GPIO", raising=False)
    else:
        monkeypatch.setenv("MOCK_GPIO", mock_env)
    return importlib.reload(gpio)


def test_env_mock_reports_env(monkeypatch):
    g = _reload(monkeypatch, "true")
    assert g.gpio_status() == {"hardware": False, "reason": "env"}


def test_missing_library_reports_no_library(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gpiozero":
            raise ImportError("No module named 'gpiozero'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    g = _reload(monkeypatch, "false")
    assert g.gpio_status() == {"hardware": False, "reason": "no_library"}


def test_device_status_exposes_gpio(monkeypatch):
    _reload(monkeypatch, None)
    import main

    data = asyncio.run(main.device_status())
    assert set(data["gpio"]) == {"hardware", "reason"}
    # mock_gpio は env だけでなく実際の状態と一致させる(旧画面 device-control.html も読む)
    assert data["mock_gpio"] is (not data["gpio"]["hardware"])
