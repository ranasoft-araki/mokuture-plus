"""Microsoft Teams への通知（Teams の「ワークフロー」の Webhook へカードを投稿する）。

Teams 側の準備は利用者が行う: チャネル（またはチャット）で「ワークフロー」→
「Webhook 要求を受信するとチャネルに投稿する」を作り、表示された URL を管理画面に貼る。
mokuture はその URL へ Adaptive Card を POST するだけ（Bot・Azure の登録は要らない）。

- **旧方式の「Incoming Webhook（コネクタ）」は受け付けない**（Microsoft が廃止を進めている。
  `*.webhook.office.com`）。受け付けるのはワークフロー（Power Automate / Logic Apps）の URL だけ。
- **カードのボタンはリンクしか開けない**（Webhook 投稿のカードは Teams の中で返事を受け取れない）。
  受付/電話/お断り は、ログイン無しで返事できる画面 `/{slug}/respond` を開くリンクにする
  （`services/decision_link.py`）。押したあとカードは書き換えられないので、返事が済んだことは
  別のカードで知らせる。
- **ワークフローは受け取っただけで 202 を返す**。投稿できたかどうかまでは分からない
  （ワークフローの中で失敗しても mokuture には見えない）。テスト送信の結果もそう伝える。
- **来訪者の入力は Teams のマークダウンとして無害化する**（`escape_md`）。カードの文字は
  常にマークダウンとして描かれ、素の文字として出す指定が無いため。
- URL は Webhook と同じく秘密（知っていれば誰でも投稿できる）。画面・ログに出さない。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from app.services import url_safety
from app.services.honorific import with_honorific
from app.services.timeutil import format_jst

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0

# ワークフロー(Power Automate / Logic Apps)の Webhook URL のホスト。
#   旧: https://prod-NN.<region>.logic.azure.com:443/workflows/...
#   新: https://<env>.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/...
_WORKFLOW_HOST_SUFFIXES = (
    "logic.azure.com",
    "powerplatform.com",
    "powerautomate.com",
)
_LEGACY_CONNECTOR_SUFFIXES = ("webhook.office.com", "outlook.office.com")

LEGACY_URL_MESSAGE = (
    "この URL は旧方式の「Incoming Webhook（コネクタ）」のものです。Microsoft が廃止を進めているため使えません。"
    "Teams の「ワークフロー」で「Webhook 要求を受信するとチャネルに投稿する」を作り、その URL を貼ってください"
)
NOT_WORKFLOW_MESSAGE = (
    "Teams の「ワークフロー」の URL ではありません。"
    "「Webhook 要求を受信するとチャネルに投稿する」を作ったときに表示される URL を貼ってください"
)


def _host(url: str) -> str:
    try:
        return (urlsplit((url or "").strip()).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


async def validate_url(url: str) -> None:
    """保存してよい Teams の URL か確かめる。駄目なら `url_safety.UnsafeUrlError`(日本語の理由)。"""
    host = _host(url)
    if _host_matches(host, _LEGACY_CONNECTOR_SUFFIXES):
        raise url_safety.UnsafeUrlError(LEGACY_URL_MESSAGE)
    if not _host_matches(host, _WORKFLOW_HOST_SUFFIXES):
        raise url_safety.UnsafeUrlError(NOT_WORKFLOW_MESSAGE)
    await url_safety.validate_public_url(url)


# ── 無害化 ───────────────────────────────────────────────────────────────────

# マークダウンとして働く文字を、見た目の近い全角の文字に寄せる（エスケープ記法は当てにしない）。
_MD_CHARS = str.maketrans({
    "\\": "＼", "*": "＊", "_": "＿", "~": "～", "`": "｀",
    "[": "［", "]": "］", "(": "（", ")": "）",
    "#": "＃", "<": "＜", ">": "＞", "{": "｛", "}": "｝", "|": "｜",
})
_LIST_HEAD = re.compile(r"^(\s*)([-+])(\s)")
_ORDERED_HEAD = re.compile(r"^(\s*\d+)\.(\s)")


def escape_md(value: str | None) -> str:
    """来訪者の入力(氏名・会社名など)をカードへ入れる前に無害化する。

    リンク `[x](https://…)`・太字・見出し・引用・コード、行頭の箇条書きを無効にし、改行は詰める
    （1 項目 1 行。改行で見出しや箇条書きを作らせない）。"""
    text = re.sub(r"[\r\n\t]+", " ", value or "").translate(_MD_CHARS)
    text = _LIST_HEAD.sub(lambda m: f"{m.group(1)}{'－' if m.group(2) == '-' else '＋'}{m.group(3)}", text)
    text = _ORDERED_HEAD.sub(r"\1．\2", text)
    return text


# ── カード ───────────────────────────────────────────────────────────────────

def _payload(body: list[dict], actions: list[dict] | None = None) -> dict:
    """ワークフローの「チャネルに投稿する」が受け取る形（attachments の Adaptive Card を投稿する）。"""
    card: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def _heading(text: str, *, attention: bool = False) -> dict:
    block = {"type": "TextBlock", "text": text, "size": "Large", "weight": "Bolder", "wrap": True}
    if attention:
        block["color"] = "Attention"
    return block


def build_reception_card(
    *,
    visitor_name: str,
    company: str | None,
    host_name: str | None,
    department: str | None,
    purpose: str | None,
    when: datetime | None,
    escalated_from: str | None = None,
    decision_links: list[tuple[str, str]] | None = None,
    admin_url: str = "",
) -> dict:
    """受付通知のカード。`decision_links` は [(ボタンの文字, 返事用の画面の URL)]。"""
    facts: list[dict] = []
    if (company or "").strip():
        facts.append({"title": "会社名", "value": escape_md(company.strip())})
    facts.append({"title": "お名前", "value": escape_md(with_honorific(visitor_name))})
    if (department or "").strip():
        facts.append({"title": "訪問先部署", "value": escape_md(department.strip())})
    if (host_name or "").strip():
        facts.append({"title": "訪問先", "value": escape_md(host_name.strip())})
    if (purpose or "").strip():
        facts.append({"title": "ご用件", "value": escape_md(purpose.strip())})
    facts.append({"title": "受付時刻", "value": format_jst(when)})

    if escalated_from:
        body = [
            _heading("⚠️ 受付に応答がありません（代理通知）", attention=True),
            {
                "type": "TextBlock",
                "text": f"「{escape_md(escalated_from)}」宛の受付に応答がありません。代わりに対応をお願いします。",
                "wrap": True,
            },
        ]
    else:
        body = [
            _heading("🔔 来客がありました"),
            {"type": "TextBlock", "text": "受付にお客様がお待ちです。対応をお願いします。", "wrap": True},
        ]
    body.append({"type": "FactSet", "facts": facts})

    actions: list[dict] = []
    for i, (title, url) in enumerate(decision_links or []):
        action = {"type": "Action.OpenUrl", "title": title, "url": url}
        if i == 0:
            action["style"] = "positive"
        actions.append(action)
    if actions:
        body.append({
            "type": "TextBlock",
            "text": "ボタンを押すとブラウザが開きます。開いた画面でもう一度押すと返事が確定し、受付の画面に伝わります（ログインは要りません）。",
            "wrap": True, "size": "Small", "isSubtle": True,
        })
    if admin_url:
        body.append({
            "type": "TextBlock",
            "text": f"[受付ログを開く]({admin_url})（ログインが必要です）",
            "wrap": True, "size": "Small", "isSubtle": True,
        })
    return _payload(body, actions)


def build_text_card(title: str, lines: list[str], *, attention: bool = False) -> dict:
    """見出し＋本文だけのカード（対応済みのお知らせ・配達の通知・テスト送信）。

    `lines` は**無害化済み**の行（呼び出し側が来訪者・端末の入力を `escape_md` に通す）。"""
    body = [_heading(title, attention=attention)]
    body += [{"type": "TextBlock", "text": line, "wrap": True} for line in lines if line.strip()]
    return _payload(body)


def build_delivery_card(
    title: str, lines: list[str], decision_links: list[tuple[str, str]] | None = None
) -> dict:
    """配達の呼び出し（受付/電話のボタン付き）・置き配のカード。`lines` は無害化済み。"""
    payload = build_text_card(title, lines)
    actions = []
    for i, (label, url) in enumerate(decision_links or []):
        action = {"type": "Action.OpenUrl", "title": label, "url": url}
        if i == 0:
            action["style"] = "positive"
        actions.append(action)
    if actions:
        card = payload["attachments"][0]["content"]
        card["body"].append({
            "type": "TextBlock",
            "text": "ボタンを押すとブラウザが開きます。開いた画面でもう一度押すと返事が確定します（ログインは要りません）。",
            "wrap": True, "size": "Small", "isSubtle": True,
        })
        card["actions"] = actions
    return payload


# ── 送信 ─────────────────────────────────────────────────────────────────────

async def post(url: str, payload: dict) -> bool:
    """送れたら True(=ワークフローが受け取った)。best-effort なので例外は投げない。

    送る直前にも宛先を確かめる。転送(リダイレクト)には従わない。URL はログに出さない。"""
    host = _host(url)
    if not _host_matches(host, _WORKFLOW_HOST_SUFFIXES):
        logger.warning("teams: url is not a workflow webhook; not sent")
        return False
    if not await url_safety.is_public_url(url):
        return False
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            logger.warning("teams: workflow returned HTTP %s", resp.status_code)
            return False
        return True
    except Exception as e:
        logger.warning("teams: post failed (%s)", type(e).__name__)
        return False


# ── 設定の読み出し ───────────────────────────────────────────────────────────

async def load_default_url(db, tenant_id: str) -> str:
    """管理画面「Teams」カードで登録した URL(テナント共通)。無ければ空文字。"""
    from sqlalchemy import select

    from app.models.notification import NotificationSetting
    from app.services.crypto import decrypt_dict

    row = (await db.execute(select(NotificationSetting).where(
        NotificationSetting.tenant_id == tenant_id,
        NotificationSetting.type == "teams",
    ))).scalar_one_or_none()
    if row is None or not row.config_json or row.config_json == "{}":
        return ""
    try:
        return (decrypt_dict(row.config_json).get("webhook_url") or "").strip()
    except Exception:
        return ""
