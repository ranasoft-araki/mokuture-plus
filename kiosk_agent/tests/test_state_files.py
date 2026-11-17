"""端末の状態ファイルが壊れていても止まらないこと・書き込みが一括であること・
定期処理が 1 回の例外で終わらないこと。"""
from __future__ import annotations

import asyncio
import json

import pytest

import state
import sync


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    f = tmp_path / "device_state.json"
    monkeypatch.setattr(state, "_STATE_FILE", f)
    return f


def test_壊れた端末状態は未登録として扱う(state_file):
    state_file.write_text('{"device_token": "abc', encoding="utf-8")   # 停電で書きかけ
    assert state.get_device_token() == ""
    assert state.get_device_name() == ""
    assert state.is_registered() is False
    state_file.write_text("", encoding="utf-8")
    assert state.get_device_token() == ""
    state_file.write_text("[1, 2]", encoding="utf-8")
    assert state.get_device_token() == ""


def test_端末状態は一時ファイル経由で書き残さない(state_file):
    state.save_device_state("tok", "受付端末")
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"device_token": "tok", "device_name": "受付端末"}
    assert not list(state_file.parent.glob("*.tmp"))
    assert state.get_device_token() == "tok" and state.get_device_name() == "受付端末"
    state.clear_device_state()
    state.clear_device_state()   # 無くても例外にしない
    assert state.get_device_token() == ""


def test_メディアの記録が壊れていても空として扱う(tmp_path, monkeypatch):
    monkeypatch.setattr(sync.settings, "media_dir", tmp_path)
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    assert sync._load_manifest() == {}
    sync._save_manifest({"m1": "video/mp4"})
    assert sync._load_manifest() == {"m1": "video/mp4"}
    assert not list(tmp_path.glob("*.tmp"))


def test_同期の繰り返しは想定外の例外で終わらない(monkeypatch):
    calls = {"force": 0, "sync": 0, "sleep": 0}

    async def force(client):
        calls["force"] += 1
        if calls["force"] == 1:
            raise RuntimeError("disk full")

    async def once(client):
        calls["sync"] += 1

    async def fake_sleep(sec):
        calls["sleep"] += 1
        if calls["sleep"] >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(sync, "check_force_refresh", force)
    monkeypatch.setattr(sync, "sync_once", once)
    monkeypatch.setattr(sync.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sync.sync_loop())
    assert calls["force"] == 3 and calls["sync"] == 2


def test_ハートビートの繰り返しは想定外の例外で終わらない(monkeypatch):
    calls = {"token": 0, "sleep": 0}

    def token():
        calls["token"] += 1
        raise RuntimeError("broken")

    async def fake_sleep(sec):
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(sync, "get_device_token", token)
    monkeypatch.setattr(sync.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sync.heartbeat_loop())
    assert calls["token"] == 2
