"""Slack notification + OAuth (Bot Token / chat.postMessage) service.

`SlackNotifier` centralises everything Slack-specific — the OAuth authorize URL,
the `code`→bot-token exchange, channel discovery/join, message formatting, and
message delivery via `chat.postMessage` — so callers never build Slack URLs or
payloads inline. This is the seam for future expansion (per-staff DM, multiple
channels, templates, Teams/LINE WORKS); see CLAUDE.md「将来拡張」.

Phase 2 uses a **Bot Token** (`chat.postMessage`), not an Incoming Webhook. The
notification channel is chosen in the admin UI after OAuth (via conversations.list),
not on Slack's consent screen.

Secrets rule: this module never logs bot tokens, client secrets, or Webhook URLs.
`send_to_config` still accepts a legacy `{webhook_url}` config so pre-existing
webhook destinations (e.g. slack_delivery) keep working.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone, timedelta

import httpx

from app.config import settings
from app.services.honorific import with_honorific

logger = logging.getLogger(__name__)
_JST = timezone(timedelta(hours=9))

_AUTHORIZE_ENDPOINT = "https://slack.com/oauth/v2/authorize"
_ACCESS_ENDPOINT = "https://slack.com/api/oauth.v2.access"
_API_BASE = "https://slack.com/api"

# Bot Token Scopes. chat:write=送信, channels:read/groups:read=公開/非公開chの列挙,
# channels:join=公開chへのBot自動参加(conversations.join)。
_SCOPE = "chat:write,channels:read,groups:read,channels:join"

_HTTP_TIMEOUT = 10.0


class SlackOAuthError(Exception):
    """Raised when the Slack OAuth code exchange fails."""


class SlackApiError(Exception):
    """Raised when a Slack Web API call fails (transport error or ok=false)."""


async def _slack_get(token: str, method: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                f"{_API_BASE}/{method}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        return r.json()
    except Exception as e:  # transport/JSON — never include the token in the message
        raise SlackApiError(f"{method} request failed") from e


async def _slack_post(token: str, method: str, body: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.post(
                f"{_API_BASE}/{method}",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
        return r.json()
    except Exception as e:
        raise SlackApiError(f"{method} request failed") from e


async def send_slack_notification(webhook_url: str, message: str) -> bool:
    """Send a message to a Slack Incoming Webhook. Returns True on success.

    Retained for legacy/webhook destinations (e.g. slack_delivery). The reception
    Slack link now uses a Bot Token via `SlackNotifier.post_message`."""
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(webhook_url, json={"text": message})
            return r.status_code == 200
    except Exception:
        return False


class SlackNotifier:
    """Slack integration operations for a tenant (stateless helper)."""

    # ── OAuth ──────────────────────────────────────────────────────────────────
    @staticmethod
    def enabled() -> bool:
        return settings.slack_oauth_enabled

    @staticmethod
    def build_authorize_url(state: str) -> str:
        """Slack OAuth v2 authorize URL. `state` is the signed CSRF/tenant token."""
        params = {
            "client_id": settings.slack_client_id,
            "scope": _SCOPE,
            "redirect_uri": settings.slack_redirect_uri,
            "state": state,
        }
        return f"{_AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def exchange_code(code: str) -> dict:
        """Exchange an OAuth `code` for a Bot Token.

        Returns a config dict ready to persist (encrypted):
        {team_id, team_name, bot_access_token, bot_user_id, channel_id, channel_name,
         auth_method, created_at, updated_at}. channel_id/channel_name are empty — the
        admin picks the channel afterward (see set-channel flow). Raises SlackOAuthError
        on any failure. Never logs the response (it contains the bot token)."""
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                res = await client.post(
                    _ACCESS_ENDPOINT,
                    data={
                        "client_id": settings.slack_client_id,
                        "client_secret": settings.slack_client_secret,
                        "code": code,
                        "redirect_uri": settings.slack_redirect_uri,
                    },
                )
            payload = res.json()
        except Exception as e:  # network / JSON error — do not leak details
            raise SlackOAuthError("slack oauth request failed") from e

        if not payload.get("ok"):
            # payload["error"] is a Slack error code (e.g. invalid_code); safe, not secret.
            raise SlackOAuthError(str(payload.get("error") or "oauth_failed"))

        bot_token = payload.get("access_token") or ""
        if not bot_token:
            raise SlackOAuthError("no_bot_token")

        team = payload.get("team") or {}
        now = datetime.now(timezone.utc).isoformat()
        return {
            "team_id": team.get("id") or "",
            "team_name": team.get("name") or "",
            "bot_access_token": bot_token,
            "bot_user_id": payload.get("bot_user_id") or "",
            "channel_id": "",
            "channel_name": "",
            "auth_method": "bot",
            "created_at": now,
            "updated_at": now,
        }

    # ── Channels (Bot Token) ───────────────────────────────────────────────────
    @staticmethod
    async def list_channels(token: str) -> list[dict]:
        """List channels the bot can post to (public + private it belongs to).

        Returns [{id, name, is_private, is_member}] sorted by name. Raises SlackApiError
        on failure (missing scope, revoked token, …) so the caller can surface it."""
        _MAX_PAGES = 10  # 10 × 200 = 2000 channels; avoids unbounded loops
        out: list[dict] = []
        cursor = ""
        truncated = False
        for page in range(_MAX_PAGES):
            params = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            data = await _slack_get(token, "conversations.list", params)
            if not data.get("ok"):
                raise SlackApiError(str(data.get("error") or "conversations_list_failed"))
            for c in data.get("channels", []):
                out.append({
                    "id": c.get("id") or "",
                    "name": c.get("name") or "",
                    "is_private": bool(c.get("is_private")),
                    "is_member": bool(c.get("is_member")),
                })
            cursor = ((data.get("response_metadata") or {}).get("next_cursor") or "").strip()
            if not cursor:
                break
            if page == _MAX_PAGES - 1:
                truncated = True
        if truncated:
            # Don't silently drop channels: surface the cap so it can be raised if needed.
            logger.warning("Slack conversations.list truncated at %d channels (page cap reached)", len(out))
        out.sort(key=lambda c: c["name"])
        return out

    @staticmethod
    async def get_channel_info(token: str, channel_id: str) -> dict:
        """Return {id, name, is_private, is_member} for one channel. Raises SlackApiError."""
        data = await _slack_get(token, "conversations.info", {"channel": channel_id})
        if not data.get("ok"):
            raise SlackApiError(str(data.get("error") or "conversations_info_failed"))
        c = data.get("channel") or {}
        return {
            "id": c.get("id") or channel_id,
            "name": c.get("name") or "",
            "is_private": bool(c.get("is_private")),
            "is_member": bool(c.get("is_member")),
        }

    @staticmethod
    async def join_channel(token: str, channel_id: str) -> bool:
        """Join a public channel (conversations.join). Best-effort: private channels
        can't be self-joined (the bot must be invited). Returns True on success."""
        try:
            data = await _slack_post(token, "conversations.join", {"channel": channel_id})
            return bool(data.get("ok"))
        except SlackApiError:
            return False

    # ── Messaging ──────────────────────────────────────────────────────────────
    @staticmethod
    async def post_message(token: str, channel_id: str, text: str, blocks: list | None = None) -> bool:
        """Send `text` (+ optional Block Kit `blocks`) to `channel_id` via chat.postMessage.
        Best-effort → returns bool. `text` はブロック使用時も通知/フォールバック用に必須。

        If the bot isn't in a public channel yet (not_in_channel), it joins and retries
        once. Never raises (callers treat Slack as best-effort)."""
        if not token or not channel_id:
            return False
        body = {"channel": channel_id, "text": text}
        if blocks:
            body["blocks"] = blocks
        try:
            data = await _slack_post(token, "chat.postMessage", body)
            if data.get("ok"):
                return True
            if data.get("error") == "not_in_channel":
                if await SlackNotifier.join_channel(token, channel_id):
                    retry = await _slack_post(token, "chat.postMessage", body)
                    return bool(retry.get("ok"))
            return False
        except SlackApiError:
            return False

    @staticmethod
    async def send_to_config(config: dict, text: str, blocks: list | None = None) -> bool:
        """Send `text` (+ optional interactive `blocks`) to a stored Slack config's destination.

        Prefers the Bot Token path ({bot_access_token, channel_id}); falls back to a
        legacy Incoming Webhook ({webhook_url}) so pre-existing webhook destinations
        (e.g. slack_delivery) keep working. Webhook はボタン非対応のため text のみ送る。
        Best-effort → returns bool."""
        token = config.get("bot_access_token") or ""
        channel_id = config.get("channel_id") or ""
        if token and channel_id:
            return await SlackNotifier.post_message(token, channel_id, text, blocks=blocks)
        webhook_url = config.get("webhook_url") or ""
        if webhook_url:
            return await send_slack_notification(webhook_url, text)
        return False

    @staticmethod
    def build_reception_blocks(text: str, actions: list[dict], token: str) -> list[dict]:
        """受付通知の Block Kit(本文 + 受付/電話/お断り ボタン)を組み立てる。
        `text`=build_reception_message の本文, `actions`=[{action,title}],
        `token`=決定署名トークン(create_decision_token)。押下は各ボタンの value に
        `"{action}|{token}"` として運び、interactions エンドポイントで検証・適用する。"""
        style = {"accept": "primary", "decline": "danger"}
        buttons = []
        for a in actions:
            act = a["action"]
            btn = {
                "type": "button",
                "text": {"type": "plain_text", "text": a["title"], "emoji": True},
                "action_id": f"reception_decision_{act}",
                "value": f"{act}|{token}",
            }
            if act in style:
                btn["style"] = style[act]
            buttons.append(btn)
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "actions", "elements": buttons},
        ]

    @staticmethod
    def public_config(config: dict) -> dict:
        """Non-secret view of a stored Slack config for the admin UI.

        Deliberately omits bot_access_token / webhook_url. `connected` = OAuth done
        (bot token present, or a legacy webhook); `channel_configured` = a channel has
        been chosen (only then can chat.postMessage fire)."""
        has_bot = bool(config.get("bot_access_token"))
        has_webhook = bool(config.get("webhook_url"))
        channel_id = config.get("channel_id") or ""
        auth_method = config.get("auth_method") or ("bot" if has_bot else ("webhook" if has_webhook else ""))
        return {
            "connected": has_bot or has_webhook,
            # webhook links have a baked-in channel; treat them as channel-configured.
            "channel_configured": bool(channel_id) or (has_webhook and not has_bot),
            "team_name": config.get("team_name") or "",
            "channel_name": config.get("channel_name") or "",
            "channel_id": channel_id,
            "auth_method": auth_method,
            "connected_at": config.get("created_at") or config.get("connected_at") or "",
        }

    @staticmethod
    def build_reception_message(
        visitor_name: str,
        company: str | None = None,
        host_name: str | None = None,
        when: datetime | None = None,
        department: str | None = None,
    ) -> str:
        """Reception notification text. Company / department / host lines are omitted when
        blank; name + time are always present (see 作業指示 §7)."""
        lines = [":bell: 来客がありました", ""]
        if (company or "").strip():
            lines.append(f"会社名：{company.strip()}")
        lines.append(f"お名前：{with_honorific(visitor_name)}")
        if (department or "").strip():
            lines.append(f"訪問先部署：{department.strip()}")
        if (host_name or "").strip():
            lines.append(f"訪問先：{host_name.strip()}")
        lines.append(f"時刻：{_format_jst(when)}")
        lines.append("")
        lines.append("対応をお願いします。")
        return "\n".join(lines)


def _format_jst(when: datetime | None) -> str:
    """Format a timestamp as JST 'YYYY/MM/DD HH:MM'. Naive datetimes are assumed UTC
    (DB `func.now()` stores UTC); None means 'now'."""
    if when is None:
        dt = datetime.now(_JST)
    else:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        dt = when.astimezone(_JST)
    return dt.strftime("%Y/%m/%d %H:%M")
