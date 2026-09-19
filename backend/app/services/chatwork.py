"""Chatwork 通知。

これまで Chatwork への送信は `api/kiosk.py` に直書きされていて、**配達の呼び出し
だけ**が使っていた。受付通知(来客のお知らせ)は Slack / Web Push / Webhook / メール
しか通っておらず、管理画面「通知設定」の Chatwork カードを受付通知のつもりで
設定していても届かない、という食い違いがあった。

担当者ごとの Chatwork ルーム指定(issue #1)を入れるにあたり、送信をここへ集約して
受付通知の経路(`services/reception_notify.py`)からも使えるようにする。

宛先の考え方は Slack と揃える:
  - API トークンはテナント共通のものを使い回す(担当者ごとに発行させない)
  - 担当者ごとに差し替えるのは **ルーム ID だけ**
"""
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationSetting
from app.services.crypto import decrypt_dict
from app.services.honorific import with_honorific
from app.services.timeutil import format_jst

logger = logging.getLogger(__name__)

API_BASE = "https://api.chatwork.com/v2"
_TIMEOUT = 10.0


async def _read_setting(db: AsyncSession, tenant_id: str, type_: str) -> dict | None:
    """1 種類ぶんの設定を復号して返す。行が無い/壊れているなら None。"""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == type_,
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        return None
    try:
        return decrypt_dict(setting.config_json)
    except Exception:
        logger.warning("chatwork config decrypt failed (tenant=%s, type=%s)", tenant_id, type_)
        return None


async def load_config(
    db: AsyncSession, tenant_id: str, types: tuple[str, ...] = ("chatwork",)
) -> dict:
    """配達の呼び出し用: `types` の順で**最初に見つかった行**を返す。

    「行はあるがルーム未設定なら、次の候補へ流さずそこで終わる」という従来の挙動
    (`api/kiosk.py` の `_first_configured_setting`)をそのまま保つ。ここを「不完全な行は
    飛ばす」に変えると、配達専用ルームを空にしているテナントの配達通知が受付用ルームへ
    流れ出してしまう。
    """
    for type_ in types:
        config = await _read_setting(db, tenant_id, type_)
        if config is not None:
            return config
    return {}


async def load_api_token(db: AsyncSession, tenant_id: str) -> str:
    """テナント共通の API トークン。担当者ごとのルームへ投稿するのに使う。

    **ルーム ID とは切り離して取る。** 共通ルームが空でも、担当者ごとのルームが
    設定されていれば送れなければならない（両方揃った行だけを返すと、トークンだけ
    登録したテナントで担当者ルームへ1通も届かなくなる）。
    """
    config = await _read_setting(db, tenant_id, "chatwork")
    return (config or {}).get("api_token", "").strip()


async def send_message(api_token: str, room_id: str, text: str) -> bool:
    """1 ルームへ投稿する。失敗しても例外は投げない（他チャネルを止めない）。"""
    token = (api_token or "").strip()
    room = (room_id or "").strip()
    if not token or not room:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(
                f"{API_BASE}/rooms/{room}/messages",
                headers={"X-ChatWorkToken": token},
                data={"body": text},
            )
        if res.status_code >= 400:
            # 本文にはトークンを出さない。room だけ出して調査できるようにする。
            logger.warning("chatwork post failed (room=%s, status=%s)", room, res.status_code)
            return False
        return True
    except Exception:
        logger.warning("chatwork post failed (room=%s)", room)
        return False


def escape_tags(value: str | None) -> str:
    """Chatwork 記法のタグ文字を無効化する。

    本文は来訪者がキオスクで入力した氏名・会社名をそのまま含む。`[/info]` や
    `[To:12345]` のような文字列を入れられると、カードを途中で閉じたり他人へ
    メンションを飛ばしたりできてしまう。角括弧を全角に寄せて無害化する
    （Chatwork にはエスケープ記法が無いため）。
    """
    return (value or "").replace("[", "［").replace("]", "］")


def build_reception_message(
    visitor_name: str,
    company: str | None = None,
    host_name: str | None = None,
    when: datetime | None = None,
    department: str | None = None,
    escalated_from: str | None = None,
) -> str:
    """受付通知の本文（Chatwork 記法）。

    Slack 版と同じ項目・同じ順序にしてある。違うのは装飾だけで、Slack の絵文字
    ショートコード(`:bell:`)は Chatwork では展開されないため `[info][title]` を使う。
    """
    head = "受付に応答がありません（代理通知）" if escalated_from else "来客がありました"
    lines: list[str] = []
    if (company or "").strip():
        lines.append(f"会社名：{escape_tags(company.strip())}")
    lines.append(f"お名前：{escape_tags(with_honorific(visitor_name))}")
    if (department or "").strip():
        lines.append(f"訪問先部署：{escape_tags(department.strip())}")
    if (host_name or "").strip():
        lines.append(f"訪問先：{escape_tags(host_name.strip())}")
    lines.append(f"時刻：{format_jst(when)}")
    lines.append("")
    if escalated_from:
        lines.append(
            f"「{escape_tags(escalated_from)}」宛の受付に応答がありません。代わりに対応をお願いします。"
        )
    else:
        lines.append("対応をお願いします。")
    body = "\n".join(lines)
    return f"[info][title]{head}[/title]{body}[/info]"
