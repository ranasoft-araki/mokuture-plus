"""遠隔ログインの API。決まりごとは services/tunnel.py の先頭を参照。

  運営(JWT・operator)  /operator/tunnel/*   開く・終了する・状態を見る・記録を見る
  端末(デバイストークン) /kiosk/tunnel/poll  端末の常駐が「開けと言われているか」を聞きに来る
  踏み台(合言葉)        /bastion/*          踏み台の sshd が「この鍵を通してよいか」を聞きに来る
"""
from __future__ import annotations

import hmac
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.tenant import require_operator
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.tunnel import TunnelSession
from app.models.user import User
from app.services import tunnel as svc
from app.services.timeutil import format_jst, iso_z, to_naive_utc, utcnow_naive

router = APIRouter(tags=["tunnel"])

MIN_MINUTES = 5
# 開いている(または片づけ中の)あいだ、端末が聞きに来る間隔
ACTIVE_POLL_SEC = 5
# 機能が無効のときの間隔(設定されたら気づける程度に)
DISABLED_POLL_SEC = 600


def _require_enabled() -> None:
    if not settings.tunnel_enabled:
        raise HTTPException(
            status_code=503,
            detail="遠隔ログインはまだ使えません（踏み台サーバーの設定 TUNNEL_BASTION_* がサーバーにありません）",
        )


def _session_out(s: TunnelSession | None) -> dict | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "device_id": s.device_id,
        "device_name": s.device_name,
        "tenant_name": s.tenant_name,
        "state": s.state,
        "port": s.port,
        "reason": s.reason,
        "requested_by": s.requested_by_email,
        "requested_at": iso_z(s.requested_at),
        "expires_at": iso_z(s.expires_at),
        "opened_at": iso_z(s.opened_at),
        "closed_at": iso_z(s.closed_at),
        "close_reason": s.close_reason,
        "closed_by": s.closed_by_email,
        "error": s.error,
    }


def _alive(device: Device, now) -> bool:
    """端末の遠隔ログイン用の常駐が、最近聞きに来ているか。"""
    seen = to_naive_utc(device.tunnel_seen_at)
    if seen is None:
        return False
    return (now - seen).total_seconds() <= max(180, settings.tunnel_idle_poll_sec * 3)


# ── 運営 ──────────────────────────────────────────────────────────────────────

@router.get("/operator/tunnel/status")
async def tunnel_status(
    device_ids: str = Query("", max_length=8000),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """端末ごとの遠隔ログインの状態(運営パネル「デバイス管理」の表示元)。"""
    ids = [x for x in (p.strip() for p in device_ids.split(",")) if x][:200]
    out = {
        "enabled": settings.tunnel_enabled,
        "bastion_host": settings.tunnel_bastion_host,
        "bastion_port": settings.tunnel_bastion_port,
        "default_minutes": settings.tunnel_default_minutes,
        "max_minutes": settings.tunnel_max_minutes,
        "min_minutes": MIN_MINUTES,
        # 運営が初めて踏み台へつなぐとき、相手が本物かを確かめる材料(公開鍵。秘密ではない)
        "bastion_host_key": svc.clean_pubkey(settings.tunnel_bastion_host_key) or "",
        "devices": {},
    }
    if not ids:
        return out
    now = utcnow_naive()
    devices = (await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all()
    sessions = (await db.execute(
        select(TunnelSession)
        .where(TunnelSession.device_id.in_(ids), TunnelSession.state.in_(svc.PENDING_STATES))
        .order_by(TunnelSession.requested_at.desc())
    )).scalars().all()
    by_device: dict[str, TunnelSession] = {}
    changed = False
    for s in sessions:
        changed = await svc.settle(db, s, now) or changed
        if s.state in svc.PENDING_STATES:
            by_device.setdefault(s.device_id, s)
    if changed:
        await db.commit()
    for d in devices:
        out["devices"][d.id] = {
            # 端末側の準備ができているか: 常駐が鍵を届けていて、受け口(端末の中の sshd)も置かれている
            "ready": bool(svc.clean_pubkey(d.tunnel_pubkey) and svc.clean_pubkey(d.tunnel_host_key)),
            "alive": _alive(d, now),
            "seen_at": iso_z(d.tunnel_seen_at),
            "reach": d.tunnel_reach,
            "port": d.tunnel_port,
            "login_user": d.tunnel_login_user,
            "host_key": d.tunnel_host_key,
            "session": _session_out(by_device.get(d.id)),
        }
    return out


class OpenTunnelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    minutes: Optional[int] = None


@router.post("/operator/tunnel/{device_id}/open")
async def open_tunnel(
    device_id: str,
    body: OpenTunnelRequest,
    user: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """遠隔ログインを開く(すでに開いていれば、終了時刻を延ばす)。"""
    _require_enabled()
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="理由を入力してください")
    minutes = body.minutes if body.minutes is not None else settings.tunnel_default_minutes
    if not (MIN_MINUTES <= minutes <= settings.tunnel_max_minutes):
        raise HTTPException(
            status_code=422,
            detail=f"開けておく時間は {MIN_MINUTES}〜{settings.tunnel_max_minutes} 分で指定してください",
        )
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="端末が見つかりません")
    if (device.status or "active") != "active":
        raise HTTPException(status_code=409, detail="承認されていない端末には遠隔ログインできません")
    if not (svc.clean_pubkey(device.tunnel_pubkey) and svc.clean_pubkey(device.tunnel_host_key)):
        raise HTTPException(
            status_code=409,
            detail="この端末は遠隔ログインの準備ができていません（端末側の仕組みがまだ入っていません）",
        )
    now = utcnow_naive()
    session = await svc.pending_session(db, device.id)
    if session is not None:
        await svc.settle(db, session, now)
    if session is not None and session.state in svc.LIVE_STATES:
        # 延長。誰が・いつ・何のために延ばしたかも残す
        extended = await svc.move(
            db, session, session.state,
            expires_at=svc.expiry(now, minutes),
            reason=f"{session.reason}\n延長（{user.email}・{format_jst(now)}）: {reason}"[:2000],
        )
        await db.commit()
        if not extended:
            raise HTTPException(status_code=409, detail="ほかの操作と重なりました。画面の状態を確かめてからやり直してください")
        return _session_out(session)
    if session is not None and session.state == "closing":
        await db.commit()
        raise HTTPException(status_code=409, detail="前回の遠隔ログインを閉じている途中です。少し待ってからやり直してください")

    port = await svc.allocate_port(db, device)
    if port is None:
        raise HTTPException(status_code=503, detail="踏み台の転送口に空きがありません")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == device.tenant_id))).scalar_one_or_none()
    session = TunnelSession(
        device_id=device.id,
        tenant_id=device.tenant_id,
        device_name=device.name or "",
        tenant_name=(tenant.name if tenant else "") or "",
        port=port,
        state="requested",
        requested_by_user_id=user.id,
        requested_by_email=user.email or "",
        reason=reason,
        requested_at=now,
        expires_at=svc.expiry(now, minutes),
    )
    db.add(session)
    try:
        await db.commit()
    except IntegrityError:
        # 同じ端末の「開く」が同時に届いた(片づいていない記録は端末ごとに 1 件)か、
        # 別の端末と同じ転送口を取り合った(devices.tunnel_port は一意)
        await db.rollback()
        raise HTTPException(status_code=409, detail="ほかの操作と重なりました。画面の状態を確かめてからやり直してください")
    return _session_out(session)


