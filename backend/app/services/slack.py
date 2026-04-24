import httpx


async def send_slack_notification(webhook_url: str, message: str) -> bool:
    """Send a message to a Slack Incoming Webhook. Returns True on success."""
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(webhook_url, json={"text": message})
            return r.status_code == 200
    except Exception:
        return False
