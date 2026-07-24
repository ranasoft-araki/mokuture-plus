from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import inspect, select, text

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.api import api_router


# Alembic 未導入のため、起動時に冪等な軽量カラム追加を適用する。
# 既存テーブルに後付けしたカラムを本番(Postgres/Neon)・開発(SQLite)双方で揃える。
# (テーブルが無ければ create_all が全カラム込みで作成するためここでは何もしない)
_ENSURE_COLUMNS = {
    "meeting_rooms": {
        "map_image_url": "VARCHAR(512)",
    },
    "tenants": {
        # 受付通知で「電話(対応不可)」応答時にキオスクへ表示する電話番号、
        # 「お断り」応答時に案内する外部問い合わせフォールURL(未設定時は共通フォームへ)。
        "kiosk_phone_number": "VARCHAR(32)",
        "inquiry_form_url": "VARCHAR(512)",
        # キオスク文言(受付メニュー見出し / ようこそ画面QR案内・フォームボタン)。
        # DEFAULT 付きで既存行も埋める。
        "kiosk_menu_title": "VARCHAR(255) DEFAULT 'ご用件をお選びください'",
        "kiosk_welcome_qr_guide": "VARCHAR(255) DEFAULT 'ご予約QRをお持ちの方はカメラへかざしてください'",
        "kiosk_welcome_form_label": "VARCHAR(255) DEFAULT 'QRをお持ちでない方はこちら'",
        # 来訪者が受付フォームで選べる訪問先部署のリスト(カンマ区切り)。
        "department_list": "TEXT",
        # 審査用デモモード。既存行は FALSE。demo1/demo2 は下でバックフィルして有効化。
        "is_demo": "BOOLEAN DEFAULT FALSE",
    },
    "lockers": {
        "name": "VARCHAR(255)",
        "pin_hash": "VARCHAR(255)",
        "occupied": "BOOLEAN DEFAULT FALSE",
        "occupied_at": "TIMESTAMP",
    },
    "reception_logs": {
        "decided_at": "TIMESTAMP",
        # 来訪者が選んだ訪問先部署。
        "department": "VARCHAR(255)",
    },
    "devices": {
        # 承認フロー。既存端末は 'active' で埋めて後方互換を保つ。
        "status": "VARCHAR(16) DEFAULT 'active'",
        "hardware_id": "VARCHAR(128)",
        # ローカルファースト・ロッカーの占有スナップショット（管理画面の表示専用）。
        "locker_state_json": "TEXT",
        "locker_state_at": "TIMESTAMP",
    },
}


def _ensure_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)
    try:
        tables = set(inspector.get_table_names())
    except Exception:
        return
    for table, cols in _ENSURE_COLUMNS.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col, ddl_type in cols.items():
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}"))

    # 審査用デモモード: 作成済みの展示デモ用テナント(demo1/demo2)を有効化する冪等バックフィル。
    # 他テナントをデモ化する場合はこの slug リストに追記するか SQL で is_demo を立てる。
    if "tenants" in tables:
        try:
            sync_conn.execute(text(
                "UPDATE tenants SET is_demo = TRUE "
                "WHERE slug IN ('demo1','demo2') AND (is_demo = FALSE OR is_demo IS NULL)"
            ))
        except Exception:
            pass  # 列未追加/型差異などがあっても致命的ではない

    # 承認フロー: (tenant_id, hardware_id) の重複登録を防ぐ一意インデックス。
    # hardware_id が NULL の行(手動作成端末)は Postgres/SQLite とも「相異なる」扱いのため衝突しない。
    if "devices" in tables:
        try:
            sync_conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_devices_tenant_hardware "
                "ON devices (tenant_id, hardware_id)"
            ))
        except Exception:
            pass  # 既存の重複データ等で作成できなくても致命的ではない


# 審査用デモモードの既定マスタ。QR発行(来局予定)の初期値プリフィルが有効な選択肢になるよう、
# demo テナントに担当者(訪問先)・目的(用件)・会議室(案内先)を冪等にシードする。
_DEMO_SLUGS = ("demo1", "demo2")
_DEMO_STAFF = "mokuture⁺担当者"     # 訪問先(担当者)
_DEMO_PURPOSE = "製品体験"          # 用件(目的)
_DEMO_ROOM = "審査会場"             # 案内先(会議室)
# デモ管理者アカウント（slug→email）。テナントの削除→再作成等で管理者ユーザーの tenant_id が
# 現デモテナントから外れて孤児化すると、会議室作成などの書込が FK 違反で 500 になる。
# シードで現デモテナントへ確実に再リンクして自己修復する。
_DEMO_ADMIN_EMAILS = {"demo1": "demo1@ranasoft.co.jp", "demo2": "demo2@ranasoft.co.jp"}


async def _seed_demo_master_data() -> None:
    """demo テナント(demo1/demo2)に、デモ来局予定の初期値に対応するマスタを冪等登録する。
    既存の値は壊さず、無い項目だけ追加する（best-effort・失敗しても起動は継続）。"""
    from app.models.tenant import Tenant
    from app.models.room import MeetingRoom
    from app.models.user import User
    try:
        async with AsyncSessionLocal() as db:
            tenants = (await db.execute(
                select(Tenant).where(Tenant.slug.in_(_DEMO_SLUGS))
            )).scalars().all()
            changed = False
            for t in tenants:
                # デモ管理者アカウントを現デモテナントへ確実に再リンク（孤児化＝tenant_id が
                # 削除済みテナントを指す状態を修復。会議室作成等の書込 500 の原因を除去）。
                # get_current_user は毎回 DB のユーザー行を読むので再ログイン不要で即反映される。
                admin_email = _DEMO_ADMIN_EMAILS.get(t.slug)
                if admin_email:
                    admins = (await db.execute(
                        select(User).where(User.email == admin_email)
                    )).scalars().all()
                    for u in admins:
                        if u.tenant_id != t.id or u.role != "admin":
                            u.tenant_id = t.id
                            u.role = "admin"
                            changed = True
                staff = [s.strip() for s in (t.staff_list or "").split(",") if s.strip()]
                if _DEMO_STAFF not in staff:
                    staff.append(_DEMO_STAFF)
                    t.staff_list = ",".join(staff)
                    changed = True
                purposes = [p.strip() for p in (t.purpose_list or "").split(",") if p.strip()]
                if _DEMO_PURPOSE not in purposes:
                    purposes.append(_DEMO_PURPOSE)
                    t.purpose_list = ",".join(purposes)
                    changed = True
                room = (await db.execute(
                    select(MeetingRoom).where(
                        MeetingRoom.tenant_id == t.id, MeetingRoom.name == _DEMO_ROOM
                    )
                )).scalar_one_or_none()
                if room is None:
                    db.add(MeetingRoom(
                        tenant_id=t.id, name=_DEMO_ROOM, location="デモ会場",
                        color="#7c3aed", is_active=True,
                    ))
                    changed = True
            if changed:
                await db.commit()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (dev only; use Alembic for production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema)
    await _seed_demo_master_data()
    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="mokuture+ API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Kiosk-Token"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
