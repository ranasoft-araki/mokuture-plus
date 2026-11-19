"""Google カレンダー連携(services/google_calendar.py・api/calendar_integration.py)。

Google へは出さない: `google_calendar._http` を、メモリ上にカレンダーとイベントを持つ偽物に差し替える。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.calendar_integration import CalendarEventTombstone, CalendarIntegration
from app.models.room import MeetingRoom
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment
from app.services import google_calendar as gcal
from app.services.auth import create_access_token, create_google_state_token
from jose import jwt as jose_jwt

from conftest import set_staff_list

API = "/api/integrations/google-calendar"
PRIMARY = "owner@example.test"
TEAM = "team@group.calendar.google.com"
HOLIDAYS = "ja.japanese#holiday@group.v.calendar.google.com"


class FakeGoogle:
    """Google の OAuth・Calendar API の最小限の偽物。"""

    def __init__(self) -> None:
        self.calendars = [
            {"id": PRIMARY, "summary": PRIMARY, "primary": True, "accessRole": "owner"},
            {"id": TEAM, "summary": "来客用", "accessRole": "owner"},
            {"id": HOLIDAYS, "summary": "日本の祝日", "accessRole": "reader"},
        ]
        self.events: dict[str, dict[str, dict]] = {PRIMARY: {}, TEAM: {}, HOLIDAYS: {}}
        self.calls: list[tuple[str, str]] = []
        self.granted_scope = " ".join(gcal.SCOPES)
        self.refresh_error: str | None = None
        self.fail_writes = 0  # 書き込みをこの回数だけ 500 で失敗させる
        self.email = PRIMARY
        self._seq = 0

    def _stamp(self) -> str:
        self._seq += 1
        return f"2026-11-19T00:00:{self._seq:02d}.000Z"

    async def __call__(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append((method, url))
        if url == gcal.TOKEN_ENDPOINT:
            if data.get("grant_type") == "authorization_code":
                return 200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                             "scope": self.granted_scope}
            if self.refresh_error:
                return 400, {"error": self.refresh_error}
            return 200, {"access_token": "at-2", "expires_in": 3600}
        if url == gcal.REVOKE_ENDPOINT:
            return 200, {}
        assert headers and headers["Authorization"].startswith("Bearer ")
        path = unquote(urlparse(url).path).replace("/calendar/v3", "")
        if path == "/users/me/calendarList/primary":
            return 200, {"id": self.email}
        if path == "/users/me/calendarList":
            return 200, {"items": self.calendars}
        parts = urlparse(url).path.replace("/calendar/v3", "").split("/")
        # /calendars/{cal}/events[/{id}]
        cal = unquote(parts[2])
        store = self.events.setdefault(cal, {})
        eid = unquote(parts[4]) if len(parts) > 4 else None
        if method in ("POST", "PATCH", "DELETE") and self.fail_writes > 0:
            self.fail_writes -= 1
            return 500, {"error": {"errors": [{"reason": "backendError"}]}}
        if method == "GET" and eid is None:
            return 200, {"items": list(store.values())}
        if method == "GET":
            return (200, store[eid]) if eid in store else (404, {})
        if method == "POST":
            new_id = json.get("id") or uuid.uuid4().hex
            if new_id in store:
                return 409, {"error": {"errors": [{"reason": "duplicate"}]}}
            store[new_id] = {**json, "id": new_id, "updated": self._stamp()}
            return 200, store[new_id]
        if method == "PATCH":
            if eid not in store:
                return 404, {}
            store[eid] = {**store[eid], **json, "updated": self._stamp()}
            return 200, store[eid]
        if method == "DELETE":
            if eid not in store:
                return 410, {}
            store[eid]["status"] = "cancelled"
            return 204, {}
        raise AssertionError((method, url))

    def put_event(self, cal: str, **ev) -> dict:
        ev.setdefault("id", uuid.uuid4().hex)
        ev.setdefault("status", "confirmed")
        ev["updated"] = self._stamp()
        self.events.setdefault(cal, {})[ev["id"]] = ev
        return ev


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(gcal, "_http", fake)
    monkeypatch.setattr(gcal.settings, "google_client_id", "cid")
    monkeypatch.setattr(gcal.settings, "google_client_secret", "secret")
    monkeypatch.setattr(gcal.settings, "google_redirect_uri", "https://api.example.test/api/integrations/google-calendar/callback")
    gcal._locks.clear()
    return fake


@pytest.fixture
async def admin_headers(tenant) -> dict:
    async with AsyncSessionLocal() as db:
        u = User(id=str(uuid.uuid4()), tenant_id=tenant.id, email="gadmin@example.test",
                 hashed_password="x", role="admin", name="管理者")
        db.add(u)
        await db.commit()
    return {"Authorization": f"Bearer {create_access_token(tenant.id, u.id, 'admin')}"}


@pytest.fixture
async def staff_headers(tenant) -> dict:
    async with AsyncSessionLocal() as db:
        u = User(id=str(uuid.uuid4()), tenant_id=tenant.id, email="gstaff@example.test",
                 hashed_password="x", role="staff", name="スタッフ")
        db.add(u)
        await db.commit()
    return {"Authorization": f"Bearer {create_access_token(tenant.id, u.id, 'staff')}"}


def uid_of(headers: dict) -> str:
    return jose_jwt.get_unverified_claims(headers["Authorization"].split()[1])["sub"]


async def complete(client, tenant, headers, *, state_user: str | None = None, **body) -> str:
    state = create_google_state_token(tenant.id, state_user or uid_of(headers))
    r = await client.post(f"{API}/oauth/complete", headers=headers, json={"code": "c", "state": state, **body})
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def connect(client, tenant, headers) -> None:
    assert await complete(client, tenant, headers) == "connected"


def future(days: int = 3, hour: int = 10) -> datetime:
    base = gcal.now_jst_wall().replace(hour=hour, minute=0, second=0)
    return base + timedelta(days=days)


def rfc(dt: datetime) -> str:
    return gcal.jst_wall_to_rfc3339(dt)


async def appts(tenant_id: str) -> list[VisitorAppointment]:
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(VisitorAppointment).where(VisitorAppointment.tenant_id == tenant_id)
            .order_by(VisitorAppointment.scheduled_at)
        )).scalars().all())


# ── 日時 ───────────────────────────────────────────────────────────────────────

def test_jst_wall_clock_round_trip():
    # 来社予定は JST の壁時計で保存している。Google へは +09:00 で送る(9 時間ずらさない)。
    assert gcal.jst_wall_to_rfc3339(datetime(2026, 11, 20, 10, 0)) == "2026-11-20T10:00:00+09:00"
    # Google が UTC で返してきても JST の 10:00 に直す。
    assert gcal.event_time_to_jst_wall({"dateTime": "2026-11-20T01:00:00Z"}) == datetime(2026, 11, 20, 10, 0)
    assert gcal.event_time_to_jst_wall({"dateTime": "2026-11-20T10:00:00+09:00"}) == datetime(2026, 11, 20, 10, 0)
    # 終日の予定は時刻が無い
    assert gcal.event_time_to_jst_wall({"date": "2026-11-20"}) is None


# ── 連携(OAuth) ───────────────────────────────────────────────────────────────

async def test_disabled_without_env(client, tenant, admin_headers, monkeypatch):
    monkeypatch.setattr(gcal.settings, "google_client_id", "")
    r = await client.get(f"{API}/oauth/url", headers=admin_headers)
    assert r.json() == {"enabled": False}
    assert (await client.get(f"{API}", headers=admin_headers)).json()["enabled"] is False


async def test_authorize_url_requests_offline_consent(client, tenant, admin_headers, google):
    r = await client.get(f"{API}/oauth/url", headers=admin_headers)
    q = parse_qs(urlparse(r.json()["authorize_url"]).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["select_account consent"]
    assert set(q["scope"][0].split()) == set(gcal.SCOPES)


async def test_callback_stores_tokens_encrypted_and_never_returns_them(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    async with AsyncSessionLocal() as db:
        integ = await gcal.load_integration(db, tenant.id)
        assert "rt-1" not in integ.credentials_json  # 暗号化されている
        assert gcal.load_credentials(integ)["refresh_token"] == "rt-1"
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["connected"] is True and body["account_email"] == PRIMARY
    assert "rt-1" not in str(body) and "at-1" not in str(body)


async def test_callback_rejects_when_a_scope_was_unchecked(client, tenant, admin_headers, google):
    google.granted_scope = gcal.SCOPE_CALENDARLIST  # 「予定の表示と編集」のチェックを外された
    assert await complete(client, tenant, admin_headers) == "scope"
    async with AsyncSessionLocal() as db:
        assert await gcal.load_integration(db, tenant.id) is None


async def test_callback_with_bad_state_changes_nothing(client, tenant, admin_headers, google):
    r = await client.post(f"{API}/oauth/complete", headers=admin_headers, json={"code": "c", "state": "forged"})
    assert r.json() == {"result": "error"}
    async with AsyncSessionLocal() as db:
        assert await gcal.load_integration(db, tenant.id) is None


async def test_state_made_by_someone_else_is_refused(client, tenant, admin_headers, google):
    # 他人が作った認可 URL を踏まされても、その人のテナントにはつながらない
    assert await complete(client, tenant, admin_headers, state_user=str(uuid.uuid4())) == "mismatch"
    async with AsyncSessionLocal() as db:
        assert await gcal.load_integration(db, tenant.id) is None
    assert not any(u == gcal.TOKEN_ENDPOINT for _m, u in google.calls)  # コードの交換もしない


async def test_staff_and_readonly_cannot_change_the_link(client, tenant, staff_headers, google):
    assert (await client.get(f"{API}/oauth/url", headers=staff_headers)).status_code == 403
    r = await client.put(f"{API}/settings", headers=staff_headers,
                         json={"direction": "to_google", "calendar_id": PRIMARY})
    assert r.status_code == 403
    # 連携状態を見るだけならスタッフもできる(来社予定画面の表示用)
    assert (await client.get(f"{API}", headers=staff_headers)).status_code == 200
    async with AsyncSessionLocal() as db:
        u = User(id=str(uuid.uuid4()), tenant_id=tenant.id, email="ro@example.test",
                 hashed_password="x", role="admin")
        db.add(u)
        await db.commit()
    ro = {"Authorization": f"Bearer {create_access_token(tenant.id, u.id, 'admin', readonly=True)}"}
    assert (await client.get(f"{API}/oauth/url", headers=ro)).status_code == 403


async def test_calendar_list_puts_my_calendars_first(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    cals = (await client.get(f"{API}/calendars", headers=admin_headers)).json()["calendars"]
    assert [c["id"] for c in cals] == [PRIMARY, TEAM, HOLIDAYS]
    assert cals[0]["primary"] and cals[0]["group"] == "mine"
    assert cals[2]["group"] == "other" and cals[2]["writable"] is False


# ── mokuture → Google ─────────────────────────────────────────────────────────

async def test_to_google_rejects_read_only_calendar(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    r = await client.put(f"{API}/settings", headers=admin_headers,
                         json={"direction": "to_google", "calendar_id": HOLIDAYS})
    assert r.status_code == 422


async def test_to_google_pushes_existing_and_new_appointments(client, tenant, admin_headers, google):
    async with AsyncSessionLocal() as db:
        room = MeetingRoom(tenant_id=tenant.id, name="商談ルーム", location="2階", is_active=True)
        db.add(room)
        await db.commit()
    # 連携前からある、これからの予定 / 過去の予定
    when = future(2, 10)
    r = await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "山田 太郎", "company": "A&B商事", "staff": "佐藤", "scheduled_at": when.isoformat(),
        "duration_minutes": 30, "meeting_room_id": room.id,
    })
    existing_id = r.json()["id"]
    qr_token = r.json()["token"]
    await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "過去 花子", "scheduled_at": (gcal.now_jst_wall() - timedelta(days=10)).isoformat(),
    })

    await connect(client, tenant, admin_headers)
    r = await client.put(f"{API}/settings", headers=admin_headers,
                         json={"direction": "to_google", "calendar_id": TEAM})
    assert r.status_code == 200

    evs = list(google.events[TEAM].values())
    assert len(evs) == 1  # 過去の予定は書き出さない
    ev = evs[0]
    assert ev["id"] == existing_id.replace("-", "")
    assert ev["start"] == {"dateTime": rfc(when), "timeZone": "Asia/Tokyo"}
    assert ev["end"]["dateTime"] == rfc(when + timedelta(minutes=30))
    assert ev["summary"] == "【来社】A&B商事 山田 太郎 様"
    assert ev["location"] == "商談ルーム（2階）"
    assert ev["extendedProperties"]["private"]["mokuture_appointment_id"] == existing_id
    assert qr_token not in str(ev)  # QR の予約コードはカレンダーに載せない
    assert (await client.get(f"{API}", headers=admin_headers)).json()["unsynced_count"] == 0

    # 新しく登録 → すぐ書き出す / 変更 → 同じイベントを書き換える / 削除 → イベントを消す
    r = await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "鈴木", "scheduled_at": future(5, 14).isoformat()})
    new_id = r.json()["id"]
    assert new_id.replace("-", "") in google.events[TEAM]
    assert r.json()["gcal_sync_state"] == "pending"  # 応答の時点ではまだ送っていない
    await client.patch(f"/api/appointments/{new_id}", headers=admin_headers,
                       json={"scheduled_at": future(6, 15).isoformat()})
    assert google.events[TEAM][new_id.replace("-", "")]["start"]["dateTime"] == rfc(future(6, 15))
    assert len(google.events[TEAM]) == 2  # 二重に作らない
    await client.delete(f"/api/appointments/{new_id}", headers=admin_headers)
    assert google.events[TEAM][new_id.replace("-", "")]["status"] == "cancelled"
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(CalendarEventTombstone))).scalars().all() == []


async def test_to_google_failed_push_is_retried_by_sync(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    google.fail_writes = 1
    r = await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "失敗 一郎", "scheduled_at": future(1).isoformat()})
    assert google.events[TEAM] == {}
    status = (await client.get(f"{API}", headers=admin_headers)).json()
    assert status["unsynced_count"] == 1 and status["last_error"]
    res = (await client.post(f"{API}/sync", headers=admin_headers)).json()
    assert res["result"]["pushed"] == 1 and res["last_error"] is None and res["unsynced_count"] == 0
    assert r.json()["id"].replace("-", "") in google.events[TEAM]


async def test_to_google_changing_calendar_moves_events(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    r = await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "移動 次郎", "scheduled_at": future(2).isoformat()})
    eid = r.json()["id"].replace("-", "")
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": PRIMARY})
    await client.post(f"{API}/sync", headers=admin_headers)
    assert google.events[TEAM][eid]["status"] == "cancelled"
    assert google.events[PRIMARY][eid]["status"] == "confirmed"


async def test_refresh_token_revoked_shows_reauth(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    async with AsyncSessionLocal() as db:  # アクセストークンの期限切れ → 取り直しで invalid_grant
        integ = await gcal.load_integration(db, tenant.id)
        gcal.store_credentials(integ, {"refresh_token": "rt-1", "access_token": "", "access_expires_at": 0})
        await db.commit()
    google.refresh_error = "invalid_grant"
    await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "切断", "scheduled_at": future(1).isoformat()})
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["status"] == "reauth_required" and body["active"] is False
    assert "もう一度連携" in body["last_error"]


# ── Google → mokuture ─────────────────────────────────────────────────────────

async def setup_pull(client, tenant, admin_headers, keyword: str = "") -> None:
    await set_staff_list(tenant.id, ["佐藤", "高橋"])
    await connect(client, tenant, admin_headers)
    r = await client.put(f"{API}/settings", headers=admin_headers, json={
        "direction": "from_google", "calendar_id": PRIMARY, "import_keyword": keyword, "default_staff": "佐藤"})
    assert r.status_code == 200, r.text


async def test_from_google_imports_timed_events_in_jst(client, tenant, admin_headers, google):
    async with AsyncSessionLocal() as db:
        db.add(MeetingRoom(tenant_id=tenant.id, name="商談ルーム", is_active=True))
        await db.commit()
    when = future(3, 11)
    utc = (when - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    google.put_event(PRIMARY, summary="来社 B社 田中様", location="本社 商談ルーム",
                     description="<p>持参物<br>資料</p>",
                     start={"dateTime": utc}, end={"dateTime": rfc(when + timedelta(minutes=45))})
    google.put_event(PRIMARY, summary="来社 終日", start={"date": "2026-12-01"}, end={"date": "2026-12-02"})
    google.put_event(PRIMARY, summary="社内定例", start={"dateTime": rfc(future(3, 13))},
                     end={"dateTime": rfc(future(3, 14))})
    google.put_event(PRIMARY, summary="来社 不在", eventType="outOfOffice", start={"dateTime": rfc(future(5))},
                     end={"dateTime": rfc(future(5, 11))})
    google.put_event(PRIMARY, summary="来社 断った予定", start={"dateTime": rfc(future(4))},
                     end={"dateTime": rfc(future(4, 11))}, attendees=[{"self": True, "responseStatus": "declined"}])

    await setup_pull(client, tenant, admin_headers, keyword="来社")
    rows = await appts(tenant.id)
    assert len(rows) == 1  # 終日・キーワードなし・断った予定は取り込まない
    a = rows[0]
    assert a.visitor_name == "B社 田中様"  # 取り込みの言葉はお名前に残さない
    assert a.scheduled_at == when and a.duration_minutes == 45  # UTC で来ても JST の壁時計
    assert a.staff == "佐藤" and a.meeting_room_id is not None and a.notes == "持参物\n資料"
    assert a.gcal_origin == "google"
    # 取り込んだ予定は Google へ書き戻さない
    assert not any(m in ("POST", "PATCH") and "/events" in u for m, u in google.calls)


async def test_from_google_updates_only_google_owned_fields(client, tenant, admin_headers, google):
    ev = google.put_event(PRIMARY, summary="来社 C社", start={"dateTime": rfc(future(2, 10))},
                          end={"dateTime": rfc(future(2, 11))})
    await setup_pull(client, tenant, admin_headers)
    a = (await appts(tenant.id))[0]
    # mokuture 側で担当者・会社名・メモを付ける
    async with AsyncSessionLocal() as db:
        row = await db.get(VisitorAppointment, a.id)
        row.staff, row.company, row.notes = "高橋", "C社", "駐車場あり"
        await db.commit()
    google.put_event(PRIMARY, id=ev["id"], summary="来社 C社 変更", start={"dateTime": rfc(future(2, 15))},
                     end={"dateTime": rfc(future(2, 16))})
    res = (await client.post(f"{API}/sync", headers=admin_headers)).json()["result"]
    assert res["updated"] == 1
    a = (await appts(tenant.id))[0]
    assert a.visitor_name == "来社 C社 変更" and a.scheduled_at == future(2, 15)
    assert (a.staff, a.company, a.notes) == ("高橋", "C社", "駐車場あり")  # 上書きしない
    # 変わっていなければ何もしない
    assert (await client.post(f"{API}/sync", headers=admin_headers)).json()["result"]["updated"] == 0


async def test_from_google_cancelled_removes_only_pending(client, tenant, admin_headers, google):
    e1 = google.put_event(PRIMARY, summary="キャンセル1", start={"dateTime": rfc(future(2))},
                          end={"dateTime": rfc(future(2, 11))})
    e2 = google.put_event(PRIMARY, summary="受付済み", start={"dateTime": rfc(future(2, 13))},
                          end={"dateTime": rfc(future(2, 14))})
    await setup_pull(client, tenant, admin_headers)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(VisitorAppointment).where(
            VisitorAppointment.gcal_event_id == e2["id"]))).scalar_one()
        row.status = "received"
        await db.commit()
    google.events[PRIMARY][e1["id"]]["status"] = "cancelled"
    google.events[PRIMARY][e2["id"]]["status"] = "cancelled"
    await client.post(f"{API}/sync", headers=admin_headers)
    rows = await appts(tenant.id)
    assert [r.visitor_name for r in rows] == ["受付済み"]


async def test_from_google_event_moved_out_of_window_is_followed(client, tenant, admin_headers, google):
    ev = google.put_event(PRIMARY, summary="延期", start={"dateTime": rfc(future(2))},
                          end={"dateTime": rfc(future(2, 11))})
    await setup_pull(client, tenant, admin_headers)
    # 一覧には出てこない(偽物は期間で絞らないので、一覧から外したうえで個別取得だけ答える)
    moved = {**ev, "start": {"dateTime": rfc(future(120))}, "end": {"dateTime": rfc(future(120, 11))},
             "updated": "2026-12-01T00:00:00Z"}
    orig_call = google.__call__

    async def call(method, url, **kw):
        if method == "GET" and url.endswith("/events"):
            return 200, {"items": []}
        if method == "GET" and url.endswith(ev["id"]):
            return 200, moved
        return await orig_call(method, url, **kw)

    gcal._http = call  # monkeypatch のフィクスチャが後で元に戻す
    await client.post(f"{API}/sync", headers=admin_headers)
    assert (await appts(tenant.id))[0].scheduled_at == future(120)


async def test_from_google_deleted_locally_is_not_reimported(client, tenant, admin_headers, google):
    google.put_event(PRIMARY, summary="不要な予定", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))})
    await setup_pull(client, tenant, admin_headers)
    a = (await appts(tenant.id))[0]
    assert (await client.delete(f"/api/appointments/{a.id}", headers=admin_headers)).status_code == 204
    await client.post(f"{API}/sync", headers=admin_headers)
    assert await appts(tenant.id) == []
    assert google.events[PRIMARY]  # Google 側の予定は消さない


async def test_from_google_does_not_import_events_mokuture_wrote(client, tenant, admin_headers, google):
    # 書き出し中に作ったイベント(元の来社予定は消してある)を、取り込みに切り替えても作り直さない
    google.put_event(PRIMARY, summary="【来社】旧", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))},
                     extendedProperties={"private": {"mokuture_appointment_id": str(uuid.uuid4())}})
    await setup_pull(client, tenant, admin_headers)
    assert await appts(tenant.id) == []


async def test_from_google_changing_calendar_drops_old_imports(client, tenant, admin_headers, google):
    google.put_event(PRIMARY, summary="主の予定", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))})
    google.put_event(TEAM, summary="来客用の予定", start={"dateTime": rfc(future(3))},
                     end={"dateTime": rfc(future(3, 11))})
    await setup_pull(client, tenant, admin_headers)
    r = await client.put(f"{API}/settings", headers=admin_headers,
                         json={"direction": "from_google", "calendar_id": TEAM})
    assert r.json()["removed_imports"] == 1
    assert [a.visitor_name for a in await appts(tenant.id)] == ["来客用の予定"]


async def test_reconnecting_another_account_that_sees_the_calendar_keeps_links(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "紐付け", "scheduled_at": future(2).isoformat()})
    google.email = "other@example.test"  # 共有カレンダー(TEAM)は新しいアカウントからも見える
    await connect(client, tenant, admin_headers)
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["account_email"] == "other@example.test" and body["calendar_id"] == TEAM
    assert (await appts(tenant.id))[0].gcal_event_id


async def test_reconnecting_another_account_without_the_calendar_unlinks(client, tenant, admin_headers, google):
    google.put_event(TEAM, summary="取り込み済み", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))})
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "from_google", "calendar_id": TEAM})
    await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "mokuture の予定", "scheduled_at": future(3).isoformat()})
    google.email = "other@example.test"
    google.calendars = [c for c in google.calendars if c["id"] != TEAM]
    await connect(client, tenant, admin_headers)
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["calendar_id"] is None
    rows = await appts(tenant.id)
    # 見えなくなったカレンダーから取り込んだ未受付の予定は消す(孤児にして二重取り込みしない)
    assert [r.visitor_name for r in rows] == ["mokuture の予定"]
    assert rows[0].gcal_event_id is None


async def test_reconnect_with_failed_account_lookup_changes_nothing(client, tenant, admin_headers, google):
    google.put_event(PRIMARY, summary="取り込み済み", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))})
    await setup_pull(client, tenant, admin_headers)
    orig = google.__call__

    async def flaky(method, url, **kw):
        if "calendarList" in url:
            return 503, {}
        return await orig(method, url, **kw)

    gcal._http = flaky
    assert await complete(client, tenant, admin_headers) == "error"
    gcal._http = google
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["calendar_id"] == PRIMARY and body["account_email"] == PRIMARY
    assert (await appts(tenant.id))[0].gcal_event_id  # 結び付きは残っている


async def test_disconnect_keeps_appointments_and_events(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "残す", "scheduled_at": future(2).isoformat()})
    assert (await client.post(f"{API}/disconnect", headers=admin_headers)).status_code == 200
    body = (await client.get(f"{API}", headers=admin_headers)).json()
    assert body["connected"] is False and body["active"] is False
    assert len(await appts(tenant.id)) == 1 and len(google.events[TEAM]) == 1
    assert ("POST", gcal.REVOKE_ENDPOINT) in google.calls


async def test_delete_right_after_create_still_removes_the_event(client, tenant, admin_headers, google):
    # 画面操作の直後の送信がまだ記録していない(＝予定にイベント ID が無い)うちに消しても、
    # 決まった ID で Google のイベントを消しに行く
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": TEAM})
    async with AsyncSessionLocal() as db:
        a = VisitorAppointment(tenant_id=tenant.id, visitor_name="すぐ消す", scheduled_at=future(2),
                               gcal_sync_state="pending")
        db.add(a)
        await db.commit()
    eid = a.id.replace("-", "")
    google.put_event(TEAM, id=eid, summary="【来社】すぐ消す", start={"dateTime": rfc(future(2))},
                     end={"dateTime": rfc(future(2, 11))})  # 送信中だったイベント
    assert (await client.delete(f"/api/appointments/{a.id}", headers=admin_headers)).status_code == 204
    assert google.events[TEAM][eid]["status"] == "cancelled"


async def test_unexpected_error_is_shown_on_screen(client, tenant, admin_headers, google, monkeypatch):
    await setup_pull(client, tenant, admin_headers)

    async def boom(db, integ):
        raise RuntimeError("x")

    monkeypatch.setattr(gcal, "_pull", boom)
    res = (await client.post(f"{API}/sync", headers=admin_headers)).json()
    assert res["result"]["failed"] == 1 and res["last_error"] == gcal.UNEXPECTED_MESSAGE


def test_title_becomes_a_clean_visitor_name():
    assert gcal.visitor_name_from_title("来社 B社 田中様", "来社") == "B社 田中様"
    assert gcal.visitor_name_from_title("【来社】C社 鈴木", "来社") == "C社 鈴木"
    assert gcal.visitor_name_from_title("来社：山田", "来社") == "山田"
    assert gcal.visitor_name_from_title("来社", "来社") == "来社"  # 何も残らなければ元のまま
    assert gcal.visitor_name_from_title("D社 高橋 来社", "来社") == "D社 高橋"
    # 短い言葉でもタイトルの途中は削らない
    assert gcal.visitor_name_from_title("ABC社 田中様", "社") == "ABC社 田中様"
    assert gcal.visitor_name_from_title("  A社   佐藤 ", "") == "A社 佐藤"


# ── 取り込みの色の条件 ─────────────────────────────────────────────────────────

async def save_pull(client, admin_headers, *, keyword: str = "", colors: list[str]) -> dict:
    r = await client.put(f"{API}/settings", headers=admin_headers, json={
        "direction": "from_google", "calendar_id": PRIMARY, "import_keyword": keyword,
        "import_colors": colors, "default_staff": ""})
    assert r.status_code == 200, r.text
    return r.json()


async def test_from_google_imports_only_selected_colors(client, tenant, admin_headers, google):
    google.put_event(PRIMARY, summary="来社 バナナ", colorId="5", start={"dateTime": rfc(future(2, 10))},
                     end={"dateTime": rfc(future(2, 11))})
    google.put_event(PRIMARY, summary="来社 トマト", colorId="11", start={"dateTime": rfc(future(2, 12))},
                     end={"dateTime": rfc(future(2, 13))})
    google.put_event(PRIMARY, summary="来社 色なし", start={"dateTime": rfc(future(2, 14))},
                     end={"dateTime": rfc(future(2, 15))})
    google.put_event(PRIMARY, summary="社内 バナナ", colorId="5", start={"dateTime": rfc(future(2, 16))},
                     end={"dateTime": rfc(future(2, 17))})
    await connect(client, tenant, admin_headers)

    # 色だけ(言葉は空): バナナと「色を付けていない予定」
    body = await save_pull(client, admin_headers, colors=["5", "default"])
    assert body["import_colors"] == ["default", "5"]  # 画面の並び順にそろえて返す
    assert {c["id"] for c in body["event_colors"]} >= {"default", "5", "11"}
    assert sorted(a.visitor_name for a in await appts(tenant.id)) == ["来社 バナナ", "来社 色なし", "社内 バナナ"]

    # 言葉と色の両方: 両方に合う予定だけ。合わなくなった未受付の予定は消える
    await save_pull(client, admin_headers, keyword="来社", colors=["5"])
    # (お名前は Google 側で予定が変わったときに付け直すので、ここでは取り込んだときのまま)
    assert [a.visitor_name for a in await appts(tenant.id)] == ["来社 バナナ"]


async def test_from_google_color_changed_in_google_is_followed(client, tenant, admin_headers, google):
    ev = google.put_event(PRIMARY, summary="来訪 D社", colorId="7", start={"dateTime": rfc(future(3, 10))},
                          end={"dateTime": rfc(future(3, 11))})
    await connect(client, tenant, admin_headers)
    await save_pull(client, admin_headers, colors=["7"])
    assert len(await appts(tenant.id)) == 1
    google.put_event(PRIMARY, id=ev["id"], summary="来訪 D社", colorId="8",
                     start={"dateTime": rfc(future(3, 10))}, end={"dateTime": rfc(future(3, 11))})
    res = (await client.post(f"{API}/sync", headers=admin_headers)).json()["result"]
    assert res["removed"] == 1 and await appts(tenant.id) == []
    google.put_event(PRIMARY, id=ev["id"], summary="来訪 D社", colorId="7",
                     start={"dateTime": rfc(future(3, 10))}, end={"dateTime": rfc(future(3, 11))})
    assert (await client.post(f"{API}/sync", headers=admin_headers)).json()["result"]["imported"] == 1


async def test_color_settings_are_validated(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    r = await client.put(f"{API}/settings", headers=admin_headers, json={
        "direction": "from_google", "calendar_id": PRIMARY, "import_colors": ["99"]})
    assert r.status_code == 422
    # 全部の色を選ぶ = 色で絞らない
    body = await save_pull(client, admin_headers, colors=[c["id"] for c in gcal.EVENT_COLORS])
    assert body["import_colors"] == []
    # 書き出し(to_google)では色を保存しない
    r = await client.put(f"{API}/settings", headers=admin_headers, json={
        "direction": "to_google", "calendar_id": PRIMARY, "import_colors": ["5"]})
    assert r.status_code == 200 and r.json()["import_colors"] == []


async def test_mokuture_written_event_is_followed_even_outside_the_color_filter(client, tenant, admin_headers, google):
    await connect(client, tenant, admin_headers)
    await client.put(f"{API}/settings", headers=admin_headers, json={"direction": "to_google", "calendar_id": PRIMARY})
    r = await client.post("/api/appointments", headers=admin_headers, json={
        "visitor_name": "書き出し済み", "scheduled_at": future(4, 10).isoformat()})
    aid = r.json()["id"]
    await save_pull(client, admin_headers, colors=["5"])  # 書き出した予定には色が無い
    eid = aid.replace("-", "").lower()
    ev = google.events[PRIMARY][eid]
    google.put_event(PRIMARY, **{**ev, "start": {"dateTime": rfc(future(4, 15))}, "end": {"dateTime": rfc(future(4, 16))}})
    await client.post(f"{API}/sync", headers=admin_headers)
    rows = await appts(tenant.id)
    assert len(rows) == 1 and rows[0].scheduled_at == future(4, 15)  # 消さず、日時は追う