@router.post("/operator/tunnel/{device_id}/close")
async def close_tunnel(
    device_id: str,
    user: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """遠隔ログインを終了する。踏み台は 1 分以内に経路を切り、端末は次に聞きに来たときに閉じる。"""
    now = utcnow_naive()
    sessions = await svc.pending_sessions(db, device_id)
    # 片づいていないものはすべて閉じる(1 件のはずだが、残りがあれば踏み台が鍵を通し続ける)
    for session in sessions:
        await svc.settle(db, session, now)
        # 端末の問い合わせが同時に状態を動かしていたら、動いたあとの状態から閉じ直す
        for _ in range(3):
            if session.state not in svc.LIVE_STATES:
                break
            if await svc.move(db, session, session.state, state="closing", close_requested_at=now,
                              close_reason="operator", closed_by_email=user.email or ""):
                break
    await db.commit()
    return {"ok": True, "session": _session_out(sessions[0]) if sessions else None}


@router.get("/operator/tunnel/sessions")
async def list_tunnel_sessions(
    device_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """遠隔ログインの記録(新しい順)。誰が・いつ・どの端末を・何のために開けたか。"""
    stmt = select(TunnelSession).order_by(TunnelSession.requested_at.desc()).limit(limit)
    if device_id:
        stmt = stmt.where(TunnelSession.device_id == device_id)
    sessions = (await db.execute(stmt)).scalars().all()
    now = utcnow_naive()
    changed = False
    for s in sessions:
        changed = await svc.settle(db, s, now) or changed
    if changed:
        await db.commit()
    return {"sessions": [_session_out(s) for s in sessions]}


# ── 端末 ──────────────────────────────────────────────────────────────────────

class TunnelPollBody(BaseModel):
    # 新しい常駐が項目を足しても、古いサーバーが 422 で落とさないように
    model_config = ConfigDict(extra="ignore")

    state: Literal["idle", "connecting", "open"] = "idle"
    pubkey: Optional[str] = Field(default=None, max_length=400)
    host_key: Optional[str] = Field(default=None, max_length=400)
    login_user: Optional[str] = Field(default=None, max_length=64)
    reach: Optional[Literal["ok", "blocked"]] = None
    error: Optional[str] = Field(default=None, max_length=400)


@router.post("/kiosk/tunnel/poll")
async def tunnel_poll(
    body: TunnelPollBody,
    x_kiosk_token: str = Header(alias="X-Kiosk-Token"),
    db: AsyncSession = Depends(get_db),
):
    """端末の遠隔ログイン用の常駐が聞きに来る。「開けと言われているか」と、つなぎ先を返す。

    キオスク本体とは別の常駐なので、ここでは端末の「最終接続」(last_seen_at)を動かさない
    (本体が止まっているのに「オンライン」に見えてしまう)。"""
    device = (await db.execute(select(Device).where(Device.token == x_kiosk_token))).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")
    if not settings.tunnel_enabled:
        return {"enabled": False, "want": False, "poll_sec": DISABLED_POLL_SEC}

    now = utcnow_naive()
    changed = False
    session = await svc.pending_session(db, device.id)
    if session is not None:
        changed = await svc.settle(db, session, now) or changed
        if session.state == "closed":
            session = None

    # 端末が届ける鍵など。鍵は、遠隔ログインが動いていないときだけ差し替えを受け付ける
    # (開いている最中に別の鍵へすり替えて、転送口を横取りされないように)。
    pubkey = svc.clean_pubkey(body.pubkey)
    if pubkey and pubkey != device.tunnel_pubkey and (session is None or not device.tunnel_pubkey):
        device.tunnel_pubkey = pubkey
        changed = True
    host_key = svc.clean_pubkey(body.host_key)
    if host_key and host_key != device.tunnel_host_key and session is None:
        device.tunnel_host_key = host_key
        changed = True
    login_user = svc.clean_login_user(body.login_user)
    if login_user and login_user != device.tunnel_login_user:
        device.tunnel_login_user = login_user
        changed = True
    if body.reach and body.reach != device.tunnel_reach:
        device.tunnel_reach = body.reach
        changed = True
    seen = to_naive_utc(device.tunnel_seen_at)
    if seen is None or (now - seen).total_seconds() >= 120 or changed:
        device.tunnel_seen_at = now
        changed = True

    approved = (device.status or "active") == "active"
    if session is not None:
        # 書き換えは svc.move(読んだときの状態のままのときだけ書く)。同時に届いた運営の
        # 「終了」を、端末の報告で上書きしない。書けなかったら、読み直した状態のまま答える。
        if session.state == "closing" and body.state != "open":
            changed = await svc.move(db, session, "closing", state="closed", closed_at=now) or changed
        elif session.state == "requested" and body.state == "open" and approved:
            changed = await svc.move(db, session, "requested", state="open",
                                     opened_at=session.opened_at or now, error=None) or changed
        elif session.state == "open" and body.state != "open":
            # 切れた。端末がつなぎ直す
            changed = await svc.move(db, session, "open", state="requested") or changed
        if session.state == "requested":
            error = (body.error or "").strip()[:255] or None
            if error != session.error:
                changed = await svc.move(db, session, "requested", error=error) or changed
    if changed:
        await db.commit()

    want = bool(session is not None and session.state in svc.LIVE_STATES and approved)
    out = {
        "enabled": True,
        "want": want,
        "poll_sec": (ACTIVE_POLL_SEC if session is not None and session.state != "closed"
                     else max(10, settings.tunnel_idle_poll_sec)),
        # つなぎ先は開いていないときも返す(端末が「届くかどうか」を前もって確かめる)
        "host": settings.tunnel_bastion_host,
        "port": settings.tunnel_bastion_port,
        "user": settings.tunnel_bastion_user,
        "host_key": svc.clean_pubkey(settings.tunnel_bastion_host_key) or "",
    }
    if want:
        out["remote_port"] = session.port
        out["ttl_sec"] = max(0, int((to_naive_utc(session.expires_at) - now).total_seconds()))
    return out


# ── 踏み台 ────────────────────────────────────────────────────────────────────

def _require_bastion(authorization: str | None) -> None:
    secret = settings.tunnel_bastion_secret
    if not settings.tunnel_enabled or not secret:
        raise HTTPException(status_code=404, detail="Not found")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not given or not hmac.compare_digest(given.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/bastion/authorized-keys", response_class=PlainTextResponse)
async def bastion_authorized_keys(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """踏み台の sshd(AuthorizedKeysCommand)が、端末がつなぎに来るたびに聞きに来る。

    返すのは「いま開けと言われている端末」の鍵だけ。それ以外の端末は、鍵を持っていても
    踏み台へつなげない。"""
    _require_bastion(authorization)
    grants = await svc.live_grants(db, utcnow_naive())
    return "".join(svc.authorized_keys_line(port, key) + "\n" for port, key in grants)


@router.get("/bastion/active-ports")
async def bastion_active_ports(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """踏み台の見回り(1 分ごと)が聞きに来る。ここに無い転送口は踏み台が切る
    (端末が終了の指示を受け取れなくても、経路は閉じる)。"""
    _require_bastion(authorization)
    grants = await svc.live_grants(db, utcnow_naive())
    return {"ports": sorted(port for port, _ in grants)}
