"""アカウント作成・ログインで共通に使う確認。

- メールアドレスはログイン ID なので、全ユーザーを通して重複させない(大文字小文字は区別しない)。
  DB に一意制約は無い(本番に既存の重複がありうる)ので、作成時にここで確かめる。
- ログインのとき同じメールが複数あっても 500 にせず、決まった1件を選ぶ。
- テナントのスラッグは画面の URL の先頭に入るので、画面側の固定パスと同じ名前は使わせない。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

EMAIL_TAKEN_DETAIL = "このメールアドレスは既に登録されています"

# 画面(Next.js)・API の固定パスと衝突するスラッグ。
RESERVED_SLUGS = frozenset({
    "login", "operator", "ops-console", "partner-portal", "api", "_next",
    "admin", "kiosk", "inquiry", "static",
    "google-calendar",  # Google カレンダー連携の戻り先(/google-calendar/callback)
    "privacy", "terms",  # プライバシーポリシー・利用規約(Google の同意画面からも開かれる)
})
RESERVED_SLUG_MESSAGE = "このスラッグは使用できません。別の名前を指定してください"


def check_slug_not_reserved(slug: str) -> str:
    """pydantic の validator から呼ぶ。予約語なら ValueError。"""
    if (slug or "").strip().lower() in RESERVED_SLUGS:
        raise ValueError(RESERVED_SLUG_MESSAGE)
    return slug


def normalize_email(email: str | None) -> str:
    return (email or "").strip()


async def email_in_use(db: AsyncSession, email: str) -> bool:
    target = normalize_email(email).lower()
    if not target:
        return False
    row = (await db.execute(
        select(User.id).where(func.lower(User.email) == target).limit(1)
    )).first()
    return row is not None


async def find_login_user(
    db: AsyncSession, email: str, roles: tuple[str, ...] | None = None
) -> User | None:
    """ログイン用にメールアドレスからユーザーを1件選ぶ。

    完全一致を優先し、無ければ大文字小文字を無視して探す。重複がある場合は、
    `roles` に合うものを優先し、その中で作成が古い順(同時刻なら id 順)の先頭を選ぶ
    ＝毎回同じ1件に決まる。"""
    raw = normalize_email(email)
    if not raw:
        return None
    for cond in (User.email == raw, func.lower(User.email) == raw.lower()):
        candidates = list((await db.execute(
            select(User).where(cond).order_by(User.created_at, User.id).limit(20)
        )).scalars().all())
        if candidates:
            if roles:
                for u in candidates:
                    if u.role in roles:
                        return u
            return candidates[0]
    return None
