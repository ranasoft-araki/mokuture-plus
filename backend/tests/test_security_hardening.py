"""セキュリティまわりの決まりごと(端末の承認・ログイン・権限・通知文面・外部送信先 等)。

アプリ全体(`client`)へ実際のトークンで入り、認証の判定そのものを通して確かめる。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import select

from app.config import Settings, insecure_default_secrets, settings
from app.database import AsyncSessionLocal
from app.models.device import Device
from app.models.notification import NotificationSetting, PushSubscription
from app.models.reception import ReceptionLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services import login_throttle, mail_quota, url_safety
from app.services.auth import (
    create_access_token,
    create_proxy_access_token,
    create_refresh_token,
    create_sse_ticket,
    hash_password,
)
from app.services.crypto import decrypt_dict
from conftest import add_reception, set_notification_setting  # type: ignore[import-not-found]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _user(tenant_id: str | None, role: str = "admin", *, email: str | None = None,
                password: str | None = None, created_at: datetime | None = None) -> User:
    async with AsyncSessionLocal() as db:
        u = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=email or f"{uuid.uuid4().hex[:8]}@example.test",
            hashed_password=hash_password(password) if password else "x",
            role=role, name="利用者",
        )
        if created_at is not None:
            u.created_at = created_at
        db.add(u)
        await db.commit()
        return u


def _token(u: User, **kw) -> str:
    return create_access_token(u.tenant_id or "", u.id, u.role, **kw)


async def _set_device(device_id: str, **values) -> None:
    async with AsyncSessionLocal() as db:
        d = await db.get(Device, device_id)
        for k, v in values.items():
            setattr(d, k, v)
        await db.commit()


# ── S3: 承認待ち・停止中の端末 ─────────────────────────────────────────────────

async def test_承認待ち端末は受付できないが状態確認はできる(client, device, kiosk_headers):
    await _set_device(device.id, status="pending")
    r = await client.post("/api/kiosk/reception", json={"visitor_name": "山田"}, headers=kiosk_headers)
    assert r.status_code == 403
    assert "承認" in r.json()["detail"]
    for path in ("/api/kiosk/lockers", "/api/kiosk/content-manifest", "/api/kiosk/appointment/x"):
        assert (await client.get(path, headers=kiosk_headers)).status_code == 403, path
    assert (await client.post("/api/kiosk/call-staff", json={}, headers=kiosk_headers)).status_code == 403

    r = await client.get("/api/kiosk/status", headers=kiosk_headers)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert (await client.post("/api/kiosk/heartbeat", headers=kiosk_headers)).status_code == 200
    r = await client.get("/api/kiosk/schedule", headers=kiosk_headers)
    assert r.status_code == 200 and r.json()["pending"] is True


async def test_停止中テナントの端末は受付できないがスケジュールは停止表示を返す(client, tenant, kiosk_headers):
    async with AsyncSessionLocal() as db:
        t = await db.get(Tenant, tenant.id)
        t.is_suspended = True
        await db.commit()
    r = await client.post("/api/kiosk/reception", json={"visitor_name": "山田"}, headers=kiosk_headers)
    assert r.status_code == 403
    r = await client.get("/api/kiosk/schedule", headers=kiosk_headers)
    assert r.status_code == 200 and r.json()["suspended"] is True


async def test_承認済み端末は従来どおり受付できる(client, kiosk_headers, monkeypatch):
    from app.services import reception_notify

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(reception_notify, "fire_reception_notifications", noop)
    r = await client.post("/api/kiosk/reception", json={"visitor_name": "山田"}, headers=kiosk_headers)
    assert r.status_code == 201


# ── N1: 自己登録の再登録 ──────────────────────────────────────────────────────

async def test_再登録はトークンを示せば同じトークン_示さなければ作り直して承認待ち(client, tenant, device):
    await _set_device(device.id, hardware_id="hw-1")
    body = {"tenant_slug": tenant.slug, "hardware_id": "hw-1"}

    r = await client.post("/api/kiosk/register", json=body, headers={"X-Kiosk-Token": device.token})
    assert r.status_code == 200
    assert r.json() == {"device_token": device.token, "device_name": device.name, "status": "active"}

    r = await client.post("/api/kiosk/register", json=body)
    data = r.json()
    assert data["device_token"] != device.token
    assert data["status"] == "pending"
    async with AsyncSessionLocal() as db:
        d = await db.get(Device, device.id)
    assert d.token == data["device_token"] and d.status == "pending"
    # 古いトークンはもう使えない
    assert (await client.get("/api/kiosk/status", headers={"X-Kiosk-Token": device.token})).status_code == 401


async def test_初回登録は従来どおり承認待ちで作られる(client, tenant):
    r = await client.post("/api/kiosk/register", json={"tenant_slug": tenant.slug, "hardware_id": "new-hw"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


# ── S4: メールアドレスの重複・予約語 ───────────────────────────────────────────

async def test_登録は既存のメールアドレスを大文字小文字を問わず拒否する(client, tenant):
    await _user(tenant.id, email="Taken@Example.test")
    r = await client.post("/api/auth/register", json={
        "tenant_name": "新規", "tenant_slug": "brand-new", "email": "taken@example.TEST", "password": "password123",
    })
    assert r.status_code == 409
    assert "既に登録" in r.json()["detail"]


async def test_予約語のスラッグは登録できない(client):
    r = await client.post("/api/auth/register", json={
        "tenant_name": "x", "tenant_slug": "admin", "email": "a@b.test", "password": "password123",
    })
    assert r.status_code == 422


async def test_代理店の顧客作成も既存メールを拒否する(client, tenant):
    async with AsyncSessionLocal() as db:
        reseller_t = Tenant(id=str(uuid.uuid4()), slug="agency", name="代理店", is_reseller=True)
        db.add(reseller_t)
        await db.commit()
    reseller = await _user(reseller_t.id, "reseller")
    await _user(tenant.id, email="dup@example.test")
    r = await client.post("/api/reseller/customers", headers=_bearer(_token(reseller)), json={
        "name": "顧客", "slug": "customer-a", "admin_email": "DUP@example.test", "admin_password": "password123",
    })
    assert r.status_code == 409
    r = await client.post("/api/reseller/customers", headers=_bearer(_token(reseller)), json={
        "name": "顧客", "slug": "kiosk", "admin_email": "new@example.test", "admin_password": "password123",
    })
    assert r.status_code == 422


async def test_重複したメールでもログインは500にならず古い方に決まる(client, tenant):
    old = await _user(tenant.id, email="same@example.test", password="old-password",
                      created_at=datetime(2025, 1, 1))
    await _user(tenant.id, email="same@example.test", password="new-password",
                created_at=datetime(2026, 1, 1))
    r = await client.post("/api/auth/login", json={"email": "same@example.test", "password": "old-password"})
    assert r.status_code == 200
    assert jwt.get_unverified_claims(r.json()["access_token"])["sub"] == old.id
    # 大文字小文字が違っても同じアカウントに決まる
    r = await client.post("/api/auth/login", json={"email": "SAME@example.test", "password": "old-password"})
    assert r.status_code == 200


async def test_デモの付け替えは別テナントのユーザーを動かさない(tenant):
    from app.main import _seed_demo_master_data

    async with AsyncSessionLocal() as db:
        demo = Tenant(id=str(uuid.uuid4()), slug="demo2", name="デモ")
        db.add(demo)
        await db.commit()
    other = await _user(tenant.id, "staff", email="demo2@ranasoft.co.jp")
    own = await _user(demo.id, "staff", email="demo2@ranasoft.co.jp")

    await _seed_demo_master_data()

    async with AsyncSessionLocal() as db:
        moved = await db.get(User, other.id)
        fixed = await db.get(User, own.id)
    assert moved.tenant_id == tenant.id and moved.role == "staff"
    assert fixed.tenant_id == demo.id and fixed.role == "admin"


# ── S7: 既定の秘密設定 ────────────────────────────────────────────────────────

def test_SQLite以外で既定の鍵のままなら起動を止める():
    pg = "postgresql+asyncpg://u:p@h/db"
    default = Settings(_env_file=None, database_url=pg,
                       jwt_secret_key=Settings.model_fields["jwt_secret_key"].default,
                       encryption_key=Settings.model_fields["encryption_key"].default)
    assert insecure_default_secrets(default) == ["JWT_SECRET_KEY", "ENCRYPTION_KEY"]
    ok = Settings(_env_file=None, database_url=pg, jwt_secret_key="x" * 40, encryption_key="y" * 44)
    assert insecure_default_secrets(ok) == []
    example = Settings(_env_file=None, database_url=pg, jwt_secret_key="x" * 40,
                       encryption_key="change-me-generate-with-Fernet")
    assert insecure_default_secrets(example) == ["ENCRYPTION_KEY"]
    sqlite = Settings(_env_file=None, database_url="sqlite+aiosqlite:///./x.db",
                      jwt_secret_key=Settings.model_fields["jwt_secret_key"].default)
    assert insecure_default_secrets(sqlite) == []


def test_起動時の確認は既定値なら例外(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "insecure_default_secrets", lambda s: ["JWT_SECRET_KEY"])
    with pytest.raises(RuntimeError):
        main._refuse_insecure_defaults()


# ── S8: 権限 ──────────────────────────────────────────────────────────────────

async def test_スタッフは管理者向けの操作ができないが日常の対応はできる(client, tenant, device):
    staff = await _user(tenant.id, "staff")
    h = _bearer(_token(staff))
    log = await add_reception(tenant.id, "田中")

    assert (await client.request("DELETE", "/api/reception/bulk", json={"ids": [log.id]}, headers=h)).status_code == 403
    assert (await client.delete(f"/api/reception/{log.id}", headers=h)).status_code == 403
    assert (await client.get("/api/reception/export.csv", headers=h)).status_code == 403
    assert (await client.get("/api/reception/contacts.csv", headers=h)).status_code == 403
    assert (await client.post(f"/api/devices/{device.id}/approve", headers=h)).status_code == 403
    assert (await client.delete(f"/api/devices/{device.id}", headers=h)).status_code == 403
    assert (await client.patch("/api/settings", json={"name": "x"}, headers=h)).status_code == 403
    assert (await client.post("/api/content/playlists", json={"name": "p"}, headers=h)).status_code == 403
    assert (await client.post("/api/meeting-rooms", json={"name": "r"}, headers=h)).status_code == 403

    # 閲覧・受付への対応はできる
    assert (await client.get("/api/reception", headers=h)).status_code == 200
    assert (await client.get("/api/devices", headers=h)).status_code == 200
    assert (await client.patch(f"/api/reception/{log.id}", json={"staff_notes": "メモ"}, headers=h)).status_code == 200


async def test_管理者は管理者向けの操作ができる(client, tenant):
    admin = await _user(tenant.id, "admin")
    h = _bearer(_token(admin))
    log = await add_reception(tenant.id, "田中")
    assert (await client.request("DELETE", "/api/reception/bulk", json={"ids": [log.id]}, headers=h)).json() == {"deleted": 1}
    r = await client.get("/api/reception/export.csv", headers=h)
    assert r.status_code == 200


async def test_代理ログインのトークンでも管理者向けの操作ができる(client, tenant):
    admin = await _user(tenant.id, "admin")
    r = await client.patch("/api/settings", json={"name": "新しい名前"},
                           headers=_bearer(create_proxy_access_token(tenant.id, admin.id)))
    assert r.status_code == 200


async def test_superadminもユーザー管理ができる(client, tenant):
    sa = await _user(tenant.id, "superadmin")
    r = await client.post("/api/users", headers=_bearer(_token(sa)),
                          json={"email": "new-staff@example.test", "password": "password123", "role": "staff"})
    assert r.status_code == 201
    r = await client.post("/api/users", headers=_bearer(_token(sa)),
                          json={"email": "NEW-STAFF@example.test", "password": "password123", "role": "staff"})
    assert r.status_code == 409


# ── S9: 通知文面の無害化 ──────────────────────────────────────────────────────

def test_Slackの受付文面は来訪者の入力を無害化する():
    from app.services.slack import SlackNotifier

    text = SlackNotifier.build_reception_message(
        visitor_name="<!channel> 太郎", company="A&B <https://evil.test|ここ>", host_name="田中",
    )
    assert "<!channel>" not in text and "&lt;!channel&gt;" in text
    assert "A&amp;B &lt;https://evil.test|ここ&gt;" in text


def test_配達の文面は送り先ごとに無害化する():
    from app.api.kiosk import _DeliveryText, _dropoff_text

    t = _DeliveryText(lambda esc: _dropoff_text(esc, "<!here>[To:1]", "1234", "端末&1"))
    assert "&lt;!here&gt;" in t.slack and "端末&amp;1" in t.slack
    assert "［To:1］" in t.chatwork and "[To:1]" not in t.chatwork
    assert "<!here>[To:1]" in t.plain


async def test_応答済みの追い通知も送り先ごとに無害化する(tenant, monkeypatch):
    from app.services import chatwork, reception_notify
    from app.services.slack import SlackNotifier

    await set_notification_setting(tenant.id, "slack", {"bot_access_token": "xoxb", "channel_id": "C1"})
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "cw", "room_id": "9"})
    async with AsyncSessionLocal() as db:
        log = ReceptionLog(id=str(uuid.uuid4()), tenant_id=tenant.id, visitor_name="<b>花子",
                           company="[info]社", method="form", state="accepted",
                           decided_by_name="<@U1>", staff="田中")
        db.add(log)
        await db.commit()
    sent: dict[str, str] = {}

    async def fake_slack(config, text, blocks=None):
        sent["slack"] = text
        return True

    async def fake_cw(token, room, text):
        sent["chatwork"] = text
        return True

    monkeypatch.setattr(SlackNotifier, "send_to_config", staticmethod(fake_slack))
    monkeypatch.setattr(chatwork, "send_message", fake_cw)
    from conftest import add_route  # type: ignore[import-not-found]
    await add_route(tenant.id, "田中", config={"chatwork_room_id": "9"})
    await reception_notify.fire_decision_notifications(tenant.id, log.id)
    assert "&lt;@U1&gt;" in sent["slack"] and "&lt;b&gt;花子" in sent["slack"]
    assert "［info］社" in sent["chatwork"] and "[info]" not in sent["chatwork"]


# ── S10: ログイン失敗の回数制限 / 接続元 IP ───────────────────────────────────

async def test_同じIDで8回失敗すると正しいパスワードでも止める(client, tenant):
    await _user(tenant.id, email="lock@example.test", password="right-password")
    for _ in range(login_throttle.MAX_FAILURES):
        r = await client.post("/api/auth/login", json={"email": "lock@example.test", "password": "wrong"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": " LOCK@example.test ", "password": "right-password"})
    assert r.status_code == 429
    assert "一時的" in r.json()["detail"]


async def test_成功すると失敗の回数は数え直す(client, tenant):
    await _user(tenant.id, email="ok@example.test", password="right-password")
    for _ in range(login_throttle.MAX_FAILURES - 1):
        await client.post("/api/auth/login", json={"email": "ok@example.test", "password": "wrong"})
    assert (await client.post("/api/auth/login", json={"email": "ok@example.test", "password": "right-password"})).status_code == 200
    for _ in range(login_throttle.MAX_FAILURES - 1):
        await client.post("/api/auth/login", json={"email": "ok@example.test", "password": "wrong"})
    assert (await client.post("/api/auth/login", json={"email": "ok@example.test", "password": "right-password"})).status_code == 200


def test_回数の記録は上限を超えて増えない(monkeypatch):
    monkeypatch.setattr(login_throttle, "_MAX_KEYS", 50)
    for i in range(200):
        login_throttle.record_failure(f"email:{i}@x")
    assert len(login_throttle._entries) <= 50


def test_接続元IPは転送ヘッダの右から最初の公開アドレス():
    from starlette.requests import Request
    from app.services.ratelimit import client_ip

    def req(xff: str | None):
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "headers": headers, "client": ("10.1.2.3", 1234)})

    assert client_ip(req("1.1.1.1, 52.10.20.30")) == "52.10.20.30"
    assert client_ip(req("8.8.8.8, 52.10.20.30, 10.0.0.2")) == "52.10.20.30"
    assert client_ip(req("10.0.0.2")) == "10.1.2.3"
    assert client_ip(req(None)) == "10.1.2.3"


# ── S11: 外へ送る URL ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://hooks.example.test/x",           # https ではない
    "https://10.0.0.1/x",                    # IP 直書き
    "https://[::1]/x",
    "https://localhost/x",
    "https://internal.example.test/x",       # 名前解決でプライベート
    "https://metadata.example.test/x",       # リンクローカル
    "https://loop.example.test/x",
    "https://mapped.example.test/x",         # IPv4 射影の IPv6
    "ftp://hooks.example.test/x",
])
async def test_内側の宛先は受け付けない(url):
    with pytest.raises(url_safety.UnsafeUrlError):
        await url_safety.validate_public_url(url)


async def test_公開された宛先は受け付ける():
    await url_safety.validate_public_url("https://hooks.example.test/x")


async def test_Webhookの保存は内側の宛先を400で拒否する(client, tenant):
    admin = await _user(tenant.id)
    h = _bearer(_token(admin))
    r = await client.put("/api/notifications/settings/webhook", json={"webhook_url": "https://internal.example.test/h"}, headers=h)
    assert r.status_code == 400
    r = await client.put("/api/notifications/settings/webhook_delivery", json={"webhook_url": "https://10.0.0.1/h"}, headers=h)
    assert r.status_code == 400
    r = await client.put("/api/notifications/staff-routes", headers=h, json={
        "staff_name": "田中", "webhook_url": "https://loop.example.test/h",
    })
    assert r.status_code == 400


async def test_送る直前にも宛先を確かめる(monkeypatch):
    from app.api import kiosk
    from app.services import reception_notify

    called = []

    class Boom:
        def __init__(self, *a, **k):
            called.append(k)

        async def __aenter__(self):
            raise AssertionError("送信してはいけない")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(kiosk.httpx, "AsyncClient", Boom)
    assert await kiosk._send_webhook("https://internal.example.test/h", {}) is False
    assert await reception_notify._post_webhook("https://internal.example.test/h", {}) is False
    assert called == []


async def test_プッシュ購読は既知の配信サービスだけ(client, tenant):
    admin = await _user(tenant.id)
    h = _bearer(_token(admin))
    for bad in ("https://push.example/1", "http://fcm.googleapis.com/x", "https://fcm.googleapis.com.evil.test/x",
                "https://evilpush.apple.com/x"):
        r = await client.post("/api/notifications/push/subscribe", headers=h,
                              json={"endpoint": bad, "p256dh": "k", "auth": "a"})
        assert r.status_code == 400, bad
    for good in ("https://fcm.googleapis.com/fcm/send/1", "https://web.push.apple.com/Q1",
                 "https://updates.push.services.mozilla.com/wpush/v2/1",
                 "https://wns2-par02p.notify.windows.com/w/?token=1"):
        r = await client.post("/api/notifications/push/subscribe", headers=h,
                              json={"endpoint": good, "p256dh": "k", "auth": "a"})
        assert r.status_code == 201, good


async def test_別テナントで再登録した購読はテナントごと付け替わる(client, tenant):
    first = await _user(tenant.id)
    async with AsyncSessionLocal() as db:
        other_t = Tenant(id=str(uuid.uuid4()), slug="other", name="別")
        db.add(other_t)
        await db.commit()
    second = await _user(other_t.id)
    body = {"endpoint": "https://fcm.googleapis.com/fcm/send/same", "p256dh": "k", "auth": "a"}
    await client.post("/api/notifications/push/subscribe", headers=_bearer(_token(first)), json=body)
    await client.post("/api/notifications/push/subscribe", headers=_bearer(_token(second)), json=body)
    async with AsyncSessionLocal() as db:
        subs = (await db.execute(select(PushSubscription))).scalars().all()
    assert len(subs) == 1
    assert subs[0].tenant_id == other_t.id and subs[0].user_id == second.id


async def test_プッシュのテスト送信は配信側の応答本文を返さない(client, tenant, monkeypatch):
    from app.api import push as push_api

    admin = await _user(tenant.id)
    async with AsyncSessionLocal() as db:
        db.add(PushSubscription(id=str(uuid.uuid4()), tenant_id=tenant.id, user_id=admin.id,
                                endpoint="https://fcm.googleapis.com/fcm/send/x", p256dh="k", auth_key="a"))
        await db.commit()

    async def fake_send(**kw):
        return False, "HTTP 400: secret upstream body"

    monkeypatch.setattr(push_api, "send_push", fake_send)
    r = await client.post("/api/notifications/push/test", headers=_bearer(_token(admin)))
    assert r.status_code == 502
    assert "secret upstream body" not in r.text


# ── S12: 通知設定の取得 ──────────────────────────────────────────────────────

async def test_通知設定はWebhookを伏せ_知らない種類は返さない(client, tenant):
    admin = await _user(tenant.id)
    h = _bearer(_token(admin))
    await set_notification_setting(tenant.id, "webhook", {"webhook_url": "https://hooks.example.test/secret"})
    await set_notification_setting(tenant.id, "webhook_delivery", {"webhook_url": "https://hooks.example.test/dl"})
    await set_notification_setting(tenant.id, "vapid", {"private_key": "should-not-leak"})
    await set_notification_setting(tenant.id, "push_delivery", {"enabled": False})
    data = (await client.get("/api/notifications/settings", headers=h)).json()
    assert data["webhook"]["webhook_url"] == "***"
    assert data["webhook_delivery"]["webhook_url"] == "***"
    assert "vapid" not in data
    assert data["push_delivery"] == {"enabled": False}

    # 伏せ字のまま保存しても実際の URL は変わらない
    r = await client.put("/api/notifications/settings/webhook", json={"webhook_url": "***"}, headers=h)
    assert r.status_code == 200
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant.id, NotificationSetting.type == "webhook"))).scalar_one()
    assert decrypt_dict(row.config_json)["webhook_url"] == "https://hooks.example.test/secret"


# ── S13: 代理店の代理ログイン ─────────────────────────────────────────────────

async def test_代理店の代理ログインは15分のみでrefreshを出さない(client, tenant):
    async with AsyncSessionLocal() as db:
        reseller_t = Tenant(id=str(uuid.uuid4()), slug="agency2", name="代理店", is_reseller=True)
        db.add(reseller_t)
        await db.commit()
        t = await db.get(Tenant, tenant.id)
        t.reseller_id = reseller_t.id
        await db.commit()
    reseller = await _user(reseller_t.id, "reseller")
    await _user(tenant.id, "admin")
    r = await client.post(f"/api/reseller/customers/{tenant.id}/proxy-login", headers=_bearer(_token(reseller)))
    assert r.status_code == 200
    data = r.json()
    assert data["refresh_token"] == "" and data["tenant_slug"] == tenant.slug
    claims = jwt.get_unverified_claims(data["access_token"])
    assert claims["proxy"] is True
    assert claims["exp"] - claims["iat"] <= 15 * 60


# ── S14: パスワード変更で古いトークンを無効にする ────────────────────────────

async def test_自分のパスワード変更で古いトークンは使えず新しいトークンは使える(client, tenant):
    u = await _user(tenant.id, email="pw@example.test", password="old-password")
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    old_access = create_access_token(tenant.id, u.id, "admin", issued_at=past)
    old_refresh = create_refresh_token(tenant.id, u.id, issued_at=past)

    r = await client.patch("/api/users/me/password", headers=_bearer(old_access),
                           json={"current_password": "old-password", "new_password": "new-password-1"})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"] and data["refresh_token"]

    assert (await client.get("/api/users/me", headers=_bearer(old_access))).status_code == 401
    assert (await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})).status_code == 401
    assert (await client.get("/api/users/me", headers=_bearer(data["access_token"]))).status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})).status_code == 200


async def test_管理者によるパスワード再設定で本人の古いトークンは使えない(client, tenant):
    admin = await _user(tenant.id, "admin")
    target = await _user(tenant.id, "staff")
    old = create_access_token(tenant.id, target.id, "staff",
                              issued_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    r = await client.post(f"/api/users/{target.id}/reset-password", headers=_bearer(_token(admin)),
                          json={"new_password": "reset-password"})
    assert r.status_code == 200
    assert (await client.get("/api/users/me", headers=_bearer(old))).status_code == 401


async def test_iatの無い古い形式のトークンはパスワード変更後だけ拒否する(client, tenant):
    u = await _user(tenant.id)
    legacy = jwt.encode(
        {"sub": u.id, "tenant_id": tenant.id, "role": "admin", "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    assert (await client.get("/api/users/me", headers=_bearer(legacy))).status_code == 200
    async with AsyncSessionLocal() as db:
        row = await db.get(User, u.id)
        row.password_changed_at = datetime(2026, 1, 1)
        await db.commit()
    assert (await client.get("/api/users/me", headers=_bearer(legacy))).status_code == 401


async def test_代理ログイン中はパスワードを変更できない(client, tenant):
    u = await _user(tenant.id, password="old-password")
    r = await client.patch("/api/users/me/password", headers=_bearer(create_proxy_access_token(tenant.id, u.id)),
                           json={"current_password": "old-password", "new_password": "new-password-1"})
    assert r.status_code == 403
    assert "代理ログイン" in r.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, u.id)).password_changed_at is None


async def test_代理ログイン中は管理者のパスワードを再設定できないがスタッフはできる(client, tenant):
    admin = await _user(tenant.id, "admin")
    other_admin = await _user(tenant.id, "admin")
    staff = await _user(tenant.id, "staff")
    h = _bearer(create_proxy_access_token(tenant.id, admin.id))
    for target in (admin, other_admin):
        r = await client.post(f"/api/users/{target.id}/reset-password", headers=h,
                              json={"new_password": "reset-password"})
        assert r.status_code == 403
    r = await client.post(f"/api/users/{staff.id}/reset-password", headers=h,
                          json={"new_password": "reset-password"})
    assert r.status_code == 200


async def test_運営の代理ログインのトークンはパスワード変更後でも使える(client, tenant, operator_headers):
    admin = await _user(tenant.id, "admin")
    async with AsyncSessionLocal() as db:
        row = await db.get(User, admin.id)
        row.password_changed_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None, microsecond=0)
        await db.commit()
    r = await client.post(f"/api/operator/tenants/{tenant.id}/proxy-login", headers=operator_headers)
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert jwt.get_unverified_claims(token)["proxy"] is True
    assert (await client.get("/api/users/me", headers=_bearer(token))).status_code == 200


# ── S15: 閲覧専用アカウント ──────────────────────────────────────────────────

async def test_閲覧専用はSlack連携を始められずSSEのチケットは取れる(client, tenant):
    ro = await _user(tenant.id, "admin")
    h = _bearer(_token(ro, readonly=True))
    r = await client.get("/api/notifications/slack/oauth/url", headers=h)
    assert r.status_code == 403
    r = await client.post("/api/events/ticket", headers=h)
    assert r.status_code == 200
    assert r.json()["expires_in"] == 60
    # 他の書き込みは従来どおり止まる
    assert (await client.patch("/api/settings", json={"name": "x"}, headers=h)).status_code == 403
    # 通常のアカウントは Slack 連携を始められる(機能が無効なら enabled:false が返る)
    admin = await _user(tenant.id, "admin")
    assert (await client.get("/api/notifications/slack/oauth/url", headers=_bearer(_token(admin)))).status_code == 200


# ── S16: CSV ──────────────────────────────────────────────────────────────────

def test_CSVの数式になるセルは無害化する():
    from app.services.csv_safe import safe_cell, safe_row

    assert safe_row(["=1+1", "+81", "-x", "@SUM", "\tA", "\rB", "普通", 3, None]) == [
        "'=1+1", "'+81", "'-x", "'@SUM", "'\tA", "'\rB", "普通", 3, None,
    ]
    assert safe_cell("a=b") == "a=b"


async def test_受付ログCSVで来訪者の入力が数式にならない(client, tenant):
    admin = await _user(tenant.id)
    async with AsyncSessionLocal() as db:
        db.add(ReceptionLog(id=str(uuid.uuid4()), tenant_id=tenant.id, visitor_name="=HYPERLINK(1)",
                            method="form", state="received"))
        await db.commit()
    r = await client.get("/api/reception/export.csv", headers=_bearer(_token(admin)))
    assert "'=HYPERLINK(1)" in r.text


# ── S17: メール送信の回数 ────────────────────────────────────────────────────

def test_メールは1時間30通まで():
    from fastapi import HTTPException

    for _ in range(mail_quota.LIMIT_PER_HOUR):
        mail_quota.consume("t1")
    with pytest.raises(HTTPException) as e:
        mail_quota.consume("t1")
    assert e.value.status_code == 429
    mail_quota.consume("t2")  # 別テナントは別枠


# ── S20: SSE チケット ────────────────────────────────────────────────────────

async def test_SSEはチケットで認証しアクセストークンをチケットとしては使えない(tenant):
    from fastapi import HTTPException
    from app.api import events

    u = await _user(tenant.id)
    assert await events._resolve_ticket(create_sse_ticket(tenant.id, u.id)) == tenant.id
    with pytest.raises(HTTPException):
        await events._resolve_ticket(_token(u))
    # 移行期間中は従来の ?token= も受ける
    assert await events._resolve_tenant_id(_token(u)) == tenant.id
    # チケットは access トークンの代わりにはならない
    with pytest.raises(HTTPException):
        await events._resolve_tenant_id(create_sse_ticket(tenant.id, u.id))


async def test_SSEのチケット発行(client, tenant):
    u = await _user(tenant.id, "staff")
    r = await client.post("/api/events/ticket", headers=_bearer(_token(u)))
    assert r.status_code == 200
    claims = jwt.get_unverified_claims(r.json()["ticket"])
    assert claims["type"] == "sse" and claims["sub"] == u.id
    assert claims["exp"] - claims["iat"] <= 60


# ── N5: 保存先 URL ───────────────────────────────────────────────────────────

def test_保存先URLは区切りの斜線まで比べる(monkeypatch):
    from app.services import storage

    monkeypatch.setattr(settings, "storage_public_url", "https://cdn.example.test")
    assert storage.is_own_storage_url("https://cdn.example.test/t/1/a.png")
    assert not storage.is_own_storage_url("https://cdn.example.test.evil/a.png")
    assert not storage.is_own_storage_url("https://cdn.example.testx/a.png")


async def test_会議室の地図は保存先のURLだけ(client, tenant):
    admin = await _user(tenant.id)
    h = _bearer(_token(admin))
    base = settings.storage_public_url.rstrip("/")
    r = await client.post("/api/meeting-rooms", headers=h, json={"name": "A", "map_image_url": "https://elsewhere.test/m.png"})
    assert r.status_code == 422
    r = await client.post("/api/meeting-rooms", headers=h, json={"name": "A", "map_image_url": f"{base}/t/m.png"})
    assert r.status_code == 201
    r = await client.post("/api/content/media", headers=h, json={
        "media_id": str(uuid.uuid4()), "filename": "a.png", "mime_type": "image/png",
        "url": base + ".evil/a.png",
    })
    assert r.status_code == 422


async def test_未使用のアップロードAPIは無い(client, tenant):
    admin = await _user(tenant.id)
    r = await client.post("/api/content/media/upload", headers=_bearer(_token(admin)))
    assert r.status_code in (404, 405)
