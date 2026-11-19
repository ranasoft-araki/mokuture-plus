"""ユーザー招待(複数アドレスの一括招待・招待リンクからの登録)。

SMTP へは出さない。`email.send_email` を差し替え、送った宛先と本文だけを記録する。
"""
from __future__ import annotations

import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.user import User, UserInvitation
from app.services import mail_quota
from app.services.auth import create_access_token
from app.services.timeutil import utcnow_naive


@pytest.fixture
def sent(monkeypatch):
    """SMTP を有効にしたことにして、送信を記録だけにする。`fail` に入れた宛先は失敗させる。"""
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_username", "noreply@example.test")
    monkeypatch.setattr(settings, "smtp_password", "x")
    box: dict = {"mails": [], "fail": set()}

    async def fake_send(to, subject, html, text, **kw):
        if to in box["fail"]:
            return False, "550 rejected"
        box["mails"].append({"to": to, "subject": subject, "text": text, "html": html})
        return True, ""

    from app.services import email as email_service
    monkeypatch.setattr(email_service, "send_email", fake_send)
    return box


async def _user(tenant_id: str, email: str, role: str = "admin") -> User:
    async with AsyncSessionLocal() as db:
        u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=email, hashed_password="x", role=role, name="招待する人")
        db.add(u)
        await db.commit()
        return u


def _auth(u: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(u.tenant_id, u.id, u.role)}"}


def _token_from(mail: dict) -> str:
    m = re.search(r"/invite#token=([A-Za-z0-9_\-]+)", mail["text"])
    assert m, mail["text"]
    return m.group(1)


async def test_まとめて招待し_形式誤り_重複_登録済みは送らない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await _user(tenant.id, "Taken@Example.test", role="staff")
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={
        "emails": ["a@example.test", "Ａ＠ｅｘａｍｐｌｅ．ｔｅｓｔ", "<b@example.test>", "taken@example.test", "not-an-email@", "mailto:c@example.test"],
        "role": "staff",
    })
    assert r.status_code == 200, r.text
    st = {x["email"]: x["status"] for x in r.json()["results"]}
    assert st["a@example.test"] == "sent"
    assert st["A@example.test"] == "duplicate"  # 全角は半角へ寄せ、大文字小文字は区別しない
    assert st["b@example.test"] == "sent"
    assert st["taken@example.test"] == "already_user"
    assert st["not-an-email@"] == "invalid"
    assert st["c@example.test"] == "sent"
    assert sorted(m["to"] for m in sent["mails"]) == ["a@example.test", "b@example.test", "c@example.test"]
    assert "【実証実験テナント】" in sent["mails"][0]["subject"]
    assert "/pilot/invite#token=" in sent["mails"][0]["text"]
    assert mail_quota.remaining(tenant.id) == mail_quota.LIMIT_PER_HOUR - 3

    lst = (await client.get("/api/users/invitations", headers=_auth(admin))).json()
    assert lst["smtp_enabled"] is True
    assert sorted(i["email"] for i in lst["invitations"]) == ["a@example.test", "b@example.test", "c@example.test"]
    assert all(i["expires_at"].endswith("Z") and not i["expired"] for i in lst["invitations"])


@pytest.mark.parametrize("raw", [
    "E-mail:taro@example.jp", "メール：taro@example.jp", "taro@example.jp（山田）",
    "taro@example.jpまで", "taro@example.jp.", "“taro@example.jp”",
])
def test_語の中からアドレスだけを取り出し_届く宛先とログインIDをそろえる(raw):
    from app.services.invitations import is_valid, normalize

    assert normalize(raw) == "taro@example.jp"
    assert is_valid(normalize(raw))


@pytest.mark.parametrize("bad", ["taro@example", "taro@@example.jp", "たろう@example.jp", "taro@-x.jp", "a..b@x.jp"])
def test_崩れたアドレスは形式の誤り(bad):
    from app.services.invitations import is_valid, normalize

    assert not is_valid(normalize(bad))


async def test_前置きつきでも別テナントの登録済みを見逃さない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    async with AsyncSessionLocal() as db:
        other = Tenant(id=str(uuid.uuid4()), slug="other", name="別テナント")
        db.add(other)
        await db.commit()
    await _user(other.id, "taro@example.jp", role="staff")
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["E-mail:Taro@example.jp"]})
    assert r.json()["results"] == [{"email": "Taro@example.jp", "status": "already_user"}]
    assert sent["mails"] == []


async def test_トークンはDBに平文で残らない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    token = _token_from(sent["mails"][0])
    async with AsyncSessionLocal() as db:
        inv = (await db.execute(select(UserInvitation))).scalar_one()
    assert inv.token_hash != token and len(inv.token_hash) == 64


async def test_上限を超える件数は1通も送らず429(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    mail_quota.consume(tenant.id, mail_quota.LIMIT_PER_HOUR - 2)
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={
        "emails": ["a@example.test", "b@example.test", "c@example.test"],
    })
    assert r.status_code == 429
    assert "あと2通" in r.json()["detail"]
    assert sent["mails"] == []
    assert mail_quota.remaining(tenant.id) == 2


async def test_送れなかった宛先は招待を作らない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    sent["fail"].add("bad@example.test")
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={
        "emails": ["ok@example.test", "bad@example.test"],
    })
    st = {x["email"]: x["status"] for x in r.json()["results"]}
    assert st == {"ok@example.test": "sent", "bad@example.test": "failed"}
    async with AsyncSessionLocal() as db:
        emails = [i.email for i in (await db.execute(select(UserInvitation))).scalars()]
    assert emails == ["ok@example.test"]


