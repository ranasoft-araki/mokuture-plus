import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Any


log = logging.getLogger(__name__)


@dataclass
class BrowserHeartbeatState:
    last_seen_monotonic: float | None = None
    last_payload: dict[str, Any] | None = None
    seen_count: int = 0

    def record(self, payload: dict[str, Any]) -> None:
        self.last_seen_monotonic = time.monotonic()
        self.last_payload = payload
        self.seen_count += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        age_sec = None
        if self.last_seen_monotonic is not None:
            age_sec = round(max(0.0, now - self.last_seen_monotonic), 1)
        return {
            "seen_count": self.seen_count,
            "last_age_sec": age_sec,
            "last_payload": self.last_payload,
        }


class SystemdWatchdog:
    def __init__(
        self,
        *,
        browser_state: BrowserHeartbeatState,
        browser_required: bool,
        browser_startup_grace_sec: int,
        browser_stale_sec: int,
    ) -> None:
        self.browser_state = browser_state
        self.browser_required = browser_required
        self.browser_startup_grace_sec = browser_startup_grace_sec
        self.browser_stale_sec = browser_stale_sec
        self.started_monotonic = time.monotonic()
        self.notify_socket = os.getenv("NOTIFY_SOCKET", "")
        self.watchdog_usec = self._parse_watchdog_usec(os.getenv("WATCHDOG_USEC", ""))
        self.enabled = bool(self.notify_socket and self.watchdog_usec > 0)
        self.interval_sec = max(1.0, (self.watchdog_usec / 1_000_000) / 2) if self.enabled else 0.0
        self._last_unhealthy_reason: str | None = None

    async def ready(self, status: str | None = None) -> None:
        if not self.enabled:
            return
        fields = ["READY=1"]
        if status:
            fields.append(f"STATUS={status}")
        await asyncio.to_thread(self._notify, "\n".join(fields))

    async def run(self) -> None:
        if not self.enabled:
            return
        while True:
            healthy, reason = self._browser_health()
            if healthy:
                self._last_unhealthy_reason = None
                await asyncio.to_thread(self._notify, f"WATCHDOG=1\nSTATUS={self._healthy_status()}")
            else:
                if reason != self._last_unhealthy_reason:
                    log.warning("[watchdog] unhealthy: %s", reason)
                    self._last_unhealthy_reason = reason
                await asyncio.to_thread(self._notify, f"STATUS={reason}")
            await asyncio.sleep(self.interval_sec)

    def status(self) -> dict[str, Any]:
        healthy, reason = self._browser_health()
        return {
            "enabled": self.enabled,
            "browser_required": self.browser_required,
            "healthy": healthy,
            "reason": reason,
            "interval_sec": self.interval_sec if self.enabled else None,
            "browser": self.browser_state.snapshot(),
        }

    def _healthy_status(self) -> str:
        browser = self.browser_state.snapshot()
        age = browser.get("last_age_sec")
        if age is None:
            return "watchdog healthy; browser heartbeat not seen yet"
        payload = browser.get("last_payload") or {}
        screen = f"; screen={payload['screen']}" if payload.get("screen") else ""
        return f"watchdog healthy; browser heartbeat age={age}s{screen}"

    def _browser_health(self) -> tuple[bool, str]:
        if not self.browser_required:
            return True, "browser heartbeat not required"

        age = self._browser_age_sec()
        if age is None:
            since_start = time.monotonic() - self.started_monotonic
            if since_start <= self.browser_startup_grace_sec:
                return True, "waiting for initial browser heartbeat"
            return False, "browser heartbeat never received"

        if age > self.browser_stale_sec:
            return False, f"browser heartbeat stale ({age:.1f}s > {self.browser_stale_sec}s)"
        return True, "browser heartbeat fresh"

    def _browser_age_sec(self) -> float | None:
        last = self.browser_state.last_seen_monotonic
        if last is None:
            return None
        return max(0.0, time.monotonic() - last)

    @staticmethod
    def _parse_watchdog_usec(raw: str) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _notify(self, payload: str) -> None:
        if not self.notify_socket:
            return
        addr: str | bytes = self.notify_socket
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(payload.encode("utf-8", errors="replace"))
