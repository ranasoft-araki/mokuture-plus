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
def settings_client(admin):
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


async def test_トークンは伏せて返す(settings_client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})
    data = settings_client.get(f"{API}/settings").json()
    assert data["chatwork"]["api_token"] == "***"
    assert data["chatwork"]["room_id"] == "111"


async def test_ルームIDだけ変えてもトークンは消えない(settings_client, tenant):
    """入力欄にトークンは戻らないので、ルームだけ直す操作が普通に起きる。"""
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})

    r = settings_client.put(f"{API}/settings/chatwork", json={"api_token": "", "room_id": "222"})

    assert r.status_code == 200
    assert await stored(tenant.id) == {"api_token": "secret-token", "room_id": "222"}


async def test_空のまま保存しても設定は残る(settings_client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "secret-token", "room_id": "111"})

    r = settings_client.put(f"{API}/settings/chatwork", json={"api_token": "", "room_id": ""})

    assert r.status_code == 200
    assert await stored(tenant.id) == {"api_token": "secret-token", "room_id": "111"}


async def test_トークンだけ差し替えられる(settings_client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "old", "room_id": "111"})

    settings_client.put(f"{API}/settings/chatwork", json={"api_token": "new", "room_id": ""})

    assert await stored(tenant.id) == {"api_token": "new", "room_id": "111"}


async def test_共通はトークンだけでも連携できる(settings_client, tenant):
    """ルームは配達通知の宛先としてだけ使う。受付の担当者ごとのルーム指定・テスト送信は
    トークンだけで使えるので、ルーム未入力でも登録できる(issue #1 追記分)。"""
    r = settings_client.put(f"{API}/settings/chatwork", json={"api_token": "tok", "room_id": ""})
    assert r.status_code == 200
    assert await stored(tenant.id) == {"api_token": "tok", "room_id": ""}


async def test_共通も新規登録にトークンは必須(settings_client, tenant):
    r = settings_client.put(f"{API}/settings/chatwork", json={"api_token": "", "room_id": ""})
    assert r.status_code == 422
    assert await stored(tenant.id) == {}


async def test_配達用は新規登録でルームも必須(settings_client, tenant):
    """配達用は行はあるがルーム空、を許すとフォールバックせず黙って止まる
    （`chatwork.load_config` 参照）。共通とは扱いを変える。"""
    r = settings_client.put(f"{API}/settings/chatwork_delivery", json={"api_token": "tok", "room_id": ""})
    assert r.status_code == 422
    assert await stored(tenant.id, "chatwork_delivery") == {}


async def test_配達用も同じ扱い(settings_client, tenant):
    await set_notification_setting(tenant.id, "chatwork_delivery", {"api_token": "dl-token", "room_id": "999"})

    settings_client.put(f"{API}/settings/chatwork_delivery", json={"api_token": "", "room_id": "888"})

    assert await stored(tenant.id, "chatwork_delivery") == {"api_token": "dl-token", "room_id": "888"}


async def test_ルーム一覧_未連携かつ未入力なら400(settings_client):
    r = settings_client.post(f"{API}/chatwork/rooms", json={})
    assert r.status_code == 400


