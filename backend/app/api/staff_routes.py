"""担当者ごとの通知先と代理通知の設定 API（管理画面「通知設定」の「担当者ごとの通知先」）。

`tenants.staff_list`（キオスクの訪問先ドロップダウン）の各担当者に、Slack チャンネル /
Chatwork ルーム / メール / Webhook / Web Push の宛先ユーザーを割り当てる。応答が無いときに
転送する代理担当者と待機秒数もここで決める。
行が無い担当者は従来どおりテナント共通の通知先だけに通知される（後方互換）。

担当者リスト自体の編集（追加・改名・削除・並べ替え）もここが持つ。以前は「受付設定」でしか
編集できず、宛先を決める画面と担当者を足す画面が別だった。

送信そのものは `services/reception_notify.py`、宛先の解決は `services/staff_routing.py`。
"""
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import PushSubscription
from app.models.reception import ReceptionLog
from app.models.staff_route import StaffNotificationRoute
from app.models.tenant import Tenant
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment
from app.services import chatwork as chatwork_service
from app.services.escalation import PENDING_STATES
from app.services import reception_notify, staff_routing
from app.services import email as email_service
from app.services.crypto import encrypt_dict
from app.services.slack import SlackApiError, SlackNotifier
from app.services.webpush import send_push
from app.services.staff_routing import (
    DEFAULT_ESCALATE_SEC,
    MAX_ESCALATE_SEC,
    MIN_ESCALATE_SEC,
    route_config,
)
from app.services.timeutil import iso_z, utcnow_naive

router = APIRouter(prefix="/notifications/staff-routes", tags=["staff-routes"])
logger = logging.getLogger(__name__)

_MAX_STAFF_NAME = 255
_MAX_WEBHOOK_URL = 512


