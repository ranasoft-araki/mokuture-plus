"""プッシュ通知の VAPID 鍵（全テナント共通の1組）。

鍵は Render の環境変数に1組だけ置く。以前は管理画面の「VAPID 鍵を生成」でテナントごとに
作っていたが廃止した。テナントの `vapid` 行が残っていても読まない（作る経路も無い）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.middleware.tenant import get_current_user
from conftest import set_notification_setting  # type: ignore[import-not-found]


@pytest.fixture
def push_client(admin, monkeypatch):
    from app.api.push import router

    monkeypatch.setattr(settings, "vapid_public_key", "system-public-key")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c


async def test_全テナント共通の鍵を返す(push_client, tenant):
    r = push_client.get("/api/notifications/push/vapid-public-key")
    assert r.json() == {"public_key": "system-public-key"}


async def test_テナントの古い鍵が残っていても使わない(push_client, tenant):
    await set_notification_setting(tenant.id, "vapid", {"private_key": "p", "public_key": "tenant-public-key"})
    r = push_client.get("/api/notifications/push/vapid-public-key")
    assert r.json() == {"public_key": "system-public-key"}


async def test_鍵の無い環境では未設定を返す(push_client, tenant, monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "")
    r = push_client.get("/api/notifications/push/vapid-public-key")
    assert r.json() == {"public_key": None}


@pytest.mark.parametrize("path", ["/api/notifications/push/setup", "/api/notifications/push/regenerate"])
async def test_鍵を作る経路は無い(push_client, tenant, path):
    """再生成は確認なしでテナントの全購読を消していた。"""
    r = push_client.post(path)
    assert r.status_code in (404, 405)
