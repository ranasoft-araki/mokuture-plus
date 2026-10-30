"""通知チャネルの全体スイッチ API と後方互換性。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.notifications import router
from app.api import kiosk
from app.database import AsyncSessionLocal
from app.middleware.tenant import get_current_user
from app.models.notification import PushSubscription
from app.services import notification_channels, notification_health
from conftest import add_push_subscription, set_notification_setting  # type: ignore[import-not-found]


def _client(admin):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    return TestClient(app)


async def test_未設定のチャネルは既存テナント互換のためオン(tenant):
    async with AsyncSessionLocal() as db:
        assert await notification_channels.is_enabled(db, tenant.id, "slack") is True
        assert await notification_channels.is_enabled(db, tenant.id, "chatwork") is True
        assert await notification_channels.is_enabled(db, tenant.id, "push") is True


def test_チャネルごとにオフを保存して取得できる(admin):
    with _client(admin) as client:
        response = client.put(
            "/api/notifications/settings/channel-enabled/slack",
            json={"enabled": False},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        settings = client.get("/api/notifications/settings").json()
        assert settings["channel_enabled_slack"] == {"enabled": False}


def test_通知先が一つもなければ警告状態を返す(admin):
    with _client(admin) as client:
        health = client.get("/api/notifications/health").json()
        assert health["no_active_channel"] is True
        assert health["issue_count"] == 0


def test_未知のチャネルは拒否する(admin):
    with _client(admin) as client:
        response = client.put(
            "/api/notifications/settings/channel-enabled/email",
            json={"enabled": False},
        )
        assert response.status_code == 422


async def test_全体プッシュOFFは配達用プッシュも停止する(tenant):
    await set_notification_setting(tenant.id, "push_delivery", {"enabled": True})
    await set_notification_setting(tenant.id, "channel_enabled_push", {"enabled": False})

    async with AsyncSessionLocal() as db:
        assert await kiosk._push_delivery_enabled(tenant.id, db) is False


async def test_全体OFFは配達用SlackとChatworkも送らない(tenant, monkeypatch):
    await set_notification_setting(tenant.id, "slack", {
        "bot_access_token": "xoxb-test", "channel_id": "C-DEFAULT",
    })
    await set_notification_setting(tenant.id, "chatwork", {
        "api_token": "token", "room_id": "123",
    })
    await set_notification_setting(tenant.id, "channel_enabled_slack", {"enabled": False})
    await set_notification_setting(tenant.id, "channel_enabled_chatwork", {"enabled": False})

    async def fail_send(*args, **kwargs):
        raise AssertionError("全体OFFなのに外部送信が呼ばれた")

    monkeypatch.setattr(kiosk.SlackNotifier, "send_to_config", fail_send)
    monkeypatch.setattr(kiosk.chatwork_service, "send_message", fail_send)

    async with AsyncSessionLocal() as db:
        assert await kiosk._notify_slack_text(tenant.id, "test", db) is None
        assert await kiosk._notify_chatwork_text(tenant.id, "test", db) is None


async def test_Slack送信失敗を管理画面の警告として保存する(tenant, admin, monkeypatch):
    await set_notification_setting(tenant.id, "slack", {
        "bot_access_token": "xoxb-test",
        "channel_id": "C-DELETED",
        "channel_name": "#削除済み",
    })

    async def fail_send(*args, **kwargs):
        return False

    monkeypatch.setattr(kiosk.SlackNotifier, "send_to_config", fail_send)
    async with AsyncSessionLocal() as db:
        assert await kiosk._notify_slack_text(tenant.id, "test", db) is False

    with _client(admin) as client:
        health = client.get("/api/notifications/health").json()
        assert health["issue_count"] == 1
        assert health["issues"][0]["channel"] == "slack"
        assert health["issues"][0]["target"] == "#削除済み"

    await notification_health.record_result(tenant.id, "slack", failed=False)
    with _client(admin) as client:
        assert client.get("/api/notifications/health").json()["issue_count"] == 0


async def test_失効したプッシュ端末を削除して警告する(tenant, admin, monkeypatch):
    await add_push_subscription(tenant.id, None, "https://push.example/expired")

    async def expired_push(**kwargs):
        return False, "HTTP 410: subscription expired"

    monkeypatch.setattr(kiosk, "send_push", expired_push)
    async with AsyncSessionLocal() as db:
        assert await kiosk._notify_push_text(
            tenant.id, "title", "body", tenant.id, db
        ) is False

    async with AsyncSessionLocal() as db:
        subscriptions = (await db.execute(select(PushSubscription).where(
            PushSubscription.tenant_id == tenant.id
        ))).scalars().all()
        assert subscriptions == []

    with _client(admin) as client:
        health = client.get("/api/notifications/health").json()
        assert health["issues"][0]["channel"] == "push"
