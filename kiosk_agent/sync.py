"""Content sync daemon — polls remote content-manifest and downloads new media."""
import asyncio
import json
import mimetypes
import os
import socket
from pathlib import Path

import httpx

import locker_store
from config import settings
from state import get_device_name, get_device_token, save_device_state
from updater import read_version

# Last known force_update_at value — used to detect remote force-refresh signals
_last_force_update_at: str | None = None

def _manifest_file() -> Path:
    return settings.media_dir / "manifest.json"


def _load_manifest() -> dict[str, str]:
    """取り寄せ済みメディアの記録。無い・壊れている(停電で書きかけ等)ときは空として扱う
    (以前は例外で同期が止まった。空なら次の同期で取り寄せ直すだけ)。"""
    f = _manifest_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[sync] manifest.json を読めないため空として扱います: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(m: dict[str, str]) -> None:
    """一時ファイルに書いてから置き換える(書きかけのファイルを残さない)。"""
    f = _manifest_file()
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
    os.replace(tmp, f)


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
        # 管理画面での端末名変更を反映（device_state.json を最新に保つ → /config・/health・再起動時の整合）
        remote_name = data.get("device_name")
        if isinstance(remote_name, str) and remote_name and remote_name != get_device_name():
            save_device_state(token, remote_name)
            print(f"[sync] 端末名を更新しました → {remote_name}")
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
        print("[sync] デバイス未登録 — 起動時に自己登録し、管理画面で承認されると同期を開始します")
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


async def sync_loop() -> None:
    # 1 回の想定外の例外(ディスク満杯など)でこのタスクが終わると、再起動まで同期が二度と
    # 走らない。中身だけを包み、待ち(sleep)は外に置く(失敗が続いても空回りしない)。
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await check_force_refresh(client)
                await sync_once(client)
            except Exception as e:
                print(f"[sync] unexpected error: {e}")
            await asyncio.sleep(settings.sync_interval_sec)


_HEARTBEAT_INTERVAL_SEC = 60


async def _mirror_lockers(client: httpx.AsyncClient, token: str) -> None:
    """管理画面「ロッカー状況」表示用に占有スナップショットを best-effort でミラーする。

    ロッカーは端末が真実の源。操作(占有/解錠)が無くても定期的に送るので、再起動/デプロイ
    直後や無操作の端末でも管理画面がロッカーを表示できる（PIN 本体は送らない）。失敗しても
    解錠フローには一切影響しない。占有変化時の即時ミラー(main.py)とは独立の保険。"""
    try:
        await client.post(
            f"{settings.remote_api_url}/kiosk/lockers/mirror",
            headers={"X-Kiosk-Token": token},
            json=locker_store.mirror_payload(),
            timeout=10,
        )
    except Exception as e:
        print(f"[heartbeat] locker mirror failed: {e}")


def _lan_ip() -> str:
    """端末の LAN IP を推定する。外部へパケットは送らず、経路上のローカルIPを得るだけ。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        s.close()


async def heartbeat_loop() -> None:
    """60秒ごとに /kiosk/heartbeat を送信。コンテンツ同期とは独立して動作。
    端末テレメトリ（エージェント版数・LAN IP）を載せ、管理画面の端末詳細に表示させる。
    併せてロッカー占有スナップショットを best-effort でミラーする（管理画面の表示用）。"""
    async with httpx.AsyncClient() as client:
        while True:
            # sync_loop と同じく、想定外の例外でタスクごと終わらないよう中身だけを包む。
            try:
                token = get_device_token()
                if token:
                    try:
                        resp = await client.post(
                            f"{settings.remote_api_url}/kiosk/heartbeat",
                            headers={"X-Kiosk-Token": token},
                            json={"version": read_version(), "ip": _lan_ip()},
                            timeout=10,
                        )
                        if resp.status_code not in (200, 204):
                            print(f"[heartbeat] unexpected status {resp.status_code}")
                    except Exception as e:
                        print(f"[heartbeat] failed: {e}")
                    await _mirror_lockers(client, token)
            except Exception as e:
                print(f"[heartbeat] unexpected error: {e}")
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
