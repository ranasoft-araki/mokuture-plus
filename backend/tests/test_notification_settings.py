"""通知設定（テナント共通の接続設定）。

Chatwork の API トークンはレスポンスで `***` にマスクしており、画面の入力欄は常に
空で表示される。素直に受け取って上書きすると「ルーム ID だけ直したい」操作で
トークンが消え、Chatwork 通知が丸ごと止まる（担当者ごとのルームも道連れ）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import AsyncSessionLocal
from app.middleware.tenant import get_current_user
from app.models.notification import NotificationSetting
from app.services.crypto import decrypt_dict
from sqlalchemy import select
from conftest import set_notification_setting  # type: ignore[import-not-found]

API = "/api/notifications"


@pytest.fixture
def client(admin):
    from app.api.notifications import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c


async def stored(tenant_id: str, type_: str = "chatwork") -> dict:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.tenant_id == tenant_id,
                NotificationSetting.type == type_,
            )
        )).scalar_one_or_none()
    return decrypt_dict(row.config_json) if row else {}


async def test_トークンは伏せて返す(client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})
    data = client.get(f"{API}/settings").json()
    assert data["chatwork"]["api_token"] == "***"
    assert data["chatwork"]["room_id"] == "111"


async def test_ルームIDだけ変えてもトークンは消えない(client, tenant):
    """入力欄にトークンは戻らないので、ルームだけ直す操作が普通に起きる。"""
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})

    r = client.put(f"{API}/settings/chatwork", json={"api_token": "", "room_id": "222"})

    assert r.status_code == 200
    assert await stored(tenant.id) == {"api_token": "secret-token", "room_id": "222"}


async def test_空のまま保存しても設定は残る(client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})

    r = client.put(f"{API}/settings/chatwork", json={"api_token": "", "room_id": ""})

    assert r.status_code == 200
    assert await stored(tenant.id) == {"api_token": "secret-token", "room_id": "111"}


async def test_トークンだけ差し替えられる(client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "old", "room_id": "111"})

    client.put(f"{API}/settings/chatwork", json={"api_token": "new", "room_id": ""})

    assert await stored(tenant.id) == {"api_token": "new", "room_id": "111"}


async def test_新規登録は両方必須(client, tenant):
    r = client.put(f"{API}/settings/chatwork", json={"api_token": "tok", "room_id": ""})
    assert r.status_code == 422
    assert await stored(tenant.id) == {}


async def test_配達用も同じ扱い(client, tenant):
    await set_notification_setting(tenant.id, "chatwork_delivery", {"api_token": "dl-token", "room_id": "999"})

    client.put(f"{API}/settings/chatwork_delivery", json={"api_token": "", "room_id": "888"})

    assert await stored(tenant.id, "chatwork_delivery") == {"api_token": "dl-token", "room_id": "888"}
