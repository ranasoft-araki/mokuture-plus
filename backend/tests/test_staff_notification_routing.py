"""担当者ごとの通知先 — Chatwork と Web Push の振り分け（issue #1 の追加要望）。

宛先の決め方(`services/staff_routing.py`)と、実際に送る側(`services/reception_notify.py`)
の分岐を確かめる。外部サービスへは出さず、送信関数を差し替えて「どこへ送ったか」だけを記録する。
"""
from __future__ import annotations

import pytest

from app.services import chatwork, reception_notify, staff_routing
from conftest import (  # type: ignore[import-not-found]
    add_push_subscription, add_reception, add_route, add_user,
    set_notification_setting, set_staff_list,
)
from app.database import AsyncSessionLocal


@pytest.fixture
def sent_chatwork(monkeypatch):
    """Chatwork への投稿を横取りして (room_id, text) を記録する。"""
    sent: list[tuple[str, str]] = []

    async def fake_send(api_token: str, room_id: str, text: str) -> bool:
        sent.append((room_id, text))
        return True

    monkeypatch.setattr(chatwork, "send_message", fake_send)
    monkeypatch.setattr(reception_notify.chatwork, "send_message", fake_send)
    return sent


@pytest.fixture
def sent_push(monkeypatch):
    """Web Push を横取りして endpoint を記録する。"""
    sent: list[str] = []

    async def fake_push(**kwargs):
        sent.append(kwargs["endpoint"])

    monkeypatch.setattr(reception_notify, "send_push", fake_push)
    return sent


@pytest.fixture
def no_slack(monkeypatch):
    """Slack は今回の対象外。呼ばれても外へ出さない。"""
    async def fake(*a, **kw):
        return True

    monkeypatch.setattr(reception_notify.SlackNotifier, "send_to_config", fake)


async def notify(tenant_id: str, log, stage: str = "primary") -> None:
    async with AsyncSessionLocal() as db:
        await reception_notify.notify_reception(db, tenant_id, log, stage=stage)


# ── Chatwork ───────────────────────────────────────────────────────────────────

async def test_担当者のルームへ送る(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"}, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["222"]
    assert "来客がありました" in sent_chatwork[0][1]
    assert "テスト株式会社" in sent_chatwork[0][1]


async def test_共通ルームにも送る設定なら両方へ(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"}, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sorted(room for room, _ in sent_chatwork) == ["111", "222"]


async def test_同じルームなら二重投稿しない(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "111"}, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["111"]


async def test_ルート未設定なら共通ルームへ(tenant, sent_chatwork, sent_push, no_slack):
    """設定を1件も作っていないテナントは従来どおりの挙動（後方互換）。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["111"]


async def test_トークン未設定なら何も送らない(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"})

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_chatwork == []


async def test_代理通知の文面になる(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"},
                    include_default=False, fallback="佐藤花子", escalate_after_sec=60)
    await add_route(tenant.id, "佐藤花子", config={"chatwork_room_id": "333"}, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log, stage="fallback")

    assert [room for room, _ in sent_chatwork] == ["333"]
    assert "応答がありません" in sent_chatwork[0][1]
    assert "田中太郎" in sent_chatwork[0][1]


# ── Web Push ───────────────────────────────────────────────────────────────────

async def test_担当者に紐づけたユーザーの端末だけに送る(tenant, sent_push, sent_chatwork, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    tanaka = await add_user(tenant.id, "田中太郎")
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, tanaka.id, "ep-tanaka")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka.id, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == ["ep-tanaka"]


async def test_共通にも送る設定なら全端末へ(tenant, sent_push, sent_chatwork, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    tanaka = await add_user(tenant.id, "田中太郎")
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, tanaka.id, "ep-tanaka")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka.id, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sorted(sent_push) == ["ep-other", "ep-tanaka"]
    assert len(sent_push) == 2, "同じ端末へ二重に送っている"


async def test_ルート未設定なら従来どおり全端末へ(tenant, sent_push, sent_chatwork, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "誰か")
    await add_push_subscription(tenant.id, u.id, "ep-1")
    await add_push_subscription(tenant.id, None, "ep-2")   # ユーザー未紐付けの古い購読

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sorted(sent_push) == ["ep-1", "ep-2"]


async def test_共通OFFでプッシュ先未指定なら送らない(tenant, sent_push, sent_chatwork, no_slack):
    """従来の挙動を保つ: 個別宛先だけに送る設定なら、プッシュは鳴らさない。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "誰か")
    await add_push_subscription(tenant.id, u.id, "ep-1")
    await add_route(tenant.id, "田中太郎", config={"email": "x@example.test"}, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == []


async def test_代理通知で絞れないときは全端末へ(tenant, sent_push, sent_chatwork, no_slack):
    """応答が無い状態で誰にも届かないのが一番危ない。安全側へ倒す。"""
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    u = await add_user(tenant.id, "誰か")
    await add_push_subscription(tenant.id, u.id, "ep-1")
    await add_route(tenant.id, "田中太郎", config={"email": "x@example.test"},
                    include_default=False, fallback="佐藤花子", escalate_after_sec=60)
    # 代理担当者にはメールだけあってプッシュ先は無い
    await add_route(tenant.id, "佐藤花子", config={"email": "y@example.test"}, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log, stage="fallback")

    assert sent_push == ["ep-1"]


async def test_代理担当者のプッシュ先が居ればその人だけに送る(tenant, sent_push, sent_chatwork, no_slack):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    sato = await add_user(tenant.id, "佐藤花子")
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, sato.id, "ep-sato")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", config={"email": "x@example.test"},
                    include_default=False, fallback="佐藤花子", escalate_after_sec=60)
    await add_route(tenant.id, "佐藤花子", push_user_id=sato.id, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log, stage="fallback")

    assert sent_push == ["ep-sato"]


async def test_他テナントの端末へは送らない(tenant, sent_push, sent_chatwork, no_slack):
    from app.models.tenant import Tenant
    import uuid as _uuid

    async with AsyncSessionLocal() as db:
        other_tenant = Tenant(id=str(_uuid.uuid4()), name="別会社", slug="other-" + _uuid.uuid4().hex[:6])
        db.add(other_tenant)
        await db.commit()
    await add_push_subscription(other_tenant.id, None, "ep-foreign")

    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "誰か")
    await add_push_subscription(tenant.id, u.id, "ep-mine")

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == ["ep-mine"]


# ── 宛先解決そのもの ───────────────────────────────────────────────────────────

async def test_宛先にルームとプッシュ先が乗る(tenant):
    await set_staff_list(tenant.id, ["田中太郎"])
    u = await add_user(tenant.id, "田中太郎")
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"}, push_user_id=u.id)

    async with AsyncSessionLocal() as db:
        dest = await staff_routing.resolve_primary(db, tenant.id, "田中太郎")

    assert dest.chatwork_rooms == ("222",)
    assert dest.push_user_ids == (u.id,)
    assert dest.has_direct is True


async def test_ルームだけでも個別宛先とみなす(tenant):
    """has_direct が False だと代理通知が共通へ流れてしまう。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"})

    async with AsyncSessionLocal() as db:
        dest = await staff_routing.resolve_primary(db, tenant.id, "田中太郎")
    assert dest.has_direct is True
