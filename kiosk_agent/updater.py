"""OTA bundle updater for mokuture+ kiosk agent.

Flow:
  1. On startup (after 15 s) and every NORMAL_INTERVAL seconds, fetch bundle manifest.
  2. If remote version differs from local, download changed files to STAGING_DIR.
  3. Set self.pending so /update-status reports ready=True.
  4. kiosk.html polls /update-status; when screen is idle (or force=True), calls
     POST /apply-update which triggers this module's apply().
  5. If any Python source files changed, apply() schedules a service restart via
     os._exit(0) so systemd (Restart=always) brings the agent back up cleanly.
"""

import asyncio
import hashlib
import logging
import os
import shutil
from pathlib import Path

import httpx

from config import settings
from state import get_device_token

log = logging.getLogger(__name__)

_APP_DIR    = Path(__file__).parent
STAGING_DIR = Path("/tmp/mokuture-staging")
_VERSION_FILE = _APP_DIR / ".bundle_version"

# Files managed by OTA (relative to kiosk_agent root).
MANAGED_FILES = [
    "static/kiosk.html",
    "main.py",
    "updater.py",
    "gpio.py",
    "sync.py",
    "state.py",
    "config.py",
]

# Changing these files requires a service restart to take effect.
RESTART_FILES = {"main.py", "updater.py", "gpio.py", "sync.py", "state.py", "config.py"}

NORMAL_INTERVAL = 1800   # 30 min between normal checks
FORCE_INTERVAL  = 60     # 1 min when a force-flagged update is pending


def _local_hash(rel: str) -> str:
    p = _APP_DIR / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def read_version() -> str:
    return _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else ""


def _save_version(v: str) -> None:
    _VERSION_FILE.write_text(v)


class BundleUpdater:
    def __init__(self) -> None:
        self._pending: dict | None = None
        self._lock = asyncio.Lock()

    # ── Public state ──────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._pending is not None

    def is_force(self) -> bool:
        return self._pending is not None and bool(self._pending.get("force"))

    # ── Background loop ───────────────────────────────────────────────────────

    async def run(self) -> None:
        await asyncio.sleep(15)  # let the server fully start first
        while True:
            try:
                await self._check_and_stage()
            except Exception:
                log.exception("[updater] check failed")
            wait = FORCE_INTERVAL if (self._pending and self._pending.get("force")) else NORMAL_INTERVAL
            await asyncio.sleep(wait)

    # ── Core logic ────────────────────────────────────────────────────────────

    async def _check_and_stage(self) -> None:
        token = get_device_token()
        if not token:
            return

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{settings.remote_api_url}/kiosk/bundle/manifest",
                    headers={"X-Kiosk-Token": token},
                    timeout=15,
                )
                resp.raise_for_status()
            except Exception as e:
                log.warning(f"[updater] manifest fetch failed: {e}")
                return

        manifest = resp.json()
        remote_ver = manifest["version"]
        force = manifest.get("force", False)

        if remote_ver == read_version():
            # Same version — only update the force flag in an already-staged pending.
            async with self._lock:
                if self._pending is not None:
                    self._pending = {**self._pending, "force": force}
            return

        log.info(f"[updater] new version {remote_ver} (current: {read_version()})")
        await self._download(manifest, token)

    async def _download(self, manifest: dict, token: str) -> None:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        changed: list[str] = []

        async with httpx.AsyncClient() as client:
            for f in manifest.get("files", []):
                rel         = f["path"]
                remote_hash = f["hash"]

                if _local_hash(rel) == remote_hash:
                    continue  # unchanged — skip download

                log.info(f"[updater] downloading {rel}")
                try:
                    r = await client.get(
                        f"{settings.remote_api_url}/kiosk/bundle/file/{rel}",
                        headers={"X-Kiosk-Token": token},
                        timeout=60,
                    )
                    r.raise_for_status()
                except Exception as e:
                    log.error(f"[updater] download failed {rel}: {e}")
                    shutil.rmtree(STAGING_DIR, ignore_errors=True)
                    return  # abort staging; retry next cycle

                dest = STAGING_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                changed.append(rel)

        if not changed:
            # All hashes matched — just advance version without touching files.
            _save_version(manifest["version"])
            return

        log.info(f"[updater] staged {len(changed)} file(s): {changed}")
        async with self._lock:
            self._pending = {**manifest, "_changed": changed}

    # ── Apply ─────────────────────────────────────────────────────────────────

    async def apply(self) -> bool:
        """Copy staged files to app dir.  Returns True if a service restart is needed."""
        async with self._lock:
            if self._pending is None:
                return False

            changed      = self._pending.get("_changed", [])
            version      = self._pending["version"]
            needs_restart = False

            for rel in changed:
                src = STAGING_DIR / rel
                dst = _APP_DIR / rel
                if not src.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                log.info(f"[updater] applied {rel}")
                if Path(rel).name in RESTART_FILES:
                    needs_restart = True

            _save_version(version)
            self._pending = None
            shutil.rmtree(STAGING_DIR, ignore_errors=True)

        return needs_restart


updater = BundleUpdater()
