"""Persistent device state (device_token, device_name).

Stored in device_state.json alongside this file so it survives restarts.
The token is obtained once via PIN exchange and reused from then on.
"""
import json
from pathlib import Path

_STATE_FILE = Path(__file__).parent / "device_state.json"


def get_device_token() -> str:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text()).get("device_token", "")
    return ""


def get_device_name() -> str:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text()).get("device_name", "")
    return ""


def save_device_state(token: str, name: str) -> None:
    _STATE_FILE.write_text(json.dumps({"device_token": token, "device_name": name}, indent=2))


def clear_device_state() -> None:
    """保存済みの端末トークンを削除する（別テナントへの付け替え/再登録用）。
    次回 /register で TENANT_SLUG による新規登録がやり直される。"""
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()


def is_registered() -> bool:
    return bool(get_device_token())
