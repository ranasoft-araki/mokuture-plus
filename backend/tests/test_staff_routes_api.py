"""担当者ごとの通知先 API — 担当者マスターの管理と、Chatwork / プッシュ先の保存。

担当者リストの実体は `tenants.staff_list`（カンマ区切り）のまま。編集の場を「通知設定」へ
移したので、追加・削除・並べ替え・改名がこの API を通る（issue #1 の追加要望）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import AsyncSessionLocal
from app.models.reception import ReceptionLog
from app.models.staff_route import StaffNotificationRoute
from app.models.tenant import Tenant
from app.services import staff_routing
from conftest import (  # type: ignore[import-not-found]
    add_push_subscription, add_reception, add_route, add_user,
    set_notification_setting, set_staff_list,
)

API = "/api/notifications/staff-routes"


async def staff_list_of(tenant_id: str) -> list[str]:
    async with AsyncSessionLocal() as db:
        t = await db.get(Tenant, tenant_id)
        raw = t.staff_list or ""
    return [n.strip() for n in raw.split(",") if n.strip()]


async def route_of(tenant_id: str, name: str) -> StaffNotificationRoute | None:
    async with AsyncSessionLocal() as db:
        return await staff_routing.get_route(db, tenant_id, name)


# ── 一覧 ───────────────────────────────────────────────────────────────────────

async def test_一覧に担当者とユーザー候補が出る(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    u = await add_user(tenant.id, "田中太郎")
    await add_push_subscription(tenant.id, u.id, "ep-1")

    data = client.get(API).json()

    assert data["staff_list"] == ["田中太郎", "佐藤花子"]
    ids = {x["id"] for x in data["users"]}
    assert u.id in ids
    picked = next(x for x in data["users"] if x["id"] == u.id)
    assert picked["has_push"] is True
    assert data["chatwork"]["connected"] is False


async def test_キオスク端末アカウントはプッシュ先候補に出ない(client, tenant):
    await add_user(tenant.id, "キオスク", role="kiosk")
    data = client.get(API).json()
    assert all(x["role"] != "kiosk" for x in data["users"])


async def test_一覧にChatworkの連携状態が出る(client, tenant):
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    data = client.get(API).json()
    assert data["chatwork"]["connected"] is True


# ── 担当者マスター ─────────────────────────────────────────────────────────────

async def test_担当者を追加できる(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    r = client.put(f"{API}/staff", json={"names": ["田中太郎", "佐藤花子"]})
    assert r.status_code == 200
    assert await staff_list_of(tenant.id) == ["田中太郎", "佐藤花子"]


async def test_並べ替えできる(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    client.put(f"{API}/staff", json={"names": ["佐藤花子", "田中太郎"]})
    assert await staff_list_of(tenant.id) == ["佐藤花子", "田中太郎"]


async def test_削除すると通知先設定も片付く(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    await add_route(tenant.id, "田中太郎", config={"email": "a@example.test"})
    await add_route(tenant.id, "佐藤花子", config={"email": "b@example.test"})

    r = client.put(f"{API}/staff", json={"names": ["田中太郎"]})

    assert r.status_code == 200
    assert r.json()["removed"] == ["佐藤花子"]
    assert await route_of(tenant.id, "佐藤花子") is None
    assert await route_of(tenant.id, "田中太郎") is not None


async def test_削除された担当者への代理通知設定は外れる(client, tenant):
    """転送先が居なくなったまま残すと、黙って代理通知が空振りする。"""
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    await add_route(tenant.id, "田中太郎", config={"email": "a@example.test"},
                    fallback="佐藤花子", escalate_after_sec=60)

    client.put(f"{API}/staff", json={"names": ["田中太郎"]})

    route = await route_of(tenant.id, "田中太郎")
    assert route.fallback_staff_name in (None, "")


@pytest.mark.parametrize("names,reason", [
    (["田中太郎", "田中太郎"], "重複"),
    (["田中,太郎"], "カンマ"),
    ([" " * 3], "空だけ"),
])
async def test_不正な担当者名は弾く(client, tenant, names, reason):
    await set_staff_list(tenant.id, ["元の人"])
    r = client.put(f"{API}/staff", json={"names": names})
    if reason == "空だけ":
        # 空白だけの要素は落として「全員削除」として成立する
        assert r.status_code == 200
        assert await staff_list_of(tenant.id) == []
    else:
        assert r.status_code == 422, reason
        assert await staff_list_of(tenant.id) == ["元の人"], "失敗したのに書き換わっている"


async def test_改名で設定と代理通知先が追随する(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    await add_route(tenant.id, "田中太郎", config={"email": "a@example.test"})
    await add_route(tenant.id, "佐藤花子", config={"email": "b@example.test"},
                    fallback="田中太郎", escalate_after_sec=60)

    r = client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "田中 太郎"})

    assert r.status_code == 200
    assert await staff_list_of(tenant.id) == ["田中 太郎", "佐藤花子"]
    assert await route_of(tenant.id, "田中 太郎") is not None
    assert await route_of(tenant.id, "田中太郎") is None
    sato = await route_of(tenant.id, "佐藤花子")
    assert sato.fallback_staff_name == "田中 太郎"


async def test_改名は未応答の受付だけ追随させる(client, tenant):
    """進行中の受付の代理通知が、旧名で設定を探して空振りしないようにする。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    pending = await add_reception(tenant.id, "田中太郎", state="received")
    done = await add_reception(tenant.id, "田中太郎", state="accepted")

    r = client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "田中 太郎"})
    assert r.json()["pending_updated"] == 1

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReceptionLog, pending.id)).staff == "田中 太郎"
        # 完了済みの履歴は当時の記録のまま
        assert (await db.get(ReceptionLog, done.id)).staff == "田中太郎"


