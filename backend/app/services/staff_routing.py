"""訪問先担当者ごとの通知先の解決（宛先ルーティング）。

受付通知の宛先は従来「テナントに1つ」だったが、来訪者がキオスクで選んだ訪問先担当者
(`reception_logs.staff` = `tenants.staff_list` の1件)ごとに Slack チャンネル / メール /
Webhook を割り当てられるようにした。行が無い担当者・担当者未選択の受付は**従来どおり
テナント共通の通知先だけ**に送る（後方互換）。

代理通知(エスカレーション)は「別の担当者を指定」方式。応答が無いまま
`escalate_after_sec` を過ぎたら、その担当者の通知先へ**1段だけ**転送する（連鎖しない＝
代理の代理は辿らない。ループも起きない）。

このモジュールは「誰に送るか」だけを決める。実際の送信は `services/reception_notify.py`。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationSetting
from app.models.staff_route import StaffNotificationRoute
from app.services.crypto import decrypt_dict

logger = logging.getLogger(__name__)

# 代理通知までの待機秒。0 = 代理通知しない。既定 60 秒。
DEFAULT_ESCALATE_SEC = 60
MIN_ESCALATE_SEC = 30
MAX_ESCALATE_SEC = 3600

# 1担当者に設定できるメール宛先の上限（誤設定で大量送信しないための歯止め）。
MAX_EMAILS = 5

_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def parse_emails(raw: str | None) -> list[str]:
    """カンマ/空白区切りのメール宛先を正規化する。形式が不正なものは捨てる。"""
    out: list[str] = []
    for part in re.split(r"[,\s;]+", (raw or "").strip()):
        addr = part.strip()
        if not addr or not _EMAIL_RE.match(addr):
            continue
        if addr not in out:
            out.append(addr)
        if len(out) >= MAX_EMAILS:
            break
    return out


def validate_emails(raw: str | None) -> list[str]:
    """管理画面からの入力を**厳密に**検証して正規化する。1件でも形式不正なら ValueError。

    保存済みデータを読む `parse_emails` は寛容（壊れた1件で通知全体を落とさない）だが、
    入力時は黙って捨てると誤設定に気づけないので弾く。"""
    parts = [p for p in re.split(r"[,\s;]+", (raw or "").strip()) if p]
    if len(parts) > MAX_EMAILS:
        raise ValueError(f"メールアドレスは最大{MAX_EMAILS}件までです")
    out: list[str] = []
    for addr in parts:
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"メールアドレスの形式が正しくありません: {addr}")
        if addr not in out:
            out.append(addr)
    return out


def route_config(route: StaffNotificationRoute | None) -> dict:
    """ルート行の暗号化済み宛先設定を復号する。壊れていても落とさず空を返す。"""
    if route is None or not route.config_json or route.config_json == "{}":
        return {}
    try:
        return decrypt_dict(route.config_json)
    except Exception:
        logger.warning("staff route config decrypt failed (route=%s)", getattr(route, "id", "?"))
        return {}


@dataclass(frozen=True)
class Destinations:
    """1回の通知で使う宛先一式。

    `use_default` が True のときだけ、従来からのテナント共通の通知先
    (Slack/Webhook/Web Push)へも送る。
    """

    slack_channels: tuple[tuple[str, str], ...] = ()   # (channel_id, channel_name)
    emails: tuple[str, ...] = ()
    webhooks: tuple[str, ...] = ()
    use_default: bool = True
    # 実際に宛先を提供した担当者名（代理通知の文面に出す）。
    routed_to: str = ""

    @property
    def has_direct(self) -> bool:
        """担当者個別の宛先を1つでも持っているか。"""
        return bool(self.slack_channels or self.emails or self.webhooks)


@dataclass(frozen=True)
class EscalationPlan:
    """代理通知の実行計画（誰へ・何秒後か）。"""

    fallback_staff_name: str
    after_sec: int
    origin_staff_name: str = field(default="")


async def get_route(
    db: AsyncSession, tenant_id: str, staff_name: str | None
) -> StaffNotificationRoute | None:
    """担当者名でルート行を引く。テナント越境しない。"""
    name = (staff_name or "").strip()
    if not name:
        return None
    result = await db.execute(
        select(StaffNotificationRoute).where(
            StaffNotificationRoute.tenant_id == tenant_id,
            StaffNotificationRoute.staff_name == name,
        )
    )
    return result.scalar_one_or_none()


def _destinations_from(route: StaffNotificationRoute, *, use_default: bool) -> Destinations:
    config = route_config(route)
    channel_id = (config.get("slack_channel_id") or "").strip()
    channel_name = (config.get("slack_channel_name") or channel_id).strip()
    webhook = (config.get("webhook_url") or "").strip()
    return Destinations(
        slack_channels=((channel_id, channel_name),) if channel_id else (),
        emails=tuple(parse_emails(config.get("email"))),
        webhooks=(webhook,) if webhook else (),
        use_default=use_default,
        routed_to=route.staff_name,
    )


async def resolve_primary(
    db: AsyncSession, tenant_id: str, staff_name: str | None
) -> Destinations:
    """受付時（1通目）の宛先。ルート未設定ならテナント共通の通知先のみ。"""
    route = await get_route(db, tenant_id, staff_name)
    if route is None:
        return Destinations(use_default=True, routed_to=(staff_name or "").strip())
    return _destinations_from(route, use_default=bool(route.include_default))


async def resolve_fallback(
    db: AsyncSession, tenant_id: str, staff_name: str | None
) -> Destinations | None:
    """代理通知（応答が無いとき）の宛先。代理先が未設定なら None（＝送らない）。

    代理担当者にルートが無い/宛先が空のときは、通知が誰にも届かないほうが危険なので
    テナント共通の通知先へ流す。代理の代理は辿らない（1段のみ）。
    """
    route = await get_route(db, tenant_id, staff_name)
    if route is None:
        return None
    fallback_name = (route.fallback_staff_name or "").strip()
    if not fallback_name or route.escalate_after_sec <= 0:
        return None

    target = await get_route(db, tenant_id, fallback_name)
    if target is None:
        return Destinations(use_default=True, routed_to=fallback_name)
    dest = _destinations_from(target, use_default=False)
    if not dest.has_direct:
        # 代理担当者に個別の宛先が無い＝共通の通知先へ（無言の空振りを避ける）。
        return Destinations(use_default=True, routed_to=fallback_name)
    return dest


async def escalation_plan(
    db: AsyncSession, tenant_id: str, staff_name: str | None
) -> EscalationPlan | None:
    """この担当者宛の受付に代理通知の設定があるか。無ければ None。"""
    route = await get_route(db, tenant_id, staff_name)
    if route is None:
        return None
    fallback_name = (route.fallback_staff_name or "").strip()
    after = int(route.escalate_after_sec or 0)
    if not fallback_name or after <= 0:
        return None
    return EscalationPlan(
        fallback_staff_name=fallback_name,
        after_sec=max(MIN_ESCALATE_SEC, min(MAX_ESCALATE_SEC, after)),
        origin_staff_name=route.staff_name,
    )


async def load_default_slack_config(db: AsyncSession, tenant_id: str) -> dict:
    """テナント共通の Slack 設定(type="slack")を復号して返す。未連携なら空 dict。"""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return {}
    try:
        return decrypt_dict(setting.config_json)
    except Exception:
        logger.warning("slack config decrypt failed (tenant=%s)", tenant_id)
        return {}


def slack_send_configs(default_config: dict, dest: Destinations) -> list[tuple[dict, str]]:
    """実際に `SlackNotifier.send_to_config` へ渡す (config, 宛先ラベル) の一覧を組み立てる。

    担当者チャンネルはテナントの Bot Token を使い回してチャンネルだけ差し替える
    （追加スコープ不要）。Bot Token が無い＝旧 Webhook 連携のテナントでは担当者ごとの
    チャンネル指定は成立しないので黙って捨てる（Webhook にはチャンネルが焼き付いている）。
    テナント共通の宛先と同じチャンネルになる場合は重複送信しない。
    """
    bot_token = (default_config.get("bot_access_token") or "").strip()
    default_channel = (default_config.get("channel_id") or "").strip()
    out: list[tuple[dict, str]] = []
    seen: set[str] = set()

    for channel_id, channel_name in dest.slack_channels:
        if not bot_token or channel_id in seen:
            continue
        seen.add(channel_id)
        out.append((
            # webhook_url は落とす: 共通のチャンネルへ二重投稿するフォールバックを防ぐ。
            {"bot_access_token": bot_token, "channel_id": channel_id},
            channel_name or channel_id,
        ))

    if dest.use_default and default_config:
        has_dest = bool(bot_token and default_channel) or bool(default_config.get("webhook_url"))
        if has_dest and default_channel not in seen:
            if default_channel:
                seen.add(default_channel)
            out.append((default_config, default_config.get("channel_name") or "既定の通知先"))
    return out
