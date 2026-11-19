"""遠隔ログイン(運営が、必要なときだけ端末へ SSH で入る)。

確かめるのは「開けと言われた端末だけが、決められた時間だけ、踏み台へつなげる」こと。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.device import Device
from app.models.tunnel import TunnelSession
from app.services import tunnel as svc
from app.services.timeutil import utcnow_naive

DEVICE_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "A" * 48
OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "B" * 48
HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "C" * 48
BASTION_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "D" * 48
SECRET = "bastion-secret-for-tests"
BASTION = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def tunnel_on(monkeypatch):
    monkeypatch.setattr(settings, "tunnel_bastion_host", "bastion.example.test")
    monkeypatch.setattr(settings, "tunnel_bastion_host_key", BASTION_KEY + " bastion")
    monkeypatch.setattr(settings, "tunnel_bastion_secret", SECRET)


async def _poll(client, headers, **body):
    r = await client.post("/api/kiosk/tunnel/poll", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _ready(client, kiosk_headers):
    """端末の常駐が一度聞きに来て、鍵を届けた状態にする。"""
    return await _poll(client, kiosk_headers, state="idle", pubkey=DEVICE_KEY + " kiosk",
                       host_key=HOST_KEY, login_user="pi", reach="ok")


async def _open(client, operator_headers, device, **body):
    body = {"reason": "画面が固まったとの連絡", **body}
    return await client.post(f"/api/operator/tunnel/{device.id}/open", json=body, headers=operator_headers)


async def _age(device_id: str, **delta):
    """片づいていない遠隔ログインの時刻を過去へずらす。"""
    async with AsyncSessionLocal() as db:
        s = await svc.pending_session(db, device_id)
        for name, seconds in delta.items():
            setattr(s, name, getattr(s, name) - timedelta(seconds=seconds))
        await db.commit()


async def test_設定が無ければ機能は無効(client, device, kiosk_headers, operator_headers):
    out = await _poll(client, kiosk_headers, state="idle", pubkey=DEVICE_KEY)
    assert out == {"enabled": False, "want": False, "poll_sec": 600}
    assert (await _open(client, operator_headers, device)).status_code == 503
    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).status_code == 404
    status = (await client.get("/api/operator/tunnel/status", headers=operator_headers)).json()
    assert status["enabled"] is False


async def test_開いてから閉じるまでの流れ(client, device, kiosk_headers, operator_headers, tunnel_on):
    out = await _ready(client, kiosk_headers)
    assert out["want"] is False and out["host"] == "bastion.example.test" and out["host_key"] == BASTION_KEY
    # 開けと言われていない端末の鍵は、踏み台に通させない
    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text == ""

    r = await _open(client, operator_headers, device, minutes=30)
    assert r.status_code == 200, r.text
    session = r.json()
    assert session["state"] == "requested" and session["requested_by"] == "ops@example.test"
    port = session["port"]
    assert port == settings.tunnel_port_base

    keys = (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text
    assert keys == f'restrict,port-forwarding,permitlisten="127.0.0.1:{port}" {DEVICE_KEY}\n'
    assert (await client.get("/api/bastion/active-ports", headers=BASTION)).json() == {"ports": [port]}

    out = await _poll(client, kiosk_headers, state="idle")
    assert out["want"] is True and out["remote_port"] == port and out["poll_sec"] == 5
    assert 29 * 60 < out["ttl_sec"] <= 30 * 60

    await _poll(client, kiosk_headers, state="open")
    status = (await client.get(f"/api/operator/tunnel/status?device_ids={device.id}", headers=operator_headers)).json()
    d = status["devices"][device.id]
    assert d["session"]["state"] == "open" and d["ready"] and d["alive"]
    assert d["login_user"] == "pi" and d["host_key"] == HOST_KEY and d["reach"] == "ok"

    r = await client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)
    assert r.json()["session"]["state"] == "closing"
    # 終了を押した時点で、踏み台は鍵を通さず、転送口も切る対象になる(端末の報告を待たない)
    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text == ""
    assert (await client.get("/api/bastion/active-ports", headers=BASTION)).json() == {"ports": []}

    out = await _poll(client, kiosk_headers, state="open")
    assert out["want"] is False
    out = await _poll(client, kiosk_headers, state="idle")
    assert out["want"] is False and out["poll_sec"] == settings.tunnel_idle_poll_sec

    log = (await client.get("/api/operator/tunnel/sessions", headers=operator_headers)).json()["sessions"]
    assert len(log) == 1 and log[0]["state"] == "closed"
    assert log[0]["close_reason"] == "operator" and log[0]["closed_by"] == "ops@example.test"
    assert log[0]["reason"] == "画面が固まったとの連絡"


async def test_時間切れで自動的に閉じる(client, device, kiosk_headers, operator_headers, tunnel_on):
    await _ready(client, kiosk_headers)
    assert (await _open(client, operator_headers, device, minutes=5)).status_code == 200
    await _poll(client, kiosk_headers, state="open")
    await _age(device.id, expires_at=5 * 60 + 1)

    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text == ""
    out = await _poll(client, kiosk_headers, state="open")
    assert out["want"] is False
    await _poll(client, kiosk_headers, state="idle")
    log = (await client.get("/api/operator/tunnel/sessions", headers=operator_headers)).json()["sessions"]
    assert log[0]["state"] == "closed" and log[0]["close_reason"] == "expired"


async def test_端末が応答しなくても記録は閉じる(client, device, kiosk_headers, operator_headers, tunnel_on):
    await _ready(client, kiosk_headers)
    await _open(client, operator_headers, device)
    await client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)
    await _age(device.id, close_requested_at=svc.CLOSE_CONFIRM_SEC + 1)
    status = (await client.get(f"/api/operator/tunnel/status?device_ids={device.id}", headers=operator_headers)).json()
    assert status["devices"][device.id]["session"] is None
    log = (await client.get("/api/operator/tunnel/sessions", headers=operator_headers)).json()["sessions"]
    assert log[0]["state"] == "closed" and "届きませんでした" in log[0]["error"]
    # 閉じたあとは、もう一度開ける
    assert (await _open(client, operator_headers, device)).status_code == 200


async def test_開いている途中にもう一度押すと延長になる(client, device, kiosk_headers, operator_headers, tunnel_on):
    await _ready(client, kiosk_headers)
    first = (await _open(client, operator_headers, device, minutes=5)).json()
    again = (await _open(client, operator_headers, device, minutes=120, reason="まだ調査中")).json()
    assert again["id"] == first["id"] and again["expires_at"] > first["expires_at"]
    assert "延長" in again["reason"] and "まだ調査中" in again["reason"]
    async with AsyncSessionLocal() as db:
        from sqlalchemy import func, select
        assert (await db.execute(select(func.count()).select_from(TunnelSession))).scalar() == 1


async def test_開けない条件(client, device, kiosk_headers, operator_headers, tunnel_on):
    # 端末側の仕組みが入っていない(鍵が届いていない)
    r = await _open(client, operator_headers, device)
    assert r.status_code == 409 and "準備ができていません" in r.json()["detail"]
    await _ready(client, kiosk_headers)
    assert (await _open(client, operator_headers, device, reason="   ")).status_code == 422
    assert (await _open(client, operator_headers, device, minutes=1)).status_code == 422
    assert (await _open(client, operator_headers, device, minutes=settings.tunnel_max_minutes + 1)).status_code == 422
    assert (await client.post("/api/operator/tunnel/no-such-device/open", json={"reason": "x"},
                              headers=operator_headers)).status_code == 404
    # 承認されていない端末
    async with AsyncSessionLocal() as db:
        d = await db.get(Device, device.id)
        d.status = "pending"
        await db.commit()
    assert (await _open(client, operator_headers, device)).status_code == 409


async def test_運営と踏み台だけが使える(client, device, kiosk_headers, tunnel_on, admin):
    from app.services.auth import create_access_token

    admin_headers = {"Authorization": f"Bearer {create_access_token(tenant_id=admin.tenant_id, user_id=admin.id, role='admin')}"}
    for headers in ({}, admin_headers):
        assert (await client.post(f"/api/operator/tunnel/{device.id}/open", json={"reason": "x"},
                                  headers=headers)).status_code in (401, 403)
        assert (await client.get("/api/operator/tunnel/status", headers=headers)).status_code in (401, 403)
        assert (await client.get("/api/operator/tunnel/sessions", headers=headers)).status_code in (401, 403)
    assert (await client.get("/api/bastion/authorized-keys")).status_code == 401
    assert (await client.get("/api/bastion/authorized-keys", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/api/bastion/active-ports", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.post("/api/kiosk/tunnel/poll", json={}, headers={"X-Kiosk-Token": "nope"})).status_code == 401


async def test_開いている最中は鍵を差し替えられない(client, device, kiosk_headers, operator_headers, tunnel_on):
    await _ready(client, kiosk_headers)
    await _open(client, operator_headers, device)
    await _poll(client, kiosk_headers, state="idle", pubkey=OTHER_KEY)
    assert DEVICE_KEY in (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text
    await client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)
    await _poll(client, kiosk_headers, state="idle")
    # 閉じたあとなら差し替えを受け付ける(端末を入れ直したとき)
    await _poll(client, kiosk_headers, state="idle", pubkey=OTHER_KEY)
    async with AsyncSessionLocal() as db:
        assert (await db.get(Device, device.id)).tunnel_pubkey == OTHER_KEY


@pytest.mark.parametrize("bad", [
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "A" * 47,
    'command="sh" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5' + "A" * 48,
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "A" * 40 + '\npermit=x',
    "",
])
async def test_形の違う鍵は受け付けない(client, device, kiosk_headers, tunnel_on, bad):
    await _poll(client, kiosk_headers, state="idle", pubkey=bad, host_key=bad, login_user="pi; rm -rf /")
    async with AsyncSessionLocal() as db:
        d = await db.get(Device, device.id)
        assert d.tunnel_pubkey is None and d.tunnel_host_key is None and d.tunnel_login_user is None


async def test_転送口は端末ごとに別で変わらない(client, tenant, device, kiosk_headers, operator_headers, tunnel_on):
    import uuid

    async with AsyncSessionLocal() as db:
        other = Device(id=str(uuid.uuid4()), tenant_id=tenant.id, name="受付端末2",
                       token=uuid.uuid4().hex * 2, status="active")
        db.add(other)
        await db.commit()
    await _ready(client, kiosk_headers)
    await _poll(client, {"X-Kiosk-Token": other.token}, state="idle", pubkey=OTHER_KEY, host_key=HOST_KEY)
    a = (await _open(client, operator_headers, device)).json()["port"]
    b = (await _open(client, operator_headers, other)).json()["port"]
    assert a != b
    await client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)
    await _poll(client, kiosk_headers, state="idle")
    assert (await _open(client, operator_headers, device)).json()["port"] == a


async def test_聞きに来ても最終接続は動かさない(client, device, kiosk_headers, tunnel_on):
    """遠隔ログイン用の常駐はキオスク本体とは別。本体が止まっているのに
    「オンライン」に見えてはいけない。"""
    await _ready(client, kiosk_headers)
    async with AsyncSessionLocal() as db:
        d = await db.get(Device, device.id)
        assert d.last_seen_at is None and d.tunnel_seen_at is not None


async def test_つなげなかった理由を運営に見せる(client, device, kiosk_headers, operator_headers, tunnel_on):
    await _ready(client, kiosk_headers)
    await _open(client, operator_headers, device)
    await _poll(client, kiosk_headers, state="connecting", error="connect_timeout", reach="blocked")
    status = (await client.get(f"/api/operator/tunnel/status?device_ids={device.id}", headers=operator_headers)).json()
    d = status["devices"][device.id]
    assert d["session"]["state"] == "requested" and d["session"]["error"] == "connect_timeout"
    assert d["reach"] == "blocked"
    await _poll(client, kiosk_headers, state="open")
    status = (await client.get(f"/api/operator/tunnel/status?device_ids={device.id}", headers=operator_headers)).json()
    assert status["devices"][device.id]["session"]["error"] is None


@pytest.mark.parametrize("order", ["close_first", "poll_first"])
@pytest.mark.parametrize("start", ["requested", "open"])
async def test_終了と端末の問い合わせが重なっても終了は取り消されない(
        client, device, kiosk_headers, operator_headers, tunnel_on, order, start):
    """端末は開いているあいだ 5 秒ごとに聞きに来る。その書き込みが、同時に届いた「終了」を
    上書きすると、画面は終了待ちなのに踏み台は鍵を通し続ける。"""
    import asyncio

    await _ready(client, kiosk_headers)
    assert (await _open(client, operator_headers, device)).status_code == 200
    if start == "open":
        await _poll(client, kiosk_headers, state="open")
    report = "connecting" if start == "open" else "open"   # どちらも端末側が状態を書き換える報告

    def close():
        return client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)

    def poll():
        return client.post("/api/kiosk/tunnel/poll", json={"state": report}, headers=kiosk_headers)

    await asyncio.gather(*([close(), poll()] if order == "close_first" else [poll(), close()]))

    log = (await client.get("/api/operator/tunnel/sessions", headers=operator_headers)).json()["sessions"]
    assert log[0]["state"] in ("closing", "closed") and log[0]["close_reason"] == "operator"
    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text == ""
    assert (await _poll(client, kiosk_headers, state="open"))["want"] is False


async def test_開くが同時に届いても記録は1件(client, device, kiosk_headers, operator_headers, tunnel_on):
    """2 件できると、終了しても古いほうが生き残って踏み台が鍵を通し続ける。"""
    import asyncio

    await _ready(client, kiosk_headers)
    results = await asyncio.gather(*[_open(client, operator_headers, device) for _ in range(4)])
    assert all(r.status_code in (200, 409) for r in results), [r.text for r in results]
    assert any(r.status_code == 200 for r in results)
    log = (await client.get("/api/operator/tunnel/sessions", headers=operator_headers)).json()["sessions"]
    assert [s["state"] for s in log] == ["requested"]

    await client.post(f"/api/operator/tunnel/{device.id}/close", headers=operator_headers)
    assert (await client.get("/api/bastion/authorized-keys", headers=BASTION)).text == ""
    assert (await client.get("/api/bastion/active-ports", headers=BASTION)).json() == {"ports": []}


async def test_受け口が置かれていない端末は開けない(client, device, kiosk_headers, operator_headers, tunnel_on):
    """常駐の鍵だけ届いていて、端末の中の受け口(sshd)が置かれていない。開いても入れない。"""
    await _poll(client, kiosk_headers, state="idle", pubkey=DEVICE_KEY)
    assert (await _open(client, operator_headers, device)).status_code == 409
    status = (await client.get(f"/api/operator/tunnel/status?device_ids={device.id}", headers=operator_headers)).json()
    assert status["devices"][device.id]["ready"] is False
    assert status["bastion_host_key"] == BASTION_KEY