class StaffRouteBody(BaseModel):
    staff_name: str
    slack_channel_id: str = ""
    # Chatwork のルーム ID。API トークンはテナント共通のものを使い回し、担当者ごとに
    # 差し替えるのはルームだけ(Slack と同じ考え方)。"" で解除。
    chatwork_room_id: str = ""
    email: str = ""
    # Web Push を届ける管理ユーザー。購読はユーザーのブラウザに紐づくため、担当者
    # (ただの名前)とユーザーをここで結びつける。"" で解除＝共通の購読へ。
    push_user_id: str = ""
    # Webhook URL は秘密情報としてレスポンスに出さない(CLAUDE.md「秘密情報の暗号化」)ので、
    # 画面は値を持たずに編集できる必要がある。None=変更しない / ""=解除 / URL=差し替え。
    webhook_url: str | None = None
    include_default: bool = True
    fallback_staff_name: str = ""
    escalate_after_sec: int = DEFAULT_ESCALATE_SEC

    @field_validator("chatwork_room_id")
    @classmethod
    def chatwork_room_numeric(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        if not re.fullmatch(r"[0-9]{1,20}", v):
            raise ValueError("Chatwork のルーム ID は数字で入力してください")
        return v

    @field_validator("staff_name")
    @classmethod
    def staff_name_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("担当者名は必須です")
        if len(v) > _MAX_STAFF_NAME:
            raise ValueError("担当者名が長すぎます")
        return v

    @field_validator("fallback_staff_name")
    @classmethod
    def fallback_len(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) > _MAX_STAFF_NAME:
            raise ValueError("代理担当者名が長すぎます")
        return v

    @field_validator("webhook_url")
    @classmethod
    def webhook_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return None  # 未指定＝既存の設定を維持する
        v = v.strip()
        if not v:
            return ""  # 明示的な解除
        if not re.match(r"^https?://", v):
            raise ValueError("Webhook URL は http(s):// で始めてください")
        if len(v) > _MAX_WEBHOOK_URL:
            raise ValueError("Webhook URL が長すぎます")
        return v

    @field_validator("escalate_after_sec")
    @classmethod
    def escalate_range(cls, v: int) -> int:
        if v == 0:
            return 0  # 0 = 代理通知しない
        if v < MIN_ESCALATE_SEC or v > MAX_ESCALATE_SEC:
            raise ValueError(f"代理通知までの秒数は 0(無効) または {MIN_ESCALATE_SEC}〜{MAX_ESCALATE_SEC} 秒です")
        return v


class TestBody(BaseModel):
    staff_name: str
    stage: str = "primary"  # primary | fallback

    @field_validator("stage")
    @classmethod
    def stage_allowed(cls, v: str) -> str:
        if v not in ("primary", "fallback"):
            raise ValueError("stage must be primary or fallback")
        return v


def _staff_list(tenant: Tenant | None) -> list[str]:
    raw = getattr(tenant, "staff_list", None) or ""
    return [n.strip() for n in raw.split(",") if n.strip()]


def _route_out(route: StaffNotificationRoute, known_staff: set[str]) -> dict:
    config = route_config(route)
    return {
        "id": route.id,
        "staff_name": route.staff_name,
        "slack_channel_id": config.get("slack_channel_id", ""),
        "slack_channel_name": config.get("slack_channel_name", ""),
        "chatwork_room_id": config.get("chatwork_room_id", ""),
        "push_user_id": getattr(route, "push_user_id", None) or "",
        "email": config.get("email", ""),
        # Webhook URL 自体は返さない（設定の有無だけ）。CLAUDE.md「秘密情報」方針。
        "webhook_configured": bool(config.get("webhook_url")),
        "include_default": bool(route.include_default),
        "fallback_staff_name": route.fallback_staff_name or "",
        "escalate_after_sec": int(route.escalate_after_sec or 0),
        # 受付設定の担当者リストから消えた担当者＝キオスクでは選ばれない（UIで注意表示）。
        "orphan": route.staff_name not in known_staff,
        "updated_at": iso_z(route.updated_at or route.created_at),
    }


async def _get_tenant(user: User, db: AsyncSession) -> Tenant | None:
    return (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()


@router.get("")
async def list_staff_routes(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """担当者リストと設定済みルートをまとめて返す（管理画面はこれ1本で描画できる）。"""
    tenant = await _get_tenant(user, db)
    staff_list = _staff_list(tenant)
    known = set(staff_list)

    result = await db.execute(
        select(StaffNotificationRoute)
        .where(StaffNotificationRoute.tenant_id == user.tenant_id)
        .order_by(StaffNotificationRoute.staff_name)
    )
    routes = [_route_out(r, known) for r in result.scalars()]

    slack_config = await staff_routing.load_default_slack_config(db, user.tenant_id)
    chatwork_token = await chatwork_service.load_api_token(db, user.tenant_id)
    push_users = await _push_user_options(user.tenant_id, db)

    # 退職などでユーザーが消えた後も id は行に残る（本番 DB は ALTER ADD COLUMN のため
    # ON DELETE SET NULL が効かない）。そのまま返すと画面のプルダウンが空欄になり、
    # 保存し直した瞬間に 422 になる。選べない id は「未指定」として見せる。
    known_user_ids = {u["id"] for u in push_users}
    for row in routes:
        if row["push_user_id"] and row["push_user_id"] not in known_user_ids:
            row["push_user_id"] = ""

    return {
        "staff_list": staff_list,
        "routes": routes,
        "slack": {
            # 担当者ごとのチャンネル指定は Bot Token 経路でのみ成立する（Webhook はチャンネル固定）。
            "bot_connected": bool(slack_config.get("bot_access_token")),
            "default_channel_name": slack_config.get("channel_name", ""),
        },
        "chatwork": {
            # トークンはテナント共通。未設定なら担当者ごとのルーム指定は使えない。
            # 共通ルームは「配達の呼び出し」専用で、受付通知は担当者ごとのルームだけへ送る。
            "connected": bool(chatwork_token),
        },
        # 担当者ごとの Web Push 先に選べる管理ユーザー。購読していない人も選べるが、
        # 選んでも届かないので画面で注意を出せるよう has_push を返す。
        "users": push_users,
        "smtp_enabled": settings.smtp_enabled,
        "default_escalate_sec": DEFAULT_ESCALATE_SEC,
        "min_escalate_sec": MIN_ESCALATE_SEC,
        "max_escalate_sec": MAX_ESCALATE_SEC,
    }


async def _push_user_options(tenant_id: str, db: AsyncSession) -> list[dict]:
    """プッシュ先に指定できるユーザー一覧（購読の有無つき）。"""
    users = (await db.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.name, User.email)
    )).scalars().all()
    subscribed = set((await db.execute(
        select(PushSubscription.user_id).where(PushSubscription.tenant_id == tenant_id)
    )).scalars().all())
    return [
        {
            "id": u.id,
            "name": (u.name or "").strip() or u.email,
            "email": u.email,
            "role": u.role,
            "has_push": u.id in subscribed,
        }
        for u in users
        # キオスク端末用アカウントは人ではないのでプッシュ先に出さない。
        if u.role != "kiosk"
    ]


@router.put("")
async def upsert_staff_route(
    body: StaffRouteBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """担当者1人ぶんの通知先を作成/更新する（担当者名で upsert）。"""
    if body.fallback_staff_name and body.fallback_staff_name == body.staff_name:
        raise HTTPException(status_code=422, detail="代理通知先には別の担当者を指定してください")

    try:
        emails = staff_routing.validate_emails(body.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    channel_id = (body.slack_channel_id or "").strip()
    channel_name = ""
    if channel_id:
        slack_config = await staff_routing.load_default_slack_config(db, user.tenant_id)
        token = slack_config.get("bot_access_token") or ""
        if not token:
            raise HTTPException(
                status_code=400,
                detail="Slackが未連携です。先に「Slackに追加」で連携してください。",
            )
        # 名称解決と公開チャンネルへの自動参加はテナント共通の設定と同じ手順。
        # Slack 側が一時的に落ちていても設定自体は保存できるよう best-effort に留める。
        try:
            info = await SlackNotifier.get_channel_info(token, channel_id)
            channel_name = ("#" if not info["is_private"] else "") + (info["name"] or channel_id)
            if not info["is_private"] and not info["is_member"]:
                await SlackNotifier.join_channel(token, channel_id)
        except SlackApiError:
            channel_name = channel_id

    # Chatwork はテナント共通のトークンを使い回す。未連携のままルームだけ指定しても
    # 届かないので、保存の時点で気付けるようにする（Slack と同じ扱い）。
    chatwork_room = (body.chatwork_room_id or "").strip()
    if chatwork_room:
        if not await chatwork_service.load_api_token(db, user.tenant_id):
            raise HTTPException(
                status_code=400,
                detail="Chatworkが未連携です。先に「通知設定」のChatworkでAPIトークンを登録してください。",
            )

    # プッシュ先ユーザーは自テナントの実在ユーザーだけ（テナント越境を防ぐ）。
    push_user_id = (body.push_user_id or "").strip()
    if push_user_id:
        target_user = (await db.execute(
            select(User).where(User.id == push_user_id, User.tenant_id == user.tenant_id)
        )).scalar_one_or_none()
        if target_user is None:
            raise HTTPException(status_code=422, detail="プッシュ通知先のユーザーが見つかりません")

    def apply(target: StaffNotificationRoute) -> None:
        """body の内容を行へ反映する。webhook_url 未指定はその行の現在値を維持する。"""
        current = route_config(target)
        webhook = current.get("webhook_url", "") if body.webhook_url is None else body.webhook_url
        target.config_json = encrypt_dict({
            "slack_channel_id": channel_id,
            "slack_channel_name": channel_name,
            "chatwork_room_id": chatwork_room,
            "email": ",".join(emails),
            "webhook_url": webhook,
        })
        target.push_user_id = push_user_id or None
        target.include_default = body.include_default
        target.fallback_staff_name = body.fallback_staff_name or None
        target.escalate_after_sec = body.escalate_after_sec
        target.updated_at = utcnow_naive()

    route = await staff_routing.get_route(db, user.tenant_id, body.staff_name)
    if route is None:
        route = StaffNotificationRoute(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            staff_name=body.staff_name,
        )
        db.add(route)
    apply(route)
    try:
        await db.commit()
    except IntegrityError:
        # 同じ担当者への同時 PUT で (tenant_id, staff_name) の一意制約に当たった＝
        # 相手が先に行を作った。作り直さず、その行を更新し直す。
        await db.rollback()
        route = await staff_routing.get_route(db, user.tenant_id, body.staff_name)
        if route is None:
            raise HTTPException(status_code=409, detail="保存に失敗しました。もう一度お試しください。")
        apply(route)
        await db.commit()
    await db.refresh(route)

    tenant = await _get_tenant(user, db)
    return {"ok": True, "route": _route_out(route, set(_staff_list(tenant)))}


# ── 担当者マスター ─────────────────────────────────────────────────────────────
# 担当者リストの実体は `tenants.staff_list`（カンマ区切り）で、キオスクの訪問先
# ドロップダウン・受付ログの突き合わせ・ここの通知先設定が同じ文字列を共有する。
# 編集の場は「通知設定」に集約し、「受付設定」側は読み取り専用にした（issue #1）。

class StaffListBody(BaseModel):
    """担当者リストを丸ごと置き換える（追加・削除・並べ替えを 1 回で反映する）。"""

    names: list[str]

    @field_validator("names")
    @classmethod
    def names_valid(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            name = (raw or "").strip()
            if not name:
                continue
            if len(name) > _MAX_STAFF_NAME:
                raise ValueError("担当者名が長すぎます")
            # 保存形式がカンマ区切りなので、名前にカンマが入ると壊れる。
            if "," in name:
                raise ValueError("担当者名にカンマは使えません")
            if name in out:
                raise ValueError(f"担当者名が重複しています: {name}")
            out.append(name)
        if len(out) > 200:
            raise ValueError("担当者は最大200名までです")
        return out


class StaffRenameBody(BaseModel):
    from_name: str
    to_name: str

    @field_validator("from_name", "to_name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("担当者名は必須です")
        if len(v) > _MAX_STAFF_NAME:
            raise ValueError("担当者名が長すぎます")
        if "," in v:
            raise ValueError("担当者名にカンマは使えません")
        return v


@router.put("/staff")
async def replace_staff_list(
    body: StaffListBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """担当者リストを置き換える（追加・削除・並べ替え）。

    リストから消えた担当者は、その担当者あての通知先設定も一緒に片付ける。残しておくと
    キオスクでは選べないのに設定だけ残り、代理通知先として参照され続けてしまう。
    """
    tenant = await _get_tenant(user, db)
    if tenant is None:
        raise HTTPException(status_code=404, detail="テナントが見つかりません")

    before = set(_staff_list(tenant))
    after = body.names
    removed = before - set(after)

    tenant.staff_list = ",".join(after) or None

    if removed:
        routes = (await db.execute(
            select(StaffNotificationRoute).where(
                StaffNotificationRoute.tenant_id == user.tenant_id
            )
        )).scalars().all()
        for route in routes:
            if route.staff_name in removed:
                await db.delete(route)
            elif (route.fallback_staff_name or "") in removed:
                # 代理通知先が居なくなった＝転送先を失う。黙って転送が止まるより、
                # 設定を外して画面上で「未設定」と分かるようにする。
                route.fallback_staff_name = None
                route.updated_at = utcnow_naive()

    await db.commit()
    return {"ok": True, "staff_list": after, "removed": sorted(removed)}


@router.post("/staff/rename")
async def rename_staff(
    body: StaffRenameBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """担当者名を変更し、通知先設定と代理通知先の参照も追随させる。

    過去の受付ログ（`reception_logs.staff`）は当時の記録なので書き換えない。ただし
    **まだ応答されていない受付だけ**は新しい名前に追随させる。そうしないと、その受付の
    代理通知が旧名で設定を探して見つけられず、安全網が黙って外れる。
    """
    tenant = await _get_tenant(user, db)
    if tenant is None:
        raise HTTPException(status_code=404, detail="テナントが見つかりません")

    names = _staff_list(tenant)
    if body.from_name not in names:
        raise HTTPException(status_code=404, detail="担当者が見つかりません")
    if body.to_name == body.from_name:
        return {"ok": True, "staff_list": names}
    if body.to_name in names:
        raise HTTPException(status_code=409, detail="同じ名前の担当者がすでに居ます")
    # 担当者リストだけでなく**設定行**も見る。リストから消えても設定だけ残っている
    # 担当者(orphan)と同じ名前へ改名すると (tenant_id, staff_name) が重複し、以後
    # `get_route()` の scalar_one_or_none() が MultipleResultsFound を投げて、
    # その担当者宛の通知が全経路サイレントに止まる。
    if await staff_routing.get_route(db, user.tenant_id, body.to_name) is not None:
        raise HTTPException(status_code=409, detail="同じ名前の通知先設定がすでにあります")

    tenant.staff_list = ",".join(body.to_name if n == body.from_name else n for n in names)

    routes = (await db.execute(
        select(StaffNotificationRoute).where(StaffNotificationRoute.tenant_id == user.tenant_id)
    )).scalars().all()
    for route in routes:
        touched = False
        if route.staff_name == body.from_name:
            route.staff_name = body.to_name
            touched = True
        if (route.fallback_staff_name or "") == body.from_name:
            route.fallback_staff_name = body.to_name
            touched = True
        if touched:
            route.updated_at = utcnow_naive()

    # まだ応答されていない受付。状態の集合と突き合わせ方(trim)は代理通知のスイープ
    # (`services/escalation.py`)と必ず揃える。片方だけズレると、改名した担当者の
    # 未応答受付だけ代理通知が静かに落ちる。
    pending = (await db.execute(
        select(ReceptionLog).where(
            ReceptionLog.tenant_id == user.tenant_id,
            func.trim(ReceptionLog.staff) == body.from_name,
            ReceptionLog.state.in_(PENDING_STATES),
        )
    )).scalars().all()
    for log in pending:
        log.staff = body.to_name

    # これから受け付ける来社予定も追随させる。予約の `staff` はキオスク受付時に
    # そのまま `reception_logs.staff` になるので、ここを旧名のまま残すと
    # 「登録済みの予約だけ担当者ごとの宛先も代理通知も効かない」状態になる。
    upcoming = (await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.tenant_id == user.tenant_id,
            func.trim(VisitorAppointment.staff) == body.from_name,
        )
    )).scalars().all()
    for appt in upcoming:
        appt.staff = body.to_name

    try:
        await db.commit()
    except IntegrityError:
        # 同名の行が既にある（(tenant_id, staff_name) の一意制約）。
        await db.rollback()
        raise HTTPException(status_code=409, detail="同じ名前の設定がすでにあります")

    return {
        "ok": True,
        "staff_list": _staff_list(tenant),
        "pending_updated": len(pending),
        "appointments_updated": len(upcoming),
    }


@router.delete("/{route_id}", status_code=200)
async def delete_staff_route(
    route_id: str,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """担当者ごとの設定を解除する（以後はテナント共通の通知先だけに送られる）。"""
    result = await db.execute(
        select(StaffNotificationRoute).where(
            StaffNotificationRoute.id == route_id,
            StaffNotificationRoute.tenant_id == user.tenant_id,
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="設定が見つかりません")
    await db.delete(route)
    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_staff_route(
    body: TestBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """設定した宛先へテスト通知を送り、宛先ごとの成否を返す。

    受付ログは作らない（テストで「受付」が1件増えないようにする）＝保存しない
    `ReceptionLog` を組み立てて文面だけ実運用と同じに揃える。応答ボタンは付けない
    （押しても対応先の受付が存在しないため）。
    """
    tenant = await _get_tenant(user, db)
    if body.stage == "fallback":
        dest = await staff_routing.resolve_fallback(db, user.tenant_id, body.staff_name)
        if dest is None:
            raise HTTPException(status_code=400, detail="代理通知先が設定されていません")
        escalated_from = body.staff_name
    else:
        dest = await staff_routing.resolve_primary(db, user.tenant_id, body.staff_name)
        escalated_from = ""

    sample = ReceptionLog(
        id="test-" + uuid.uuid4().hex[:8],
        tenant_id=user.tenant_id,
        visitor_name="テスト 太郎",
        company="テスト株式会社",
        purpose="通知テスト",
        staff=body.staff_name,
        method="form",
        state="received",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    results: list[dict] = []
    text = SlackNotifier.build_reception_message(
        visitor_name=sample.visitor_name,
        company=sample.company,
        host_name=sample.staff,
        when=sample.created_at,
        escalated_from=escalated_from or None,
    ) + "\n\n（これはテスト送信です）"

    slack_config = await staff_routing.load_default_slack_config(db, user.tenant_id)
    for config, label in staff_routing.slack_send_configs(slack_config, dest):
        ok = await SlackNotifier.send_to_config(config, text)
        results.append({"channel": "slack", "target": label, "ok": bool(ok)})

    chatwork_rooms = staff_routing.chatwork_send_rooms(dest)
    if chatwork_rooms:
        token = await chatwork_service.load_api_token(db, user.tenant_id)
        cw_text = chatwork_service.build_reception_message(
            visitor_name=sample.visitor_name,
            company=sample.company,
            host_name=sample.staff,
            when=sample.created_at,
            escalated_from=escalated_from or None,
        ) + "\n（これはテスト送信です）"
        for room_id, label in chatwork_rooms:
            if not token:
                results.append({
                    "channel": "chatwork", "target": label, "ok": False,
                    "error": "ChatworkのAPIトークンが未設定です",
                })
                continue
            ok = await chatwork_service.send_message(token, room_id, cw_text)
            results.append({"channel": "chatwork", "target": label, "ok": bool(ok)})

    # Web Push は実運用と同じ絞り込み（担当者→ユーザー→その人の端末）で送る。
    push_subs = await reception_notify.push_targets(db, user.tenant_id, dest, escalated_from)
    if dest.push_user_ids or push_subs:
        private_key = await reception_notify.vapid_private_key(db, user.tenant_id)
        if not private_key:
            results.append({
                "channel": "push", "target": "プッシュ通知", "ok": False,
                "error": "プッシュ通知が未設定です（通知設定で有効化してください）",
            })
        elif not push_subs:
            results.append({
                "channel": "push", "target": "プッシュ通知", "ok": False,
                "error": "届け先の端末がありません（対象ユーザーがまだプッシュを許可していません）",
            })
        else:
            sent = 0
            for sub in push_subs:
                try:
                    await send_push(
                        endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth_key,
                        title="通知テスト",
                        body=f"「{body.staff_name}」宛の通知テストです。",
                        url=f"/{user.tenant_id}/admin/reception",
                        private_key=private_key, subject=settings.vapid_subject,
                        tag="staff-route-test",
                    )
                    sent += 1
                except Exception:
                    pass
            results.append({
                "channel": "push", "target": f"{len(push_subs)}台", "ok": sent > 0,
                **({} if sent else {"error": "送信できませんでした"}),
            })

    for url in dest.webhooks:
        payload = reception_notify.build_webhook_payload(user.tenant_id, sample, escalated_from)
        payload["test"] = True
        ok = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
            ok = res.status_code < 400
        except Exception:
            ok = False
        results.append({"channel": "webhook", "target": "Webhook", "ok": ok})

    if dest.emails:
        if not settings.smtp_enabled:
            for addr in dest.emails:
                results.append({
                    "channel": "email", "target": addr, "ok": False,
                    "error": "メール送信が未設定です（管理者にSMTPの設定をご依頼ください）",
                })
        else:
            tenant_name = tenant.name if tenant else settings.app_name
            brand_color = tenant.brand_color if tenant else "#4a7c4e"
            slug = tenant.slug if tenant else user.tenant_id
            admin_url = f"{settings.public_web_url.rstrip('/')}/{slug}/admin/reception"
            subject, mail_text, html = reception_notify.build_reception_email(
                tenant_name, brand_color, sample, admin_url, escalated_from
            )
            subject = subject + "（テスト送信）"
            for addr in dest.emails:
                ok, err = await email_service.send_email(
                    to=addr,
                    subject=subject,
                    html=html,
                    text=mail_text,
                    host=settings.smtp_host,
                    port=settings.smtp_port,
                    username=settings.smtp_username,
                    password=settings.smtp_password,
                    from_addr=settings.smtp_from or settings.smtp_username,
                    from_name=settings.smtp_from_name or tenant_name,
                    starttls=settings.smtp_starttls,
                    use_ssl=settings.smtp_ssl,
                )
                row = {"channel": "email", "target": addr, "ok": bool(ok)}
                if not ok:
                    row["error"] = (err or "送信に失敗しました")[:200]
                results.append(row)

    if not results:
        raise HTTPException(status_code=400, detail="送信先が設定されていません")
    return {"ok": all(r["ok"] for r in results), "results": results}
