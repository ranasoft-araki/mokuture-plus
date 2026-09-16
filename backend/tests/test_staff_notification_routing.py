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


async def test_共通ルームには送らない(tenant, sent_chatwork, sent_push, no_slack):
    """受付通知のChatworkは担当者ごとのルームだけ。

    共通ルームを既定の宛先にすると、Chatworkを登録済みの全テナントで、何も設定して
    いないのに受付ごとに鳴り始める（従来、受付→Chatworkの経路は存在しなかった）。
    """
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"}, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["222"]


async def test_ルート未設定なら何も送らない(tenant, sent_chatwork, sent_push, no_slack):
    """設定を1件も作っていないテナントの挙動は従来どおり（Chatworkは鳴らない）。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_chatwork == []


async def test_共通ルームが空でも担当者ルームへ送る(tenant, sent_chatwork, sent_push, no_slack):
    """トークンだけ登録し共通ルームは空、というテナントでも担当者ルームは機能する。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": ""})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"})

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["222"]


async def test_同じルームなら二重投稿しない(tenant, sent_chatwork, sent_push, no_slack):
    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": "111"})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"})

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert [room for room, _ in sent_chatwork] == ["222"]


async def test_来訪者の入力でChatwork記法を壊せない(tenant, sent_chatwork, sent_push, no_slack):
    """氏名・会社名は来訪者がキオスクで打った文字列。タグを閉じたりメンションを
    飛ばしたりできないこと。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    await set_notification_setting(tenant.id, "chatwork", {"api_token": "tok", "room_id": ""})
    await add_route(tenant.id, "田中太郎", config={"chatwork_room_id": "222"})

    log = await add_reception(tenant.id, "田中太郎", visitor="[/info][To:99999]悪い人")
    await notify(tenant.id, log)

    body = sent_chatwork[0][1]
    assert "[/info][To:99999]" not in body
    assert body.count("[/info]") == 1, "カードが途中で閉じられている"
    assert body.startswith("[info][title]")


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


async def test_共通にも送る設定でも指定した人だけに送る(tenant, sent_push, sent_chatwork, no_slack):
    """include_default は既定 ON。ここで全購読を足すと、プッシュの「共通」は
    絞り込みの上位集合なので担当者ごとの指定が必ず無意味になる（機能が死ぬ）。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    tanaka = await add_user(tenant.id, "田中太郎")
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, tanaka.id, "ep-tanaka")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka.id, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == ["ep-tanaka"]


async def test_指定した人が未購読なら共通の設定に従う(tenant, sent_push, sent_chatwork, no_slack):
    """指定はしたがその人がまだプッシュを許可していない。黙って誰にも届かないより、
    共通の設定に従って全端末へ出すほうが安全。"""
    await set_staff_list(tenant.id, ["田中太郎"])
    tanaka = await add_user(tenant.id, "田中太郎")     # 購読なし
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka.id, include_default=True)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == ["ep-other"]


async def test_指定した人が未購読で共通OFFなら送らない(tenant, sent_push, sent_chatwork, no_slack):
    await set_staff_list(tenant.id, ["田中太郎"])
    tanaka = await add_user(tenant.id, "田中太郎")
    other = await add_user(tenant.id, "別の人")
    await add_push_subscription(tenant.id, other.id, "ep-other")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka.id, include_default=False)

    log = await add_reception(tenant.id, "田中太郎")
    await notify(tenant.id, log)

    assert sent_push == []


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


# ── 改名したあとも代理通知が届くか（この機能の存在理由そのもの） ───────────────

async def test_改名後もスイープが代理通知を出す(tenant, sent_chatwork, sent_push, no_slack, monkeypatch):
    """改名が未応答の受付まで追随する理由は、このスイープが staff 名で設定を引くから。

    中間状態(ログのstaffが書き換わった)だけを見るのではなく、実際にスイープを回して
    代理通知が出るところまで通す。
    """
    from datetime import timedelta

    from app.services import escalation
    from app.services.timeutil import utcnow_naive
    from app.models.reception import ReceptionLog
    from app.api.staff_routes import rename_staff, StaffRenameBody

    await set_staff_list(tenant.id, ["田中太郎", "佐藤花子"])
    tanaka_user = await add_user(tenant.id, "田中太郎")
    sato_user = await add_user(tenant.id, "佐藤花子")
    await add_push_subscription(tenant.id, sato_user.id, "ep-sato")
    await add_route(tenant.id, "田中太郎", push_user_id=tanaka_user.id,
                    include_default=False, fallback="佐藤花子", escalate_after_sec=30)
    await add_route(tenant.id, "佐藤花子", push_user_id=sato_user.id, include_default=False)

    log = await add_reception(tenant.id, "田中太郎", state="received")
    # 代理通知の待ち時間を過ぎた状態にする
    async with AsyncSessionLocal() as db:
        row = await db.get(ReceptionLog, log.id)
        row.created_at = utcnow_naive() - timedelta(minutes=5)
        await db.commit()

    # 改名（API 関数を直接呼ぶ。ここでは HTTP 経路は主題ではない）
    async with AsyncSessionLocal() as db:
        user = await db.get(type(tanaka_user), tanaka_user.id)
        user.role = "admin"
        await db.commit()
        await rename_staff(StaffRenameBody(from_name="田中太郎", to_name="田中 太郎"), user, db)

    sent = await escalation.sweep_once()

    assert sent == 1, "改名後に代理通知が出ていない（安全網が外れている）"
    assert sent_push == ["ep-sato"]