async def test_居ない担当者の改名は404(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    r = client.post(f"{API}/staff/rename", json={"from_name": "誰か", "to_name": "別の人"})
    assert r.status_code == 404


async def test_同名への改名は409(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    r = client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "佐藤花子"})
    assert r.status_code == 409
    assert await staff_list_of(tenant.id) == ["田中太郎", "佐藤花子"]


# ── 通知先の保存 ───────────────────────────────────────────────────────────────

async def test_Chatworkのルームを保存できる(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})

    r = client.put(API, json={"staff_name": "田中太郎", "chatwork_room_id": "222"})

    assert r.status_code == 200
    assert r.json()["route"]["chatwork_room_id"] == "222"
    assert client.get(API).json()["routes"][0]["chatwork_room_id"] == "222"


async def test_Chatwork未連携でルーム指定すると400(client, tenant):
    """保存できてしまうと「設定したのに届かない」になる。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    r = client.put(API, json={"staff_name": "田中太郎", "chatwork_room_id": "222"})
    assert r.status_code == 400


@pytest.mark.parametrize("room", ["abc", "22-2", "1 2"])
async def test_ルームIDが数字でなければ弾く(client, tenant, room):
    await set_staff_list(tenant.id, ["田中太郎"])
    r = client.put(API, json={"staff_name": "田中太郎", "chatwork_room_id": room})
    assert r.status_code == 422


async def test_プッシュ先ユーザーを保存できる(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "田中太郎")

    r = client.put(API, json={"staff_name": "田中太郎", "push_user_id": u.id})

    assert r.status_code == 200
    assert r.json()["route"]["push_user_id"] == u.id
    route = await route_of(tenant.id, "田中太郎")
    assert route.push_user_id == u.id


async def test_プッシュ先を解除できる(client, tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "田中太郎")
    client.put(API, json={"staff_name": "田中太郎", "push_user_id": u.id})

    client.put(API, json={"staff_name": "田中太郎", "push_user_id": ""})

    route = await route_of(tenant.id, "田中太郎")
    assert route.push_user_id is None


async def test_他テナントのユーザーはプッシュ先にできない(client, tenant):
    import uuid as _uuid
    async with AsyncSessionLocal() as db:
        other = Tenant(id=str(_uuid.uuid4()), name="別会社", slug="o-" + _uuid.uuid4().hex[:6])
        db.add(other)
        await db.commit()
    foreign = await add_user(other.id, "よその人")

    await set_staff_list(tenant.id, ["田中太郎"])
    r = client.put(API, json={"staff_name": "田中太郎", "push_user_id": foreign.id})

    assert r.status_code == 422


async def test_既存のメールとWebhookを壊さない(client, tenant):
    """Chatwork とプッシュを足しても、これまでの宛先は維持される。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    client.put(API, json={
        "staff_name": "田中太郎", "email": "a@example.test", "webhook_url": "https://example.test/hook",
    })
    client.put(API, json={"staff_name": "田中太郎", "email": "a@example.test"})  # webhook 未指定＝維持

    row = client.get(API).json()["routes"][0]
    assert row["email"] == "a@example.test"
    assert row["webhook_configured"] is True


# ── 権限 ───────────────────────────────────────────────────────────────────────

async def test_一般ユーザーは触れない(tenant):
    from app.api.staff_routes import router
    from app.middleware.tenant import get_current_user

    staff_user = await add_user(tenant.id, "ただの社員", role="staff")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: staff_user

    with TestClient(app) as c:
        assert c.get(API).status_code == 403
        assert c.put(f"{API}/staff", json={"names": ["誰か"]}).status_code == 403
        assert c.post(f"{API}/staff/rename",
                      json={"from_name": "a", "to_name": "b"}).status_code == 403


