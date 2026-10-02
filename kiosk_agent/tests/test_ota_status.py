"""OTA の更新確認(デバイスチェック画面の「ソフトウェア更新」)。

「最新です」は記録した版ではなくディスク上の中身で判定する。記録だけ進んで中身が
古い(git で巻き戻された等)端末を「最新」と見せないこと、開発機では何も書き換えない
ことを、サーバーをモックして確かめる。
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

import updater as updater_mod

SOURCE = {"commit": "585655b" + "0" * 33, "date": "2026-10-01T12:14:00Z", "subject": "声の操作: 直す"}


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """端末の作業ディレクトリと配信サーバーを用意する。server の中身を書き換えて使う。"""
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(updater_mod, "_APP_DIR", app)
    monkeypatch.setattr(updater_mod, "_VERSION_FILE", app / ".bundle_version")
    monkeypatch.setattr(updater_mod, "_INFO_FILE", app / ".bundle_info.json")
    monkeypatch.setattr(updater_mod, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(updater_mod, "get_device_token", lambda: "tok")

    server = {"files": {"static/kiosk.html": b"<html>new</html>", "main.py": b"print('new')\n"},
              "source": SOURCE, "down": False, "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        server["requests"].append(request.url.path)
        if server["down"]:
            raise httpx.ConnectError("down", request=request)
        if request.url.path.endswith("/kiosk/bundle/manifest"):
            files = [{"path": p, "hash": _h(b), "size": len(b)} for p, b in server["files"].items()]
            version = _h("|".join(f"{f['path']}:{f['hash']}" for f in files).encode()) if files else "empty"
            return httpx.Response(200, json={"version": version, "files": files, "force": False,
                                             "source": server["source"]})
        rel = request.url.path.split("/kiosk/bundle/file/", 1)[1]
        return httpx.Response(200, content=server["files"][rel])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(updater_mod.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))

    def write(rel: str, data: bytes):
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    return app, server, write


def _updater(enabled: bool = True) -> updater_mod.BundleUpdater:
    u = updater_mod.BundleUpdater()
    u.enabled = enabled
    return u


def test_中身が一致していれば最新で版の名前も記録する(env):
    app, server, write = env
    for rel, data in server["files"].items():
        write(rel, data)
    u = _updater()
    asyncio.run(u.check())
    st = u.status()
    assert st["error"] is None
    assert st["mismatch"] == []
    assert st["pending"] is None
    assert st["local"]["version"] == st["remote"]["version"]
    assert st["local"]["source"] == SOURCE
    assert st["local"]["applied_at"]
    assert st["checked_at"]
    # 取り寄せはしていない
    assert not [p for p in server["requests"] if "/bundle/file/" in p]


def test_記録だけ新しく中身が古い端末は最新と見せず取り寄せ直す(env):
    """git checkout で巻き戻された Pi(2026-10-01 に実際に起きた)。"""
    app, server, write = env
    for rel, data in server["files"].items():
        write(rel, data)
    u = _updater()
    asyncio.run(u.check())
    write("static/kiosk.html", b"<html>old</html>")  # 記録(.bundle_version)は最新のまま中身だけ古い

    asyncio.run(u.check())
    st = u.status()
    assert st["mismatch"] == ["static/kiosk.html"]
    assert st["pending"]["files"] == 1

    restart = asyncio.run(u.apply())
    assert restart is False  # kiosk.html だけなら再起動しない
    assert (app / "static/kiosk.html").read_bytes() == b"<html>new</html>"
    st = u.status()
    assert st["mismatch"] == [] and st["pending"] is None


def test_新しい版を適用すると名前と適用時刻が入れ替わる(env):
    app, server, write = env
    for rel, data in server["files"].items():
        write(rel, data)
    u = _updater()
    asyncio.run(u.check())
    old = u.status()["local"]

    new_source = {**SOURCE, "commit": "a" * 40, "subject": "次の更新"}
    server["files"]["main.py"] = b"print('newer')\n"
    server["source"] = new_source
    asyncio.run(u.check())
    st = u.status()
    assert st["pending"]["source"] == new_source
    assert st["local"]["source"] == SOURCE  # 適用するまでは前の版のまま

    assert asyncio.run(u.apply()) is True  # main.py は再起動が要る
    st = u.status()
    assert st["local"]["version"] == st["remote"]["version"] != old["version"]
    assert st["local"]["source"] == new_source
    info = json.loads((app / ".bundle_info.json").read_text(encoding="utf-8"))
    assert info["version"] == st["local"]["version"]


def test_開発機は突き合わせるだけで何も書き換えない(env):
    app, server, write = env
    write("static/kiosk.html", b"<html>wip</html>")
    write("main.py", server["files"]["main.py"])
    u = _updater(enabled=False)
    asyncio.run(u.check())
    st = u.status()
    assert st["enabled"] is False
    assert st["mismatch"] == ["static/kiosk.html"]
    assert st["pending"] is None
    assert (app / "static/kiosk.html").read_bytes() == b"<html>wip</html>"
    assert not (app / ".bundle_version").exists()


def test_配信元が空なら最新ではなく異常として出す(env):
    """2026-07 に実際に起きた: Render のイメージに kiosk_agent が無く manifest が空だった。"""
    app, server, write = env
    server["files"] = {}
    u = _updater()
    asyncio.run(u.check())
    st = u.status()
    assert st["error"] == "配信元にファイルがありません"
    assert st["mismatch"] is None
    assert not (app / ".bundle_version").exists()


def test_サーバーに届かないときは理由を出す(env):
    app, server, write = env
    server["down"] = True
    u = _updater()
    asyncio.run(u.check())
    st = u.status()
    assert st["error"] == "配信サーバーに接続できません"
    assert st["checked_at"]
    assert st["checking"] is False


def test_未登録の端末は確認しない(env, monkeypatch):
    app, server, write = env
    monkeypatch.setattr(updater_mod, "get_device_token", lambda: None)
    u = _updater()
    asyncio.run(u.check())
    assert u.status()["error"] == "端末が未登録です"
    assert server["requests"] == []


def test_版の名前を記録する前に入った版は記録時刻を適用時刻とみなす(env):
    """この仕組みを入れた更新が届いた直後(.bundle_info.json がまだ無い)。"""
    app, server, write = env
    for rel, data in server["files"].items():
        write(rel, data)
    u = _updater()
    asyncio.run(u.check())
    (app / ".bundle_info.json").unlink()
    st = u.status()
    assert st["local"]["source"] is None
    assert st["local"]["applied_at"]  # .bundle_version の更新時刻

    asyncio.run(u.check())  # 次の確認で名前が付く
    assert u.status()["local"]["source"] == SOURCE
