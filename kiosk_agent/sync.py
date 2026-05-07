"""Content sync daemon — polls remote content-manifest and downloads new media."""
import asyncio
import json
import mimetypes
from pathlib import Path

import httpx

from config import settings
from state import get_device_token

# Last known force_update_at value — used to detect remote force-refresh signals
_last_force_update_at: str | None = None

def _manifest_file() -> Path:
    return settings.media_dir / "manifest.json"


def _load_manifest() -> dict[str, str]:
    f = _manifest_file()
    if f.exists():
        return json.loads(f.read_text())
    return {}


def _save_manifest(m: dict[str, str]) -> None:
    _manifest_file().write_text(json.dumps(m, indent=2))


def _ext(mime_type: str) -> str:
    ext = mimetypes.guess_extension(mime_type)
    return ".jpg" if ext == ".jpe" else (ext or "")


def media_path(media_id: str, mime_type: str) -> Path:
    return settings.media_dir / f"{media_id}{_ext(mime_type)}"


def find_media(media_id: str) -> Path | None:
    if not settings.media_dir.exists():
        return None
    for p in settings.media_dir.iterdir():
        if p.stem == media_id and p.suffix != ".json":
            return p
    return None


async def check_force_refresh(client: httpx.AsyncClient) -> None:
    """Poll /kiosk/schedule and trigger a reload if force_update_at has changed."""
    global _last_force_update_at
    token = get_device_token()
    if not token:
        return
    try:
        resp = await client.get(
            f"{settings.remote_api_url}/kiosk/schedule",
            headers={"X-Kiosk-Token": token},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        fat = data.get("force_update_at")
        if fat is not None and fat != _last_force_update_at:
            _last_force_update_at = fat
            print(f"[sync] force_update_at が変更されました ({fat}) — 設定を再読み込みします")
            # Trigger settings reload: log prominently so the kiosk process notices.
            # The kiosk HTML polls /proxy/schedule independently and will pick up any
            # content changes on its next cycle. This log line signals a forced reload
            # has been requested by the admin.
            print("[sync] FORCE_REFRESH: admin requested immediate settings reload")
        else:
            if _last_force_update_at is None and fat is not None:
                _last_force_update_at = fat
    except Exception as e:
        print(f"[sync] force-refresh check failed: {e}")


async def sync_once(client: httpx.AsyncClient) -> None:
    token = get_device_token()
    if not token:
        print("[sync] デバイス未登録 — /setup で PIN を登録してください")
        return
    try:
        resp = await client.get(
            f"{settings.remote_api_url}/kiosk/content-manifest",
            headers={"X-Kiosk-Token": token},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[sync] manifest fetch failed: {e}")
        return

    remote_items = resp.json().get("items", [])
    manifest = _load_manifest()

    for item in remote_items:
        mid = item["id"]
        mt = item["mime_type"]
        target = media_path(mid, mt)

        if target.exists() and manifest.get(mid) == mt:
            continue

        kb = item.get("size_bytes", 0) // 1024
        print(f"[sync] downloading {item['filename']} ({kb} KB)")
        try:
            dl = await client.get(item["url"], timeout=180, follow_redirects=True)
            dl.raise_for_status()
            target.write_bytes(dl.content)
            manifest[mid] = mt
            _save_manifest(manifest)
            print(f"[sync] saved → {target.name}")
        except Exception as e:
            print(f"[sync] download error {mid}: {e}")

    # Remove stale files no longer in any schedule
    remote_ids = {i["id"] for i in remote_items}
    for mid in list(manifest.keys()):
        if mid not in remote_ids:
            stale = find_media(mid)
            if stale:
                stale.unlink(missing_ok=True)
            del manifest[mid]
    _save_manifest(manifest)
    print(f"[sync] 完了 — キャッシュ {len(manifest)} 件")


async def sync_loop() -> None:
    async with httpx.AsyncClient() as client:
        while True:
            await check_force_refresh(client)
            await sync_once(client)
            await asyncio.sleep(settings.sync_interval_sec)


_HEARTBEAT_INTERVAL_SEC = 60


async def heartbeat_loop() -> None:
    """60秒ごとに /kiosk/heartbeat を送信。コンテンツ同期とは独立して動作。"""
    async with httpx.AsyncClient() as client:
        while True:
            token = get_device_token()
            if token:
                try:
                    resp = await client.post(
                        f"{settings.remote_api_url}/kiosk/heartbeat",
                        headers={"X-Kiosk-Token": token},
                        timeout=10,
                    )
                    if resp.status_code not in (200, 204):
                        print(f"[heartbeat] unexpected status {resp.status_code}")
                except Exception as e:
                    print(f"[heartbeat] failed: {e}")
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