async def test_ルーム一覧_保存済みトークンを使う(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api

    await set_notification_setting(tenant.id, "chatwork", {"api_token": "saved-token", "room_id": ""})

    seen = {}

    async def fake_list_rooms(token):
        seen["token"] = token
        return [{"room_id": "1", "name": "部屋A", "type": "group"}]

    monkeypatch.setattr(notifications_api.chatwork_service, "list_rooms", fake_list_rooms)

    r = settings_client.post(f"{API}/chatwork/rooms", json={})

    assert r.status_code == 200
    assert r.json() == {"rooms": [{"room_id": "1", "name": "部屋A", "type": "group"}]}
    assert seen["token"] == "saved-token"


async def test_ルーム一覧_入力中の未保存トークンを優先する(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api

    await set_notification_setting(tenant.id, "chatwork", {"api_token": "saved-token", "room_id": ""})

    seen = {}

    async def fake_list_rooms(token):
        seen["token"] = token
        return []

    monkeypatch.setattr(notifications_api.chatwork_service, "list_rooms", fake_list_rooms)

    settings_client.post(f"{API}/chatwork/rooms", json={"api_token": "typed-but-unsaved"})

    assert seen["token"] == "typed-but-unsaved"


async def test_ルーム一覧_API失敗は502(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api
    from app.services.chatwork import ChatworkApiError

    await set_notification_setting(tenant.id, "chatwork", {"api_token": "saved-token", "room_id": ""})

    async def fake_list_rooms(token):
        raise ChatworkApiError("boom")

    monkeypatch.setattr(notifications_api.chatwork_service, "list_rooms", fake_list_rooms)

    r = settings_client.post(f"{API}/chatwork/rooms", json={})
    assert r.status_code == 502


async def test_テスト送信_ルーム未設定はトークン確認になる(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api

    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": ""})

    async def fake_verify(token):
        return {"name": "テスト太郎", "account_id": "1"}

    monkeypatch.setattr(notifications_api.chatwork_service, "verify_token", fake_verify)

    r = settings_client.post(f"{API}/test/chatwork")

    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_テスト送信_ルーム未設定でトークン無効なら400(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api

    await set_notification_setting(tenant.id, "chatwork", {"api_token": "bad", "room_id": ""})

    async def fake_verify(token):
        return None

    monkeypatch.setattr(notifications_api.chatwork_service, "verify_token", fake_verify)

    r = settings_client.post(f"{API}/test/chatwork")

    assert r.status_code == 400


# ── Slack DM(issue #1 追記分) ──────────────────────────────────────────────────
# SLACK_CLIENT_ID等が未設定のテスト環境では SlackNotifier.enabled() が False になり
# 全エンドポイントが 404 を返すので、各テストで True に差し替える。

def _enable_slack(monkeypatch, notifications_api) -> None:
    monkeypatch.setattr(notifications_api.SlackNotifier, "enabled", staticmethod(lambda: True))


async def test_Slackユーザー一覧_未連携は400(settings_client, monkeypatch):
    from app.api import notifications as notifications_api
    _enable_slack(monkeypatch, notifications_api)

    r = settings_client.get(f"{API}/slack/users")
    assert r.status_code == 400


async def test_Slackユーザー一覧_取得できる(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api
    _enable_slack(monkeypatch, notifications_api)

    await set_notification_setting(tenant.id, "slack", {"bot_access_token": "xoxb-tok"})

    async def fake_list_users(token):
        assert token == "xoxb-tok"
        return [{"id": "U1", "name": "鈴木一郎"}]

    monkeypatch.setattr(notifications_api.SlackNotifier, "list_users", fake_list_users)

    r = settings_client.get(f"{API}/slack/users")

    assert r.status_code == 200
    assert r.json() == {"users": [{"id": "U1", "name": "鈴木一郎"}]}


async def test_Slackユーザー一覧_権限不足は専用メッセージ(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api
    from app.services.slack import SlackApiError
    _enable_slack(monkeypatch, notifications_api)

    await set_notification_setting(tenant.id, "slack", {"bot_access_token": "xoxb-old"})

    async def fake_list_users(token):
        raise SlackApiError("missing_scope")

    monkeypatch.setattr(notifications_api.SlackNotifier, "list_users", fake_list_users)

    r = settings_client.get(f"{API}/slack/users")

    assert r.status_code == 400
    assert "連携してください" in r.json()["detail"]


async def test_SlackチャンネルDM先を保存できる(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api
    _enable_slack(monkeypatch, notifications_api)

    await set_notification_setting(tenant.id, "slack", {"bot_access_token": "xoxb-tok", "channel_id": "", "channel_name": ""})

    async def fake_open_dm(token, user_id):
        assert user_id == "U1"
        return "D999"

    monkeypatch.setattr(notifications_api.SlackNotifier, "open_dm", fake_open_dm)

    r = settings_client.post(f"{API}/slack/channel", json={"user_id": "U1", "display_name": "鈴木一郎"})

    assert r.status_code == 200
    assert r.json()["channel_name"] == "DM: 鈴木一郎"

    data = settings_client.get(f"{API}/slack").json()
    assert data["channel_id"] == "D999"
    assert data["channel_name"] == "DM: 鈴木一郎"


async def test_Slackチャンネル_channel_idもuser_idも無ければ422(settings_client, tenant, monkeypatch):
    from app.api import notifications as notifications_api
    _enable_slack(monkeypatch, notifications_api)

    await set_notification_setting(tenant.id, "slack", {"bot_access_token": "xoxb-tok"})
    r = settings_client.post(f"{API}/slack/channel", json={})
    assert r.status_code == 422
