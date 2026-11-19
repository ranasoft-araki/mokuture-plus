"""遠隔ログイン(運営が、問題の起きた端末へ必要なときだけ SSH で入る)の決まりごと。

経路の全体:
  運営パネルで「開く」 → 端末の常駐(kiosk_agent/tunnel_agent.py)が次に聞きに来たとき
  それを受け取る → 端末が踏み台サーバーへ外向きに SSH をつなぎ、逆向きの転送口を開く
  → 運営は踏み台を経由して、その転送口から端末へ SSH で入る → 「終了」か時間切れで閉じる。

この API が握るのは「どの端末を、いつまで、つながせてよいか」だけ。端末へ入るための鍵は
ここには無い(運営それぞれの SSH の鍵で、踏み台と端末が確かめる)。この API が乗っ取られても、
できるのは端末に踏み台へつながせることまでで、端末の中へは入れない。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.device import Device
from app.models.tunnel import TunnelSession
from app.services.timeutil import to_naive_utc

# 端末がつなぎに来てよい状態(踏み台が鍵を通す・転送口を残す)
LIVE_STATES = ("requested", "open")
# まだ片づいていない状態
PENDING_STATES = ("requested", "open", "closing")

# 終了を頼んでから、端末の「閉じた」を待つ時間。過ぎたら記録の上では閉じたことにする
# (踏み台は LIVE_STATES でなくなった時点で、その転送口を 1 分以内に切っている)。
CLOSE_CONFIRM_SEC = 180

# ed25519 の公開鍵だけを受け付ける。この文字列は踏み台の authorized_keys の行として
# そのまま出すので、形を厳密に決める(空白・改行・オプションを紛れ込ませない)。
_ED25519 = re.compile(r"^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5[A-Za-z0-9+/]{48}$")
_LOGIN_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def clean_pubkey(value: str | None) -> str | None:
    """「ssh-ed25519 AAAA... コメント」から種類と本体だけを取り出す。形が違えば None。"""
    parts = (value or "").split()
    if len(parts) < 2:
        return None
    key = f"{parts[0]} {parts[1]}"
    return key if _ED25519.match(key) else None


def clean_login_user(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _LOGIN_USER.match(value) else None


async def move(db: AsyncSession, session: TunnelSession, expect: str, **values) -> bool:
    """記録を書き換える。ただし、読んだときの状態(expect)のままのときだけ。書けたら True。

    記録の書き換えは必ずここを通す。端末の問い合わせ(5 秒ごと)と運営の操作は同時に届く。
    読んだ値を元にそのまま書き戻すと、あいだに入った「終了」を「接続中」で上書きしてしまい、
    画面は終了待ちなのに踏み台は鍵を通し続ける。書けなかったときは最新の状態を読み直す。"""
    result = await db.execute(
        update(TunnelSession)
        .where(TunnelSession.id == session.id, TunnelSession.state == expect)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(session)
    return result.rowcount == 1


async def settle(db: AsyncSession, session: TunnelSession, now: datetime) -> bool:
    """時間の経過で決まる状態の移り変わりを当てる。変えたら True(呼んだ側が commit する)。"""
    changed = False
    if session.state in LIVE_STATES and now >= to_naive_utc(session.expires_at):
        changed = await move(db, session, session.state, state="closing",
                             close_requested_at=now, close_reason="expired") or changed
    if session.state == "closing":
        asked = to_naive_utc(session.close_requested_at) or now
        if (now - asked).total_seconds() >= CLOSE_CONFIRM_SEC:
            changed = await move(
                db, session, "closing", state="closed", closed_at=now,
                error="端末から「閉じた」の報告が届きませんでした（踏み台側の経路は切断済み）",
            ) or changed
    return changed


async def pending_sessions(db: AsyncSession, device_id: str) -> list[TunnelSession]:
    """その端末の、まだ片づいていない遠隔ログイン(新しい順。一意インデックスにより 1 件まで)。"""
    return list((await db.execute(
        select(TunnelSession)
        .where(TunnelSession.device_id == device_id, TunnelSession.state.in_(PENDING_STATES))
        .order_by(TunnelSession.requested_at.desc())
    )).scalars().all())


async def pending_session(db: AsyncSession, device_id: str) -> TunnelSession | None:
    rows = await pending_sessions(db, device_id)
    return rows[0] if rows else None


async def allocate_port(db: AsyncSession, device: Device) -> int | None:
    """踏み台の上の転送口を端末に割り当てる(一度決めたら変えない)。空きが無ければ None。"""
    if device.tunnel_port:
        return device.tunnel_port
    used = set((await db.execute(
        select(Device.tunnel_port).where(Device.tunnel_port.is_not(None))
    )).scalars().all())
    base = settings.tunnel_port_base
    for port in range(base, base + settings.tunnel_port_count):
        if port not in used:
            device.tunnel_port = port
            return port
    return None


async def live_grants(db: AsyncSession, now: datetime) -> list[tuple[int, str]]:
    """いま踏み台へつないでよい端末の (転送口, 公開鍵)。"""
    rows = (await db.execute(
        select(TunnelSession, Device)
        .join(Device, Device.id == TunnelSession.device_id)
        .where(TunnelSession.state.in_(LIVE_STATES), TunnelSession.expires_at > now)
    )).all()
    grants = []
    for session, device in rows:
        key = clean_pubkey(device.tunnel_pubkey)
        # 転送口は要求のときに決めたもの。端末の行のものと食い違うなら通さない
        if key and device.tunnel_port and device.tunnel_port == session.port:
            grants.append((session.port, key))
    return grants


def authorized_keys_line(port: int, pubkey: str) -> str:
    """踏み台の sshd に渡す 1 行。この鍵でできるのは、決まった転送口を 1 つ開くことだけ。"""
    return f'restrict,port-forwarding,permitlisten="127.0.0.1:{int(port)}" {pubkey}'


def expiry(now: datetime, minutes: int) -> datetime:
    return now + timedelta(minutes=minutes)