async def test_消えたユーザーのプッシュ先は未指定として返す(client, tenant):
    """本番DBは ALTER ADD COLUMN のため ON DELETE SET NULL が効かない。
    そのまま返すとプルダウンが空欄になり、保存し直した瞬間に 422 になる。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await add_route(tenant.id, "田中太郎", push_user_id="deleted-user-id")

    row = client.get(API).json()["routes"][0]

    assert row["push_user_id"] == ""


# ── 改名の追随（代理通知の安全網を外さないこと） ─────────────────────────────

async def test_設定だけ残る担当者と同名への改名を拒む(client, tenant):
    """リストから消えても設定行は残る(orphan)。同名へ改名すると
    (tenant_id, staff_name) が重複し、以後 get_route() が MultipleResultsFound を
    投げて、その担当者宛の通知が全経路サイレントに止まる。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await add_route(tenant.id, "田中太郎", config={"email": "a@example.test"})
    await add_route(tenant.id, "佐藤花子", config={"email": "b@example.test"})  # orphan

    r = client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "佐藤花子"})

    assert r.status_code == 409
    async with AsyncSessionLocal() as db:
        assert await staff_routing.get_route(db, tenant.id, "佐藤花子") is not None  # 例外にならない
    assert await staff_list_of(tenant.id) == ["田中太郎"]


async def test_改名は来社予定にも追随する(client, tenant):
    """予約の staff はキオスク受付時にそのまま受付ログの staff になる。旧名のまま
    残すと、登録済みの予約だけ担当者ごとの宛先も代理通知も効かない。"""
    from datetime import datetime, timedelta, timezone
    from app.models.visitor_appointment import VisitorAppointment
    import uuid as _uuid

    await set_staff_list(tenant.id, ["田中太郎"])
    async with AsyncSessionLocal() as db:
        appt = VisitorAppointment(
            id=str(_uuid.uuid4()), tenant_id=tenant.id,
            visitor_name="来客 花子", staff="田中太郎",
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
        )
        db.add(appt)
        await db.commit()

    r = client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "田中 太郎"})

    assert r.json()["appointments_updated"] == 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(VisitorAppointment, appt.id)).staff == "田中 太郎"


async def test_改名はnotified状態の受付にも追随する(client, tenant):
    """追随する状態の集合は代理通知のスイープ(PENDING_STATES)と揃える。"""
    from app.services.escalation import PENDING_STATES

    assert "notified" in PENDING_STATES
    await set_staff_list(tenant.id, ["田中太郎"])
    notified = await add_reception(tenant.id, "田中太郎", state="notified")

    client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "田中 太郎"})

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReceptionLog, notified.id)).staff == "田中 太郎"


async def test_改名は前後空白付きの受付も拾う(client, tenant):
    """スイープ側が func.trim() で拾っている行を、改名だけ取りこぼさないこと。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    padded = await add_reception(tenant.id, " 田中太郎 ", state="received")

    client.post(f"{API}/staff/rename", json={"from_name": "田中太郎", "to_name": "田中 太郎"})

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReceptionLog, padded.id)).staff == "田中 太郎"


# ── 他経路からの巻き戻し防止 ───────────────────────────────────────────────────

async def test_受付設定のPATCHでは担当者リストを書き換えない(admin, tenant):
    """デプロイ前に開かれていた古いタブが受付設定を保存しても、担当者リストを
    その時点の内容で巻き戻さないこと。"""
    from app.api.settings import router as settings_router
    from app.middleware.tenant import get_current_user

    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    app = FastAPI()
    app.include_router(settings_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin

    with TestClient(app) as c:
        r = c.patch("/api/settings", json={"staff_list": "古い人", "purpose_list": "打ち合わせ"})

    assert r.status_code == 200
    assert await staff_list_of(tenant.id) == ["田中太郎", "佐藤花子"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Tenant, tenant.id)).purpose_list == "打ち合わせ"  # 他の項目は通る


async def test_ユーザー削除でプッシュ宛先が外れる(admin, tenant):
    """本番DBの push_user_id は ON DELETE SET NULL が効かない。残すと画面は
    「指定しない」と出るのに、実際は宛先が解決できず届かない状態になる。"""
    from app.api.users import router as users_router
    from app.middleware.tenant import get_current_user

    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "田中太郎")
    await add_route(tenant.id, "田中太郎", push_user_id=u.id)

    app = FastAPI()
    app.include_router(users_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        assert c.delete(f"/api/users/{u.id}").status_code == 204

    route = await route_of(tenant.id, "田中太郎")
    assert route.push_user_id is None
