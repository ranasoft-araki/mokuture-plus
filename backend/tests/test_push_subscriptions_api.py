"""プッシュ通知の登録端末メタデータ API。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.push import router
from app.middleware.tenant import get_current_user


def _client(admin):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    return TestClient(app)


def test_登録したOSを端末一覧に返す(admin):
    with _client(admin) as client:
        response = client.post("/api/notifications/push/subscribe", json={
            "endpoint": "https://push.example/device-1",
            "p256dh": "key",
            "auth": "auth",
            "os_name": "Windows",
        })
        assert response.status_code == 201

        subscriptions = client.get("/api/notifications/push/subscriptions").json()
        assert subscriptions[0]["os_name"] == "Windows"


def test_OS未登録の既存端末は不明と表示する(admin):
    with _client(admin) as client:
        response = client.post("/api/notifications/push/subscribe", json={
            "endpoint": "https://push.example/legacy-device",
            "p256dh": "key",
            "auth": "auth",
        })
        assert response.status_code == 201

        subscriptions = client.get("/api/notifications/push/subscriptions").json()
        assert subscriptions[0]["os_name"] == "不明"


def test_再登録時にOSを更新する(admin):
    with _client(admin) as client:
        body = {
            "endpoint": "https://push.example/device-2",
            "p256dh": "old-key",
            "auth": "old-auth",
        }
        assert client.post("/api/notifications/push/subscribe", json=body).status_code == 201
        body.update({"p256dh": "new-key", "auth": "new-auth", "os_name": "Android"})
        assert client.post("/api/notifications/push/subscribe", json=body).status_code == 201

        subscriptions = client.get("/api/notifications/push/subscriptions").json()
        assert len(subscriptions) == 1
        assert subscriptions[0]["os_name"] == "Android"
