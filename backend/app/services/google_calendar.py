"""Google カレンダー連携(来社予定 ⇔ Google カレンダー)。→ CLAUDE.md「Google カレンダー連携」節。

テナントにつき Google アカウント 1 つ・カレンダー 1 つ・方向はどちらか一方。

- **to_google(mokuture → Google)**: mokuture で登録した来社予定を、選んだカレンダーへ書き出す。
  作成・変更は画面の操作の直後に送り(`push_appointment`)、送れなかった分と削除は定期同期が拾い直す。
  イベント ID は予約の UUID から作る(ハイフンを抜いた 32 桁の 16 進 = Google の base32hex の範囲内)
  ので、送り直しても二重にならない。イベントには `extendedProperties.private.mokuture_appointment_id`
  を付け、取り込み側でも「mokuture が書いた予定」だと分かるようにする。
  Google から取り込んだ予定(`gcal_origin="google"`)は書き出さない(相手の元の予定を書き換えないため)。
- **from_google(Google → mokuture)**: 選んだカレンダーの予定を来社予定として取り込む(定期同期)。
  Google が元なので、Google 側で変わった **氏名(=タイトル)・日時・所要時間** は取り込み直す。
  **担当者・会議室・会社名・メモは mokuture 側で付ける値なので、作るとき以外は上書きしない**
  (上書きすると、受付の担当者の割り当てが同期のたびに消える)。終日の予定は取り込まない。
  Google で消された・条件に合わなくなった予定は、まだ受付していない(pending)ものだけ消す。

日時: 来社予定の `scheduled_at` は **JST の壁時計(naive)**(管理画面のブラウザ時刻のまま保存される。
appointments.py `_fmt_scheduled_jp` 参照)。naive-UTC で統一している他の列とは違うので注意。
Google へは `+09:00` 付き + timeZone=Asia/Tokyo で送り、Google からは JST に直してから tz を外す。

秘密: refresh_token / access_token は Fernet 暗号化して保存し、API レスポンス・ログに出さない。

前提: 単一ワーカー(Dockerfile `--workers 1`)。テナントごとの同期は `_lock` で直列にする
(定期同期と「今すぐ同期」・画面操作直後の送信が同じ予定を同時に触らないように)。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.calendar_integration import CalendarEventTombstone, CalendarIntegration
from app.models.room import MeetingRoom
from app.models.tenant import Tenant
from app.models.visitor_appointment import VisitorAppointment
from app.services.crypto import decrypt_dict, encrypt_dict
from app.services.honorific import with_honorific
from app.services.timeutil import utcnow_naive

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/calendar/v3"
SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"
SCOPE_CALENDARLIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
SCOPES = (SCOPE_EVENTS, SCOPE_CALENDARLIST)

JST = timezone(timedelta(hours=9))
TZ_NAME = "Asia/Tokyo"
_HTTP_TIMEOUT = 15.0

# 取り込む期間(JST)。過去は 1 日前まで、先は 90 日。
PULL_DAYS_BEHIND = 1
PULL_DAYS_AHEAD = 90
# 1 回の取り込みで読むイベント一覧のページ数の上限(1 ページ 250 件)。
PULL_MAX_PAGES = 8
# 期間の一覧に出てこなかった取り込み済みの予定を個別に確かめる上限(期間外へ動かされた予定の追従)。
PULL_MAX_MISSING_CHECKS = 20
# 1 回の同期で書き出す予定・消すイベントの上限(異常時に一気に送らないための歯止め)。
PUSH_MAX_PER_SYNC = 100
# 送り直す対象にする来社予定の範囲(これより前の予定は書き出さない)。
PUSH_DAYS_BEHIND = 1
# 定期同期の最初の 1 回は起動からこの秒数後(再デプロイ直後に Google へ一斉に行かない)。
LOOP_INITIAL_DELAY_SEC = 30.0

_NOTE_MAX = 2000
_ERROR_MAX = 500


class GoogleAuthError(Exception):
    """Google 側で許可が取り消された・期限切れ(invalid_grant)。再連携が要る。"""


class GoogleOAuthError(Exception):
    """認可コードの交換に失敗した(コールバックで使う)。"""


class GoogleApiError(Exception):
    def __init__(self, status: int, reason: str = "", message: str = ""):
        super().__init__(f"google api error {status} {reason}")
        self.status = status
        self.reason = reason
        self.message = message or api_error_message(status, reason)


def enabled() -> bool:
    return settings.google_calendar_enabled


# ── HTTP(テストはここを差し替える) ─────────────────────────────────────────────

async def _http(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    json: Any = None,
    data: Optional[dict] = None,
) -> tuple[int, dict]:
    """Google へ 1 回だけ要求を送り (HTTP ステータス, JSON 本文) を返す。通信失敗は (0, {})。

    応答本文はトークンを含みうるので、ここでもログに出さない。"""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            res = await client.request(method, url, headers=headers, params=params, json=json, data=data)
    except Exception:
        return 0, {}
    try:
        body = res.json() if res.content else {}
    except ValueError:
        body = {}
    return res.status_code, body if isinstance(body, dict) else {}


def _reason(body: dict) -> str:
    err = body.get("error")
    if isinstance(err, dict):
        errs = err.get("errors")
        if isinstance(errs, list) and errs and isinstance(errs[0], dict) and errs[0].get("reason"):
            return str(errs[0]["reason"])
        return str(err.get("status") or "")
    return str(err or "")


def api_error_message(status: int, reason: str = "") -> str:
    """画面の「最後のエラー」に出す文言。Google の生の応答は出さない。"""
    if status == 0:
        return "Google カレンダーに接続できませんでした。自動で再試行します。"
    if status == 404:
        return ("選んだカレンダーが見つかりません。Google カレンダーで削除されたか、共有が外れた可能性があります。"
                "「同期するカレンダー」を選び直してください。")
    if status == 403 and reason in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"):
        return "Google の利用回数の上限に達しました。しばらくすると自動で再開します。"
    if status == 403:
        return ("このカレンダーに予定を書き込む権限がありません。Google カレンダーで編集の権限があるカレンダーを"
                "「同期するカレンダー」に選んでください。")
    return f"Google カレンダーとの同期に失敗しました（エラー {status}）。自動で再試行します。"


REAUTH_MESSAGE = ("Google アカウントの連携が切れました（Google 側で許可が取り消されたか、期限が切れました）。"
                  "「カレンダー連携」の「もう一度連携する」を押して、連携し直してください。")
UNEXPECTED_MESSAGE = "Google カレンダーとの同期中に予期しないエラーが起きました。自動で再試行します。"


# ── OAuth ──────────────────────────────────────────────────────────────────────

def build_authorize_url(state: str) -> str:
    # access_type=offline + prompt=consent: 2 回目以降の同意でも refresh_token を必ず受け取る。
    # select_account: ブラウザにログイン中のアカウントが 1 つでも選択画面を出す(別のアカウントに切り替えられるように)。
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "select_account consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def missing_scopes(granted: str) -> list[str]:
    """同意画面で外されたスコープ(Google は項目ごとにチェックを外せる)。"""
    have = set((granted or "").split())
    return [s for s in SCOPES if s not in have]


async def exchange_code(code: str) -> dict:
    """認可コード → {refresh_token, access_token, access_expires_at, scope}。失敗は GoogleOAuthError。"""
    status, body = await _http("POST", TOKEN_ENDPOINT, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    })
    if status != 200 or not body.get("access_token"):
        raise GoogleOAuthError(str(body.get("error") or f"status_{status}"))
    return {
        "refresh_token": body.get("refresh_token") or "",
        "access_token": body["access_token"],
        "access_expires_at": time.time() + float(body.get("expires_in") or 3600),
        "scope": body.get("scope") or "",
    }


async def revoke(token: str) -> None:
    """Google 側の許可も取り消す(best-effort。失敗しても連携の解除は進める)。"""
    if token:
        await _http("POST", REVOKE_ENDPOINT, data={"token": token})


def load_credentials(integ: CalendarIntegration) -> dict:
    raw = integ.credentials_json or "{}"
    if raw == "{}":
        return {}
    try:
        return decrypt_dict(raw)
    except Exception:
        return {}


def store_credentials(integ: CalendarIntegration, creds: dict) -> None:
    integ.credentials_json = encrypt_dict(creds) if creds else "{}"


def has_refresh_token(integ: CalendarIntegration) -> bool:
    return bool(load_credentials(integ).get("refresh_token"))


def is_active(integ: Optional[CalendarIntegration]) -> bool:
    """同期を動かしてよい状態か(連携済み・方向とカレンダーを選んである)。"""
    return bool(
        enabled()
        and integ is not None
        and integ.status == "active"
        and integ.direction in ("to_google", "from_google")
        and integ.calendar_id
        and has_refresh_token(integ)
    )


def record_error(integ: CalendarIntegration, message: Optional[str]) -> None:
    if message:
        integ.last_error = message[:_ERROR_MAX]
        integ.last_error_at = utcnow_naive()
    else:
        integ.last_error = None
        integ.last_error_at = None


async def access_token(db: AsyncSession, integ: CalendarIntegration, *, force_refresh: bool = False) -> str:
    """使えるアクセストークンを返す。期限が近ければ refresh_token で取り直して保存する。"""
    creds = load_credentials(integ)
    if (
        not force_refresh
        and creds.get("access_token")
        and float(creds.get("access_expires_at") or 0) > time.time() + 60
    ):
        return creds["access_token"]
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise GoogleAuthError("no refresh token")
    status, body = await _http("POST", TOKEN_ENDPOINT, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if status in (400, 401) and body.get("error") in ("invalid_grant", "unauthorized_client", "invalid_client"):
        # 許可が取り消された・テスト公開中の 7 日期限切れ等。黙って失敗し続けないよう画面に出して止める。
        integ.status = "reauth_required"
        record_error(integ, REAUTH_MESSAGE)
        await db.commit()
        raise GoogleAuthError(str(body.get("error")))
    if status != 200 or not body.get("access_token"):
        raise GoogleApiError(status, _reason(body))
    creds["access_token"] = body["access_token"]
    creds["access_expires_at"] = time.time() + float(body.get("expires_in") or 3600)
    if body.get("refresh_token"):  # 通常は返らないが、返ったら差し替える
        creds["refresh_token"] = body["refresh_token"]
    store_credentials(integ, creds)
    await db.commit()
    return creds["access_token"]


async def _call(
    db: AsyncSession,
    integ: CalendarIntegration,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json: Any = None,
) -> tuple[int, dict]:
    token = await access_token(db, integ)
    status, body = await _http(method, API_BASE + path, headers={"Authorization": f"Bearer {token}"},
                               params=params, json=json)
    if status == 401:  # 期限前に無効になったアクセストークン。1 回だけ取り直す。
        token = await access_token(db, integ, force_refresh=True)
        status, body = await _http(method, API_BASE + path, headers={"Authorization": f"Bearer {token}"},
                                   params=params, json=json)
    return status, body


def _q(s: str) -> str:
    return quote(s, safe="")


# ── カレンダー一覧 ─────────────────────────────────────────────────────────────

async def primary_calendar_id(db: AsyncSession, integ: CalendarIntegration) -> str:
    """連携したアカウントのメインのカレンダー ID(= Google アカウントのメールアドレス)。"""
    status, body = await _call(db, integ, "GET", "/users/me/calendarList/primary")
    if status != 200:
        raise GoogleApiError(status, _reason(body))
    return str(body.get("id") or "")


async def list_calendars(db: AsyncSession, integ: CalendarIntegration) -> list[dict]:
    """選べるカレンダー。Google の画面と同じく「マイカレンダー」(自分がオーナー)と「他のカレンダー」に分ける。"""
    items: list[dict] = []
    page: Optional[str] = None
    for _ in range(10):
        params: dict = {"minAccessRole": "reader", "maxResults": 250}
        if page:
            params["pageToken"] = page
        status, body = await _call(db, integ, "GET", "/users/me/calendarList", params=params)
        if status != 200:
            raise GoogleApiError(status, _reason(body))
        for it in body.get("items") or []:
            if not isinstance(it, dict) or it.get("deleted") or not it.get("id"):
                continue
            role = str(it.get("accessRole") or "")
            items.append({
                "id": str(it["id"]),
                "name": str(it.get("summaryOverride") or it.get("summary") or it["id"]),
                "primary": bool(it.get("primary")),
                "access_role": role,
                "writable": role in ("owner", "writer"),
                "group": "mine" if role == "owner" else "other",
                "color": it.get("backgroundColor") or None,
            })
        page = body.get("nextPageToken")
        if not page:
            break
    items.sort(key=lambda c: (not c["primary"], c["group"] != "mine", c["name"]))
    return items


# ── 日時 ───────────────────────────────────────────────────────────────────────

def jst_wall_to_rfc3339(dt: datetime) -> str:
    """来社予定の scheduled_at(JST 壁時計・naive) → '2026-11-20T10:00:00+09:00'。"""
    return dt.replace(tzinfo=JST, microsecond=0).isoformat()


def event_time_to_jst_wall(t: Optional[dict]) -> Optional[datetime]:
    """Google の start/end → JST の壁時計(naive)。終日の予定(date だけ)は None。"""
    if not isinstance(t, dict):
        return None
    s = t.get("dateTime")
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:  # RFC3339 なので通常は付いている。無ければ JST とみなす
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST).replace(tzinfo=None, microsecond=0)


def wall(dt: datetime) -> datetime:
    """来社予定の scheduled_at を naive の壁時計にそろえる(aware で読み戻っても数字はそのまま)。"""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def now_jst_wall() -> datetime:
    return datetime.now(JST).replace(tzinfo=None, microsecond=0)


# ── mokuture → Google ─────────────────────────────────────────────────────────

_EVENT_ID_RE = re.compile(r"^[a-v0-9]{5,1024}$")


def event_id_for(appt: VisitorAppointment) -> str:
    eid = appt.id.replace("-", "").lower()
    return eid if _EVENT_ID_RE.match(eid) else ""


def _room_label(room: Optional[MeetingRoom]) -> str:
    if room is None:
        return ""
    return room.name + (f"（{room.location}）" if room.location else "")


def build_event(appt: VisitorAppointment, room: Optional[MeetingRoom]) -> dict:
    """書き出すイベントの本文。QR の予約コード(token)は入れない(カレンダーの共有先に渡さない)。"""
    start = wall(appt.scheduled_at)
    minutes = appt.duration_minutes if appt.duration_minutes and appt.duration_minutes > 0 else 60
    end = start + timedelta(minutes=minutes)
    who = with_honorific(appt.visitor_name)
    summary = f"【来社】{appt.company} {who}" if appt.company else f"【来社】{who}"
    lines: list[str] = [f"お名前：{who}"]
    if appt.company:
        lines.append(f"会社名：{appt.company}")
    if appt.purpose:
        lines.append(f"ご用件：{appt.purpose}")
    if appt.staff:
        lines.append(f"担当：{appt.staff}")
    if room is not None:
        lines.append(f"会議室：{_room_label(room)}")
    if appt.notes:
        lines.append(f"メモ：{appt.notes}")
    lines += [
        "",
        "mokuture+ の「来社予定」から自動で登録した予定です。",
        "内容の変更は mokuture+ の「来社予定」で行ってください（ここで変えても mokuture+ には反映されず、"
        "次に来社予定を変更したときに上書きされます）。",
    ]
    return {
        "summary": summary[:1024],
        "description": "\n".join(lines)[:8000],
        "location": _room_label(room),
        "start": {"dateTime": jst_wall_to_rfc3339(start), "timeZone": TZ_NAME},
        "end": {"dateTime": jst_wall_to_rfc3339(end), "timeZone": TZ_NAME},
        "status": "confirmed",
        "extendedProperties": {"private": {"mokuture_appointment_id": appt.id}},
    }


async def _push_one(
    db: AsyncSession, integ: CalendarIntegration, appt: VisitorAppointment, room: Optional[MeetingRoom]
) -> Optional[str]:
    """1 件を書き出す。成功なら None、失敗なら画面に出す文言を返す(予定には error を付ける)。"""
    cal = integ.calendar_id or ""
    body = build_event(appt, room)
    linked = bool(appt.gcal_event_id) and appt.gcal_calendar_id == cal
    events = f"/calendars/{_q(cal)}/events"

    if linked:
        status, resp = await _call(db, integ, "PATCH", f"{events}/{_q(appt.gcal_event_id)}", json=body)
        if status in (404, 410):  # Google 側で完全に消えていた → 作り直す(ID は Google に任せる)
            status, resp = await _call(db, integ, "POST", events, json=body)
    else:
        eid = event_id_for(appt)
        status, resp = await _call(db, integ, "POST", events, json={**body, "id": eid} if eid else body)
        if status == 409 and eid:  # 前回送れたが記録できなかった・一度消した同じ ID → 上書きで戻す
            status, resp = await _call(db, integ, "PATCH", f"{events}/{_q(eid)}", json=body)
            if status in (404, 410):
                status, resp = await _call(db, integ, "POST", events, json=body)

    if status == 200 and resp.get("id"):
        appt.gcal_event_id = str(resp["id"])
        appt.gcal_calendar_id = cal
        appt.gcal_updated = str(resp.get("updated") or "") or None
        appt.gcal_sync_state = "synced"
        return None
    appt.gcal_sync_state = "error"
    return api_error_message(status, _reason(resp))


async def _process_deletes(db: AsyncSession, integ: CalendarIntegration) -> tuple[int, int, Optional[str]]:
    rows = (await db.execute(
        select(CalendarEventTombstone)
        .where(CalendarEventTombstone.tenant_id == integ.tenant_id, CalendarEventTombstone.kind == "delete")
        .order_by(CalendarEventTombstone.created_at)
        .limit(PUSH_MAX_PER_SYNC)
    )).scalars().all()
    done = failed = 0
    last_err: Optional[str] = None
    for t in rows:
        status, resp = await _call(db, integ, "DELETE", f"/calendars/{_q(t.calendar_id)}/events/{_q(t.event_id)}")
        # 404/410 = もう無い。403 でカレンダーへの権限を失った場合も、消しようが無いので片付ける。
        if status in (200, 204, 404, 410) or (status == 403 and _reason(resp) not in (
            "rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded")):
            await db.delete(t)
            done += 1
        else:
            failed += 1
            last_err = api_error_message(status, _reason(resp))
        await db.commit()
    return done, failed, last_err


async def _push_pending(db: AsyncSession, integ: CalendarIntegration) -> "SyncResult":
    res = SyncResult()
    done, failed, err = await _process_deletes(db, integ)
    res.removed += done
    res.failed += failed
    res.error = err or res.error

    since = now_jst_wall() - timedelta(days=PUSH_DAYS_BEHIND)
    rows = (await db.execute(
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(MeetingRoom, (VisitorAppointment.meeting_room_id == MeetingRoom.id)
                   & (MeetingRoom.tenant_id == integ.tenant_id))
        .where(
            VisitorAppointment.tenant_id == integ.tenant_id,
            VisitorAppointment.gcal_origin.is_(None),
            VisitorAppointment.scheduled_at >= since,
            or_(
                VisitorAppointment.gcal_sync_state.is_(None),
                VisitorAppointment.gcal_sync_state.in_(("pending", "error")),
                VisitorAppointment.gcal_calendar_id.is_(None),
                VisitorAppointment.gcal_calendar_id != integ.calendar_id,
            ),
        )
        .order_by(VisitorAppointment.scheduled_at)
        .limit(PUSH_MAX_PER_SYNC)
    )).all()
    for appt, room in rows:
        err = await _push_one(db, integ, appt, room)
        if err:
            res.failed += 1
            res.error = err
        else:
            res.pushed += 1
        await db.commit()
    return res


# ── Google → mokuture ─────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*(br|/p|/div|/li)\s*/?\s*>", re.IGNORECASE)


def _plain(description: Optional[str]) -> Optional[str]:
    """Google の説明欄(HTML のことがある)をメモ用の素の文字にする。"""
    if not description:
        return None
    s = _BR_RE.sub("\n", str(description))
    s = unescape(_TAG_RE.sub("", s)).strip()
    return s[:_NOTE_MAX] or None


_EDGE_RE = re.compile(r"^[\s:：・\-－/／|｜]+|[\s:：・\-－/／|｜]+$")


def visitor_name_from_title(summary: Optional[str], keyword: str = "") -> str:
    """予定のタイトル → 来社予定の「お名前」。キオスク・通知に「【来社】B社 田中様 様」と出ないよう、
    取り込みの言葉(例: 来社)と、それを囲む【】[]「」と区切り記号を外す。何も残らなければ元のタイトル。
    外すのは括弧で囲まれたものと、タイトルの頭・お尻にあるものだけ(「社」のような短い言葉でも
    「ABC社 田中様」の途中を削らないように)。"""
    original = re.sub(r"\s+", " ", (summary or "")).strip()
    name = original
    if keyword:
        for open_, close in (("【", "】"), ("[", "]"), ("［", "］"), ("「", "」"), ("(", ")"), ("（", "）")):
            name = name.replace(f"{open_}{keyword}{close}", " ")
        name = _EDGE_RE.sub("", name)
        if name.startswith(keyword):
            name = name[len(keyword):]
        if name.endswith(keyword):
            name = name[: -len(keyword)]
    name = _EDGE_RE.sub("", re.sub(r"\s+", " ", name)).strip()
    return (name or original)[:255] or "（タイトルなし）"


def _match_room(location: Optional[str], rooms: list[MeetingRoom]) -> Optional[str]:
    """Google の「場所」に会議室名が含まれていればその会議室(長い名前を優先)。"""
    loc = (location or "").strip()
    if not loc:
        return None
    for room in sorted(rooms, key=lambda r: len(r.name or ""), reverse=True):
        if room.name and room.name in loc:
            return room.id
    return None


def _declined_by_me(ev: dict) -> bool:
    for a in ev.get("attendees") or []:
        if isinstance(a, dict) and a.get("self") and a.get("responseStatus") == "declined":
            return True
    return False


def _duration(start: datetime, end: Optional[datetime]) -> int:
    if end is None or end <= start:
        return 60
    return max(1, min(int((end - start).total_seconds() // 60), 24 * 60))


async def _list_window(db: AsyncSession, integ: CalendarIntegration) -> list[dict]:
    now = now_jst_wall()
    params: dict = {
        "singleEvents": "true",
        "showDeleted": "true",
        "timeMin": jst_wall_to_rfc3339(now - timedelta(days=PULL_DAYS_BEHIND)),
        "timeMax": jst_wall_to_rfc3339(now + timedelta(days=PULL_DAYS_AHEAD)),
        "maxResults": 250,
    }
    out: list[dict] = []
    for _ in range(PULL_MAX_PAGES):
        status, body = await _call(db, integ, "GET", f"/calendars/{_q(integ.calendar_id or '')}/events",
                                   params=params)
        if status != 200:
            raise GoogleApiError(status, _reason(body))
        out += [e for e in body.get("items") or [] if isinstance(e, dict) and e.get("id")]
        page = body.get("nextPageToken")
        if not page:
            break
        params["pageToken"] = page
    return out


def _should_remove(ev: dict, keyword: str) -> bool:
    """この予定を来社予定として持たない(消す・作らない)べきか。"""
    if ev.get("status") == "cancelled":
        return True
    if event_time_to_jst_wall(ev.get("start")) is None:  # 終日
        return True
    if ev.get("eventType") not in (None, "", "default"):  # 不在・集中時間・勤務場所・Gmail からの予定
        return True
    if keyword and keyword not in str(ev.get("summary") or ""):
        return True
    return _declined_by_me(ev)


async def _pull(db: AsyncSession, integ: CalendarIntegration) -> "SyncResult":
    res = SyncResult()
    tid = integ.tenant_id
    cal = integ.calendar_id or ""
    keyword = (integ.import_keyword or "").strip()
    events = await _list_window(db, integ)

    linked: dict[str, VisitorAppointment] = {
        a.gcal_event_id: a
        for a in (await db.execute(
            select(VisitorAppointment).where(
                VisitorAppointment.tenant_id == tid,
                VisitorAppointment.gcal_event_id.is_not(None),
            )
        )).scalars().all()
        if a.gcal_event_id
    }
    ignored = set((await db.execute(
        select(CalendarEventTombstone.event_id).where(
            CalendarEventTombstone.tenant_id == tid, CalendarEventTombstone.kind == "ignore"
        )
    )).scalars().all())
    rooms = list((await db.execute(select(MeetingRoom).where(MeetingRoom.tenant_id == tid))).scalars().all())
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
    staff_names = {s.strip() for s in ((tenant.staff_list if tenant else "") or "").split(",") if s.strip()}
    default_staff = integ.default_staff if integ.default_staff in staff_names else None

    seen: set[str] = set()
    for ev in events:
        eid = str(ev["id"])
        seen.add(eid)
        mid = ((ev.get("extendedProperties") or {}).get("private") or {}).get("mokuture_appointment_id")
        appt = linked.get(eid)
        if appt is None and mid:
            appt = (await db.execute(select(VisitorAppointment).where(
                VisitorAppointment.id == str(mid), VisitorAppointment.tenant_id == tid
            ))).scalar_one_or_none()
            if appt is not None and appt.gcal_event_id and appt.gcal_event_id != eid:
                appt = None  # 別のイベントに結び付いている予定は奪わない
        await _apply_event(db, integ, ev, appt, res, keyword=keyword, rooms=rooms,
                           default_staff=default_staff, ignored=ignored, from_mokuture=bool(mid))

    # 期間の一覧に出てこなかった、取り込み済み・未受付の先の予定(期間外へ動かされた等)を個別に確かめる。
    now = now_jst_wall()
    lo, hi = now - timedelta(days=PULL_DAYS_BEHIND), now + timedelta(days=PULL_DAYS_AHEAD)
    missing = sorted(
        (a for a in linked.values()
         if a.gcal_event_id not in seen and a.gcal_calendar_id == cal and a.status == "pending"
         and lo <= wall(a.scheduled_at) <= hi),
        key=lambda a: wall(a.scheduled_at),
    )[:PULL_MAX_MISSING_CHECKS]
    for appt in missing:
        status, ev = await _call(db, integ, "GET", f"/calendars/{_q(cal)}/events/{_q(appt.gcal_event_id or '')}")
        if status in (404, 410):
            ev = {"id": appt.gcal_event_id, "status": "cancelled"}
        elif status != 200:
            res.failed += 1
            res.error = api_error_message(status, _reason(ev))
            continue
        await _apply_event(db, integ, ev, appt, res, keyword=keyword, rooms=rooms, default_staff=default_staff,
                           ignored=ignored, from_mokuture=False)

    # 日時を過ぎた「取り込まない」印は掃除する。
    await db.execute(delete(CalendarEventTombstone).where(
        CalendarEventTombstone.tenant_id == tid,
        CalendarEventTombstone.kind == "ignore",
        CalendarEventTombstone.scheduled_at < now_jst_wall() - timedelta(days=PULL_DAYS_BEHIND + 1),
    ))
    await db.commit()
    return res


async def _apply_event(
    db: AsyncSession,
    integ: CalendarIntegration,
    ev: dict,
    appt: Optional[VisitorAppointment],
    res: "SyncResult",
    *,
    keyword: str,
    rooms: list[MeetingRoom],
    default_staff: Optional[str],
    ignored: set[str],
    from_mokuture: bool,
) -> None:
    eid = str(ev["id"])
    cal = integ.calendar_id or ""
    if _should_remove(ev, keyword):
        # まだ受付していない予定だけ消す(受付済みは記録として残す)。mokuture で作った予定は、
        # Google で消されたときだけ消す(終日・キーワードは取り込みの条件なので当てはめない)。
        if appt is not None and appt.status == "pending" and appt.gcal_calendar_id == cal and (
            appt.gcal_origin == "google" or ev.get("status") == "cancelled"
        ):
            await db.delete(appt)
            res.removed += 1
        return

    start = event_time_to_jst_wall(ev.get("start"))
    assert start is not None  # _should_remove が終日を落としている
    end = event_time_to_jst_wall(ev.get("end"))
    updated = str(ev.get("updated") or "") or None

    if appt is None:
        # mokuture が書いたイベントの元の予定が無い = mokuture で消した予定。作り直さない。
        if eid in ignored or from_mokuture:
            return
        db.add(VisitorAppointment(
            tenant_id=integ.tenant_id,
            visitor_name=visitor_name_from_title(ev.get("summary"), keyword),
            staff=default_staff,
            meeting_room_id=_match_room(ev.get("location"), rooms),
            scheduled_at=start,
            duration_minutes=_duration(start, end),
            notes=_plain(ev.get("description")),
            gcal_event_id=eid,
            gcal_calendar_id=cal,
            gcal_origin="google",
            gcal_updated=updated,
            gcal_sync_state="synced",
        ))
        res.imported += 1
        return

    if appt.status != "pending":
        return  # 受付済み・期限切れは当時の記録として触らない
    if appt.gcal_event_id == eid and appt.gcal_calendar_id == cal and appt.gcal_updated == updated:
        return  # 変わっていない
    if appt.gcal_origin == "google":
        appt.visitor_name = visitor_name_from_title(ev.get("summary"), keyword)
    appt.scheduled_at = start
    appt.duration_minutes = _duration(start, end)
    appt.gcal_event_id = eid
    appt.gcal_calendar_id = cal
    appt.gcal_updated = updated
    appt.gcal_sync_state = "synced"
    res.updated += 1


# ── 同期の入口 ─────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    pushed: int = 0
    imported: int = 0
    updated: int = 0
    removed: int = 0
    failed: int = 0
    error: Optional[str] = None
    skipped: bool = False

    def as_dict(self) -> dict:
        return {
            "pushed": self.pushed, "imported": self.imported, "updated": self.updated,
            "removed": self.removed, "failed": self.failed, "error": self.error, "skipped": self.skipped,
        }


_locks: dict[str, asyncio.Lock] = {}


def tenant_lock(tenant_id: str) -> asyncio.Lock:
    """テナントごとの同期の鍵。同期・画面操作直後の送信・設定の保存が同じ予定を同時に触らないように。"""
    return _lock(tenant_id)


def _lock(tenant_id: str) -> asyncio.Lock:
    lock = _locks.get(tenant_id)
    if lock is None:
        lock = _locks[tenant_id] = asyncio.Lock()
    return lock


async def load_integration(db: AsyncSession, tenant_id: str) -> Optional[CalendarIntegration]:
    return (await db.execute(
        select(CalendarIntegration).where(CalendarIntegration.tenant_id == tenant_id)
    )).scalar_one_or_none()


async def sync_tenant(tenant_id: str) -> SyncResult:
    """そのテナントの同期を 1 回行う(定期同期・「今すぐ同期」・設定の保存直後)。"""
    async with _lock(tenant_id):
        async with AsyncSessionLocal() as db:
            integ = await load_integration(db, tenant_id)
            if not is_active(integ):
                return SyncResult(skipped=True)
            assert integ is not None
            try:
                res = await (_push_pending(db, integ) if integ.direction == "to_google" else _pull(db, integ))
            except GoogleAuthError:
                return SyncResult(failed=1, error=REAUTH_MESSAGE)
            except Exception as e:
                message = e.message if isinstance(e, GoogleApiError) else UNEXPECTED_MESSAGE
                if not isinstance(e, GoogleApiError):
                    logger.warning("google calendar sync error (tenant=%s): %s", tenant_id, type(e).__name__)
                await db.rollback()
                integ = await load_integration(db, tenant_id)
                if integ is not None:
                    record_error(integ, message)
                    await db.commit()
                return SyncResult(failed=1, error=message)
            integ.last_synced_at = utcnow_naive()
            record_error(integ, res.error if res.failed else None)
            await db.commit()
            return res


async def push_appointment(tenant_id: str, appointment_id: str) -> None:
    """来社予定を登録・変更した直後に、その 1 件を Google へ送る(BackgroundTasks から呼ぶ)。

    書き出し中でなければ何もしない。失敗しても予定には error が残り、定期同期が送り直す。"""
    try:
        async with _lock(tenant_id):
            async with AsyncSessionLocal() as db:
                integ = await load_integration(db, tenant_id)
                if not is_active(integ) or integ.direction != "to_google":
                    return
                row = (await db.execute(
                    select(VisitorAppointment, MeetingRoom)
                    .outerjoin(MeetingRoom, (VisitorAppointment.meeting_room_id == MeetingRoom.id)
                               & (MeetingRoom.tenant_id == tenant_id))
                    .where(VisitorAppointment.id == appointment_id, VisitorAppointment.tenant_id == tenant_id)
                )).one_or_none()
                if row is None or row[0].gcal_origin == "google":
                    return
                appt, room = row
                err = await _push_one(db, integ, appt, room)
                if err:
                    record_error(integ, err)
                else:
                    integ.last_synced_at = utcnow_naive()
                await db.commit()
    except GoogleAuthError:
        return
    except Exception:
        logger.warning("google calendar push failed (tenant=%s)", tenant_id, exc_info=False)


async def process_deletes(tenant_id: str) -> None:
    """来社予定を消した直後に、Google 側のイベントを消す(BackgroundTasks から呼ぶ)。"""
    try:
        async with _lock(tenant_id):
            async with AsyncSessionLocal() as db:
                integ = await load_integration(db, tenant_id)
                if not is_active(integ) or integ.direction != "to_google":
                    return
                _done, failed, err = await _process_deletes(db, integ)
                if failed:
                    record_error(integ, err)
                    await db.commit()
    except GoogleAuthError:
        return
    except Exception:
        logger.warning("google calendar delete failed (tenant=%s)", tenant_id, exc_info=False)


async def note_appointment_deleted(db: AsyncSession, appt: VisitorAppointment) -> bool:
    """来社予定を消す前に呼ぶ。Google 側の後始末が要るなら印を残し、送る必要があれば True を返す。

    - 取り込んだ予定 → 次の取り込みで作り直さない印(ignore)。
    - 書き出し中に mokuture の予定を消した → Google のイベントを消す印(delete)。
    呼び出し元がこのあと予定の削除と一緒に commit する。"""
    if appt.gcal_origin == "google":
        if appt.gcal_event_id and appt.gcal_calendar_id:
            db.add(CalendarEventTombstone(
                tenant_id=appt.tenant_id, kind="ignore", calendar_id=appt.gcal_calendar_id,
                event_id=appt.gcal_event_id, scheduled_at=wall(appt.scheduled_at),
            ))
        return False
    integ = await load_integration(db, appt.tenant_id)
    if not is_active(integ) or integ.direction != "to_google":
        return False
    assert integ is not None
    if appt.gcal_event_id and appt.gcal_calendar_id:
        cal, eid = appt.gcal_calendar_id, appt.gcal_event_id
    else:
        # 作成直後に消した: 画面操作の直後の送信がこれから(または送信中に)イベントを作るかもしれない。
        # ID は予約から決まるので、その ID で消しに行く(無ければ 404 で片付く)。
        cal, eid = integ.calendar_id or "", event_id_for(appt)
    if not cal or not eid:
        return False
    db.add(CalendarEventTombstone(
        tenant_id=appt.tenant_id, kind="delete", calendar_id=cal, event_id=eid,
        scheduled_at=wall(appt.scheduled_at),
    ))
    return True


async def unlink_all(db: AsyncSession, tenant_id: str) -> int:
    """別の Google アカウントで結び直し、前に選んでいたカレンダーがそのアカウントから見えないとき。

    イベント ID はカレンダーのものなので、見えなくなったカレンダーとの結び付きは役に立たない。
    - mokuture で登録した予定 → 結び付きを外して「まだ送っていない」に戻す(新しいカレンダーへ書き直せる)
    - 取り込んだ予定 → まだ受付していないこれからの予定は消す(残すと二度と更新されない孤児になり、
      同じカレンダーを後で選び直したときに二重に取り込まれる)。受付済み・過去の予定は記録として残す。
    消した数を返す。"""
    stale = (await db.execute(select(VisitorAppointment).where(
        VisitorAppointment.tenant_id == tenant_id,
        VisitorAppointment.gcal_origin == "google",
        VisitorAppointment.status == "pending",
        VisitorAppointment.scheduled_at >= now_jst_wall(),
    ))).scalars().all()
    for a in stale:
        await db.delete(a)
    await db.execute(
        update(VisitorAppointment)
        .where(VisitorAppointment.tenant_id == tenant_id, VisitorAppointment.gcal_origin.is_(None))
        .values(gcal_event_id=None, gcal_calendar_id=None, gcal_updated=None, gcal_sync_state="pending")
    )
    await db.execute(
        update(VisitorAppointment)
        .where(VisitorAppointment.tenant_id == tenant_id, VisitorAppointment.gcal_origin == "google")
        .values(gcal_event_id=None, gcal_calendar_id=None, gcal_updated=None)
    )
    await db.execute(delete(CalendarEventTombstone).where(CalendarEventTombstone.tenant_id == tenant_id))
    return len(stale)


async def run_sync_loop() -> None:
    """アプリのライフサイクルに紐づく常駐ループ(`main.lifespan` が起動・停止する)。単一ワーカー前提。"""
    interval = max(60, int(settings.google_calendar_sync_interval_sec or 300))
    await asyncio.sleep(LOOP_INITIAL_DELAY_SEC)
    while True:
        try:
            if enabled():
                async with AsyncSessionLocal() as db:
                    tenant_ids = (await db.execute(
                        select(CalendarIntegration.tenant_id).where(
                            CalendarIntegration.status == "active",
                            CalendarIntegration.direction.is_not(None),
                            CalendarIntegration.calendar_id.is_not(None),
                        )
                    )).scalars().all()
                for tid in tenant_ids:
                    try:
                        await sync_tenant(tid)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.warning("google calendar sync failed (tenant=%s)", tid, exc_info=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("google calendar sync loop failed", exc_info=False)
        await asyncio.sleep(interval)
