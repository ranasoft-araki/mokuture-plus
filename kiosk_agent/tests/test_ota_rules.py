"""OTA 更新の安全側の決まり。

1. manifest のパスは MANAGED_FILES に完全一致するものだけ扱う(絶対パス・.. は決して書かない)。
   ただし同じ配信で届いた updater.py が配信対象に足したファイルは一緒に届ける
   (届けないと、新しい main.py が import できずに起動しなくなる)。
2. 取り寄せたファイルは manifest のハッシュと照合し、1 つでも違えば何も適用しない。
3. 取り寄せは毎回新しい一時ディレクトリへ。適用は取り寄せが終わるまで待つ。
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

import updater as updater_mod


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    staging_parent = tmp_path / "staging"
    monkeypatch.setattr(updater_mod, "_APP_DIR", app)
    monkeypatch.setattr(updater_mod, "_VERSION_FILE", app / ".bundle_version")
    monkeypatch.setattr(updater_mod, "_INFO_FILE", app / ".bundle_info.json")
    monkeypatch.setattr(updater_mod, "STAGING_DIR", staging_parent)
    monkeypatch.setattr(updater_mod, "get_device_token", lambda: "tok")

    server = {
        "files": {"static/kiosk.html": b"<html>new</html>", "main.py": b"print('new')\n"},
        "extra": [],          # manifest にだけ載せる項目(パスの検証用)
        "serve": {},          # 取り寄せで manifest と違う中身を返すとき
        "requests": [],
        "delay": 0.0,
        "started": None,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        server["requests"].append(request.url.path)
        if request.url.path.endswith("/kiosk/bundle/manifest"):
            files = [{"path": p, "hash": _h(b), "size": len(b)} for p, b in server["files"].items()]
            files += server["extra"]
            version = _h("|".join(f"{f['path']}:{f['hash']}" for f in files if isinstance(f, dict)).encode())
            return httpx.Response(200, json={"version": version, "files": files, "force": False, "source": None})
        rel = request.url.path.split("/kiosk/bundle/file/", 1)[1]
        if server["started"] is not None:
            server["started"].set()
        if server["delay"]:
            await asyncio.sleep(server["delay"])
        data = server["serve"].get(rel, server["files"].get(rel))
        if data is None:
            return httpx.Response(404)
        return httpx.Response(200, content=data)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(updater_mod.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    return app, server, staging_parent, tmp_path


def _updater() -> updater_mod.BundleUpdater:
    u = updater_mod.BundleUpdater()
    u.enabled = True
    return u


def test_配信対象に無いパスは取り寄せも書き込みもしない(env):
    app, server, _, tmp_path = env
    evil = b"x = 1\n"
    server["extra"] = [
        {"path": "../outside.py", "hash": _h(evil), "size": 6},
        {"path": "/etc/cron.d/x", "hash": _h(evil), "size": 6},
        {"path": ".env", "hash": _h(evil), "size": 6},
        {"path": "device_state.json", "hash": _h(evil), "size": 6},
        {"path": "C:/x.py", "hash": _h(evil), "size": 6},
        "not-a-dict",
    ]
    u = _updater()
    asyncio.run(u.check())
    st = u.status()
    assert sorted(st["mismatch"]) == ["main.py", "static/kiosk.html"]
    assert st["remote"]["files"] == 2
    asked = [p for p in server["requests"] if "/bundle/file/" in p]
    assert sorted(p.split("/bundle/file/")[1] for p in asked) == ["main.py", "static/kiosk.html"]
    asyncio.run(u.apply())
    assert not (tmp_path / "outside.py").exists()
    assert not (app / ".env").exists() and not (app / "device_state.json").exists()


def test_パスの判定():
    ok = updater_mod._is_safe_rel
    assert ok("main.py") and ok("card/ocr/base.py")
    for bad in ("", "../x", "a/../../x", "/abs", "\\abs", "C:x", "a\\b", "./a", None, 3):
        assert not ok(bad), bad


def test_新しいupdaterが足したファイルは同じ配信で届ける(env):
    app, server, _, _ = env
    new_updater = b'MANAGED_FILES = [\n    "main.py",\n    "updater.py",\n    "newmod.py",\n]\n'
    server["files"]["updater.py"] = new_updater
    server["files"]["newmod.py"] = b"VALUE = 1\n"
    server["files"]["notlisted.py"] = b"VALUE = 2\n"   # どちらの一覧にも無い
    u = _updater()
    asyncio.run(u.check())
    asked = [p.split("/bundle/file/")[1] for p in server["requests"] if "/bundle/file/" in p]
    assert asked[0] == "updater.py"   # 先に取り寄せて新しい一覧を読む
    assert "newmod.py" in asked and "notlisted.py" not in asked
    assert asyncio.run(u.apply()) is True
    assert (app / "newmod.py").read_bytes() == b"VALUE = 1\n"
    assert not (app / "notlisted.py").exists()


def test_ハッシュが合わなければ何も適用しない(env):
    app, server, staging_parent, _ = env
    server["serve"]["main.py"] = b"print('tampered')\n"
    u = _updater()
    asyncio.run(u.check())
    st = u.status()
    assert st["pending"] is None
    assert "一致しません" in st["error"] and "main.py" in st["error"]
    assert asyncio.run(u.apply()) is False
    assert not (app / "main.py").exists() and not (app / "static/kiosk.html").exists()
    assert not any(staging_parent.iterdir())   # この回の一時ディレクトリは残さない


def test_取り寄せは毎回新しい一時ディレクトリに置く(env):
    app, server, staging_parent, _ = env
    u = _updater()
    asyncio.run(u.check())
    first = u._pending["_staging"]
    server["files"]["main.py"] = b"print('newer')\n"
    asyncio.run(u.check())
    second = u._pending["_staging"]
    assert first != second
    assert Path(first).parent == staging_parent and Path(second).parent == staging_parent
    assert not Path(first).exists()   # 置き換えられた前の版の一時ディレクトリは消す
    asyncio.run(u.apply())
    assert (app / "main.py").read_bytes() == b"print('newer')\n"
    assert not any(staging_parent.iterdir())


def test_取り寄せ中は適用しない(env):
    app, server, _, _ = env

    async def run():
        u = _updater()
        await u.check()                     # 1 つ目の版を適用待ちにする
        assert u.is_ready()
        server["files"]["main.py"] = b"print('v2')\n"
        server["delay"] = 0.2
        server["started"] = asyncio.Event()
        check = asyncio.create_task(u.check())
        await server["started"].wait()      # 2 つ目の版を取り寄せている最中
        assert u.is_ready() is False        # 待機画面に「適用できる」と見せない
        assert await u.apply() is False     # 待たずに何もしない(書きかけを写さない)
        assert not (app / "main.py").exists()
        await check
        assert u.is_ready()
        assert await u.apply() is True      # 取り寄せ終わった版を適用する
        assert (app / "main.py").read_bytes() == b"print('v2')\n"
        assert u.status()["mismatch"] == []

    asyncio.run(run())
