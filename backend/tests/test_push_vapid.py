"""プッシュ通知の VAPID 鍵（全テナント共通の1組）。

鍵は Render の環境変数に1組だけ置く。以前は管理画面の「VAPID 鍵を生成」でテナントごとに
作っており、その `vapid` 行を持つテナントの端末はその鍵で購読しているので、行がある限り
そちらを優先する（切り替えると届かなくなる）。新しく行を作る経路はもう無い。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.middleware.tenant import get_current_user
from app.models.notification import NotificationSetting
from conftest import set_notification_setting  # type: ignore[import-not-found]


@pytest.fixture
def push_client(admin, monkeypatch):
    from app.api.notifications import router as notifications_router
    from app.api.push import router as push_router

    monkeypatch.setattr(settings, "vapid_public_key", "system-public-key")
    app = FastAPI()
    app.include_router(push_router, prefix="/api")
    app.include_router(notifications_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c


async def vapid_rows(tenant_id: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.tenant_id == tenant_id,
                NotificationSetting.type == "vapid",
            )
        )).scalars().all()
    return len(rows)


async def test_鍵の無いテナントは共通の鍵で購読する(push_client, tenant):
    r = push_client.get("/api/notifications/push/vapid-public-key")
    assert r.json() == {"public_key": "system-public-key"}


async def test_以前に作ったテナントの鍵があればそちらを返す(push_client, tenant):
    await set_notification_setting(tenant.id, "vapid", {"private_key": "p", "public_key": "tenant-public-key"})
    r = push_client.get("/api/notifications/push/vapid-public-key")
    assert r.json() == {"public_key": "tenant-public-key"}


async def test_setupは鍵を作らずに返すだけ(push_client, tenant):
    """配布済みの古い管理画面がまだ呼ぶので、消さずに無害にしてある。"""
    r = push_client.post("/api/notifications/push/setup")
    assert r.status_code == 200
    assert r.json()["public_key"] == "system-public-key"
    assert await vapid_rows(tenant.id) == 0


async def test_再生成は無い(push_client, tenant):
    """押すと確認なしでテナントの全購読が消えていた。"""
    r = push_client.post("/api/notifications/push/regenerate")
    assert r.status_code in (404, 405)


async def test_通知設定の取得に秘密鍵を出さない(push_client, tenant):
    await set_notification_setting(tenant.id, "vapid", {"private_key": "secret", "public_key": "pub"})
    await set_notification_setting(tenant.id, "webpush", {"private_key": "secret", "public_key": "pub"})
    data = push_client.get("/api/notifications/settings").json()
    assert "vapid" not in data
    assert "webpush" not in data
