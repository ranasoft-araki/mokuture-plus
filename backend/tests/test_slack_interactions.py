from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.api import notifications
from app.services.auth import create_decision_token
from conftest import add_reception  # type: ignore[import-not-found]


def _signed_payload(secret: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    raw = urlencode({"payload": json.dumps(payload, ensure_ascii=False)}).encode()
    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode() + b":" + raw
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return raw, {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }


async def test_slack操作は即時ackし元メッセージ更新を通知送信より先に行う(
    client, tenant, monkeypatch,
):
    secret = "slack-test-secret"
    monkeypatch.setattr(notifications.settings, "slack_signing_secret", secret)
    log = await add_reception(tenant.id, "田中太郎")
    token = create_decision_token(log.id, tenant.id)
    calls: list[tuple[str, object]] = []

    async def fake_update(url: str, body: dict) -> None:
        calls.append(("update", body))

    async def fake_notify(tenant_id: str, log_id: str) -> None:
        calls.append(("notify", log_id))

    monkeypatch.setattr(notifications, "_post_slack_response_url", fake_update)
    monkeypatch.setattr(notifications.reception_notify, "fire_decision_notifications", fake_notify)

    payload = {
        "actions": [{"value": f"accept|{token}"}],
        "user": {"id": "U-FIRST", "real_name": "田中太郎"},
        "message": {"text": "来客がありました"},
        "response_url": "https://hooks.slack.test/response/1",
    }
    raw, headers = _signed_payload(secret, payload)
    response = await client.post("/api/notifications/slack/interactions", content=raw, headers=headers)

    assert response.status_code == 200
    assert response.content == b""
    assert [name for name, _ in calls] == ["update", "notify"]
    assert "田中太郎" in calls[0][1]["blocks"][1]["elements"][0]["text"]

    # 後から押した人には、先着者を示す更新だけを返し、確定通知は再送しない。
    calls.clear()
    payload["user"] = {"id": "U-SECOND", "real_name": "佐藤花子"}
    payload["response_url"] = "https://hooks.slack.test/response/2"
    raw, headers = _signed_payload(secret, payload)
    response = await client.post("/api/notifications/slack/interactions", content=raw, headers=headers)

    assert response.status_code == 200
    assert response.content == b""
    assert [name for name, _ in calls] == ["update"]
    assert "田中太郎" in calls[0][1]["blocks"][1]["elements"][0]["text"]