async def test_招待し直すとリンクを作り直し前のリンクは使えない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    old = _token_from(sent["mails"][0])
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["A@example.test"], "role": "admin"})
    assert r.json()["results"][0]["status"] == "resent"
    new = _token_from(sent["mails"][1])
    assert new != old
    async with AsyncSessionLocal() as db:
        invs = list((await db.execute(select(UserInvitation))).scalars())
    assert len(invs) == 1 and invs[0].role == "admin"
    assert (await client.post("/api/auth/invitations/lookup", json={"token": old})).status_code == 404
    assert (await client.post("/api/auth/invitations/lookup", json={"token": new})).status_code == 200


async def test_リンクから登録してログインでき_同じリンクは2度使えない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["new@example.test"], "role": "staff"})
    token = _token_from(sent["mails"][0])

    info = await client.post("/api/auth/invitations/lookup", json={"token": token})
    assert info.status_code == 200
    assert info.json()["email"] == "new@example.test"
    assert info.json()["tenant_slug"] == "pilot"

    short = await client.post("/api/auth/invitations/accept", json={"token": token, "password": "short"})
    assert short.status_code == 422

    r = await client.post("/api/auth/invitations/accept", json={"token": token, "password": "password123", "name": "新人"})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_slug"] == "pilot" and r.json()["role"] == "staff"

    login = await client.post("/api/auth/login", json={"email": "new@example.test", "password": "password123"})
    assert login.status_code == 200

    again = await client.post("/api/auth/invitations/accept", json={"token": token, "password": "password123"})
    assert again.status_code == 410
    lst = (await client.get("/api/users/invitations", headers=_auth(admin))).json()
    assert lst["invitations"] == []  # 登録済みは招待中の一覧から消える


async def test_期限切れのリンクは使えない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    token = _token_from(sent["mails"][0])
    async with AsyncSessionLocal() as db:
        inv = (await db.execute(select(UserInvitation))).scalar_one()
        inv.expires_at = utcnow_naive() - timedelta(minutes=1)
        await db.commit()
    assert (await client.post("/api/auth/invitations/lookup", json={"token": token})).status_code == 410
    assert (await client.post("/api/auth/invitations/accept", json={"token": token, "password": "password123"})).status_code == 410
    lst = (await client.get("/api/users/invitations", headers=_auth(admin))).json()
    assert lst["invitations"][0]["expired"] is True


async def test_招待後に別経路で登録されたアドレスは409(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    token = _token_from(sent["mails"][0])
    await _user(tenant.id, "A@EXAMPLE.TEST", role="staff")
    r = await client.post("/api/auth/invitations/accept", json={"token": token, "password": "password123"})
    assert r.status_code == 409


async def test_スタッフは招待できず_別テナントの招待は見えない(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    staff = await _user(tenant.id, "staff@example.test", role="staff")
    assert (await client.post("/api/users/invitations", headers=_auth(staff), json={"emails": ["a@example.test"]})).status_code == 403
    assert (await client.get("/api/users/invitations", headers=_auth(staff))).status_code == 403

    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    async with AsyncSessionLocal() as db:
        other = Tenant(id=str(uuid.uuid4()), slug="other", name="別テナント")
        db.add(other)
        await db.commit()
        inv_id = (await db.execute(select(UserInvitation.id))).scalar_one()
    other_admin = await _user(other.id, "other@example.test")
    assert (await client.get("/api/users/invitations", headers=_auth(other_admin))).json()["invitations"] == []
    assert (await client.delete(f"/api/users/invitations/{inv_id}", headers=_auth(other_admin))).status_code == 404
    assert (await client.post(f"/api/users/invitations/{inv_id}/resend", headers=_auth(other_admin))).status_code == 404


async def test_取り消すとリンクは使えず_送り直すと新しいリンクになる(client, tenant, sent):
    admin = await _user(tenant.id, "boss@example.test")
    await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test", "b@example.test"]})
    tokens = {m["to"]: _token_from(m) for m in sent["mails"]}
    lst = (await client.get("/api/users/invitations", headers=_auth(admin))).json()["invitations"]
    ids = {i["email"]: i["id"] for i in lst}

    assert (await client.delete(f"/api/users/invitations/{ids['a@example.test']}", headers=_auth(admin))).status_code == 204
    assert (await client.post("/api/auth/invitations/lookup", json={"token": tokens["a@example.test"]})).status_code == 404

    r = await client.post(f"/api/users/invitations/{ids['b@example.test']}/resend", headers=_auth(admin))
    assert r.status_code == 200
    assert (await client.post("/api/auth/invitations/lookup", json={"token": tokens["b@example.test"]})).status_code == 404
    assert (await client.post("/api/auth/invitations/lookup", json={"token": _token_from(sent["mails"][-1])})).status_code == 200


async def test_SMTP未設定なら503で何も作らない(client, tenant, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")  # 開発機の backend/.env に SMTP があっても未設定扱いにする
    admin = await _user(tenant.id, "boss@example.test")
    r = await client.post("/api/users/invitations", headers=_auth(admin), json={"emails": ["a@example.test"]})
    assert r.status_code == 503
    assert (await client.get("/api/users/invitations", headers=_auth(admin))).json()["smtp_enabled"] is False


async def test_件名にテナント名の改行を入れない():
    from app.services.invitations import build_email

    subject, text, html = build_email(
        tenant_name="悪い\r\nBcc: x@example.test", brand_color="#123456", inviter="a<b>",
        to="c@example.test", role="staff", url="https://example.test/x/invite#token=abc",
        expires_at=utcnow_naive(),
    )
    assert "\n" not in subject and "\r" not in subject
    assert "a&lt;b&gt;" in html
