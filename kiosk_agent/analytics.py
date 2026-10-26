"""端末側の分析ログ（スプール・アップロード・稼働メトリクス）。

設計は リポジトリ直下の `ANALYTICS.md`。この モジュールが担うのは3つ:

1. **ブラウザからのイベントを受け取り、ディスクへ先に書いてから ack する**
   （ブラウザにデバイストークンを持たせないための中継でもある）。
2. **端末稼働イベント**（起動/停止/再起動/ブラウザ異常終了/オンライン・オフライン）を記録する。
3. **定期メトリクス**（既定60秒のハートビート、既定300秒ごとに CPU/温度/メモリ等）を記録する。

送信は指数バックオフ付きのアップローダが1本だけ行い、成功した行だけスプールから消す。
**通信断の間もローカルに溜まり、復旧後に順番どおり再送される**＝稼働率の分母（電源が入って
いた時間）が通信状態に左右されない。

新しい pip 依存は増やしていない（httpx は既存）。
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import time
import uuid
from pathlib import Path

import httpx

import sysinfo
from config import settings
from state import get_device_token

_AGENT_DIR = Path(__file__).parent
SPOOL_DIR = Path(os.getenv("ANALYTICS_SPOOL_DIR", str(_AGENT_DIR / "analytics_spool")))
# 「正常停止したか」のマーカー。停止時に消し、起動時に残っていれば異常終了だったと分かる。
_RUNNING_MARK = SPOOL_DIR / "running.mark"

# ── 設定（すべて環境変数で変更可 / ANALYTICS.md §9-3） ──────────────────────
HEARTBEAT_SEC = int(os.getenv("ANALYTICS_HEARTBEAT_SEC", "60"))
METRICS_SEC = int(os.getenv("ANALYTICS_METRICS_SEC", "300"))
FLUSH_SEC = int(os.getenv("ANALYTICS_FLUSH_SEC", "15"))
# ブラウザのハートビートがこれ以上途切れたら「受付アプリが落ちている」とみなす。
BROWSER_STALE_SEC = int(
    os.getenv("ANALYTICS_BROWSER_STALE_SEC", str(settings.systemd_watchdog_browser_stale_sec))
)
# 起動時に OS の uptime がこれ未満なら「端末が起動した」と判定する。
BOOT_WINDOW_SEC = int(os.getenv("ANALYTICS_BOOT_WINDOW_SEC", "180"))
# スプールの上限行数（種類ごと）。超えたら古い行から捨てて log_dropped を残す。
MAX_SPOOL_LINES = int(os.getenv("ANALYTICS_MAX_SPOOL_LINES", "20000"))
# 1回のアップロードで送る件数（バックエンドの上限 200 と揃える）。
UPLOAD_BATCH = int(os.getenv("ANALYTICS_UPLOAD_BATCH", "200"))
# 1回のブラウザ投入で受け付ける件数。
MAX_BROWSER_BATCH = 200

_BACKOFF_BASE_SEC = 2.0
_BACKOFF_MAX_SEC = 300.0

KIND_EVENTS = "events"
KIND_DEVICE_EVENTS = "device_events"
KIND_METRICS = "device_metrics"

_ENDPOINT = {
    KIND_EVENTS: "/analytics/events",
    KIND_DEVICE_EVENTS: "/analytics/device-events",
    KIND_METRICS: "/analytics/device-metrics",
}
_ID_FIELD = {KIND_EVENTS: "event_id", KIND_DEVICE_EVENTS: "id", KIND_METRICS: "id"}


def _now_iso() -> str:
    """UTC の ISO8601（末尾 Z）。DB は naive-UTC 保存なので送信も UTC で揃える。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def _agent_version() -> str:
    try:
        from updater import read_version

        return (read_version() or "")[:32]
    except Exception:
        return ""


# ── スプール（JSONL・種類ごとに1ファイル） ─────────────────────────────────

class Spool:
    """追記のみの JSONL。**先にディスクへ書いてから** 呼び出し元へ ack する。

    行数は多くても数万なので、取り出し/削除は都度の読み書きで足りる
    （1分1行のハートビートで 1 日 1,440 行）。
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self._lock = asyncio.Lock()
        self.dropped: dict[str, int] = {}

    def _path(self, kind: str) -> Path:
        return self.dir / f"{kind}.jsonl"

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _append_sync(self, kind: str, records: list[dict]) -> int:
        self._ensure_dir()
        path = self._path(kind)
        with path.open("a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # 電源断でも ack 済みの行が消えないように
        return self._trim_sync(kind)

    def _trim_sync(self, kind: str) -> int:
        """上限を超えたら **古い行から** 捨てる。捨てた件数を返す。"""
        path = self._path(kind)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return 0
        if len(lines) <= MAX_SPOOL_LINES:
            return 0
        excess = len(lines) - MAX_SPOOL_LINES
        path.write_text("\n".join(lines[excess:]) + "\n", encoding="utf-8")
        self.dropped[kind] = self.dropped.get(kind, 0) + excess
        return excess

    async def append(self, kind: str, records: list[dict]) -> int:
        if not records:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._append_sync, kind, records)

    def _take_sync(self, kind: str, limit: int) -> list[dict]:
        path = self._path(kind)
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue  # 壊れた行は捨てる（次の削除で消える）
                    if len(out) >= limit:
                        break
        except Exception:
            return []
        return out

    async def take(self, kind: str, limit: int = UPLOAD_BATCH) -> list[dict]:
        async with self._lock:
            return await asyncio.to_thread(self._take_sync, kind, limit)

    def _drop_sync(self, kind: str, ids: set[str]) -> None:
        path = self._path(kind)
        if not path.exists() or not ids:
            return
        id_field = _ID_FIELD[kind]
        kept: list[str] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except Exception:
                        continue
                    if rec.get(id_field) in ids:
                        continue
                    kept.append(raw)
        except Exception:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        tmp.replace(path)

    async def drop(self, kind: str, ids: set[str]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._drop_sync, kind, ids)

    def pending_counts(self) -> dict[str, int]:
        counts = {}
        for kind in _ENDPOINT:
            path = self._path(kind)
            try:
                counts[kind] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            except Exception:
                counts[kind] = 0
        return counts


# ── 端末の分析ログ本体 ───────────────────────────────────────────────────────

class DeviceAnalytics:
    def __init__(self, browser_state, spool: Spool | None = None) -> None:
        # watchdog.BrowserHeartbeatState（ブラウザの生存確認）を共有する
        self.browser_state = browser_state
        self.spool = spool or Spool(SPOOL_DIR)
        self.online: bool | None = None
        self._offline_since: float | None = None
        self._seq = 0
        self._last_page_id: str | None = None
        self._browser_alive = False
        self._crash_reported = False
        self._agent_version = _agent_version()
        self._os_version = sysinfo.os_version()
        self._ui_version = ""  # ブラウザが app_started で申告する

    # ── 記録 ────────────────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def record_device_event(
        self,
        event_name: str,
        *,
        detail_code: str | None = None,
        duration_ms: int | None = None,
        count: int | None = None,
    ) -> None:
        """端末稼働イベントを1件スプールへ。失敗してもキオスクは止めない。"""
        try:
            await self.spool.append(
                KIND_DEVICE_EVENTS,
                [
                    {
                        "id": str(uuid.uuid4()),
                        "occurred_at": _now_iso(),
                        "sequence_no": self._next_seq(),
                        "event_name": event_name,
                        "detail_code": detail_code,
                        "duration_ms": duration_ms,
                        "count": count,
                        "agent_version": self._agent_version or None,
                        "ui_version": self._ui_version or None,
                        "os_version": self._os_version,
                        "uptime_sec": sysinfo.uptime_sec(),
                    }
                ],
            )
        except Exception:
            pass

    async def record_metric(self, *, with_metrics: bool) -> None:
        """メトリクス1件（ハートビート）をスプールへ。"""
        try:
            payload = self.browser_state.snapshot()
            age = payload.get("last_age_sec")
            last = payload.get("last_payload") or {}
            screen = last.get("screen") or None
            fresh = age is not None and age <= BROWSER_STALE_SEC
            # 正常稼働 = ブラウザが生きている & バックエンドへ到達できている &
            #            承認待ち/停止中の画面ではない（ANALYTICS.md §10）。
            # `online` が None（起動直後でまだ一度も送信していない）は「到達性が不明」なので
            # 正常稼働に数えない。アップローダは 15 秒ごとに回るのですぐ確定する。
            healthy = bool(fresh and self.online is True and screen not in (None, "pending", "suspended"))
            row = {
                "id": str(uuid.uuid4()),
                "measured_at": _now_iso(),
                "interval_sec": HEARTBEAT_SEC,
                "online": self.online,
                "app_healthy": healthy,
                "browser_age_sec": age,
                "screen_id": _normalize_screen(screen),
                "agent_version": self._agent_version or None,
                "ui_version": self._ui_version or None,
            }
            row.update(sysinfo.snapshot(with_metrics=with_metrics))
            # camera / mic は main.py 側の既存プローブを使う（循環 import を避けて遅延取得）
            row["camera_connected"], row["mic_connected"] = _peripheral_status(with_metrics)
            await self.spool.append(KIND_METRICS, [row])
        except Exception:
            pass

    async def submit_browser_events(self, events: list[dict]) -> dict:
        """ブラウザから受け取ったイベントをディスクへ書いてから ack する。

        返す `accepted` に載った `event_id` だけをブラウザは IndexedDB から消す
        （＝ディスクに残っていないイベントは消えない）。
        """
        if not isinstance(events, list):
            return {"accepted": [], "rejected": [{"id": None, "reason": "not_a_list"}]}
        events = events[:MAX_BROWSER_BATCH]
        accepted, rejected = [], []
        rows = []
        for ev in events:
            if not isinstance(ev, dict) or not isinstance(ev.get("event_id"), str):
                rejected.append({"id": None, "reason": "malformed"})
                continue
            rows.append(ev)
            accepted.append(ev["event_id"])
        if rows:
            await self.spool.append(KIND_EVENTS, rows)
            # ブラウザが申告する UI 版数を端末イベント/メトリクスにも載せる
            ui = rows[-1].get("ui_version")
            if isinstance(ui, str) and ui:
                self._ui_version = ui[:32]
        return {"accepted": accepted, "rejected": rejected}

    # ── 起動・停止 ──────────────────────────────────────────────────────────
    async def on_startup(self) -> None:
        """エージェント起動時。端末の起動/再起動・前回の異常終了を判定して記録する。"""
        uptime = sysinfo.uptime_sec()
        unclean = _RUNNING_MARK.exists()
        try:
            SPOOL_DIR.mkdir(parents=True, exist_ok=True)
            _RUNNING_MARK.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass
        await self.record_device_event("agent_started")
        if uptime is not None and uptime < BOOT_WINDOW_SEC:
            # OS が起動したばかり＝端末の電源投入/再起動
            await self.record_device_event(
                "device_restart" if unclean else "device_boot",
                detail_code="unclean_shutdown" if unclean else "clean_shutdown",
            )
        # 前回捨てたイベントがあれば件数だけ残す（本文は残さない）
        for kind, count in list(self.spool.dropped.items()):
            if count:
                await self.record_device_event("log_dropped", detail_code="spool_overflow", count=count)
                self.spool.dropped[kind] = 0

    async def on_shutdown(self) -> None:
        """systemd 停止時。正常停止として記録し、マーカーを消す。"""
        await self.record_device_event("device_shutdown", detail_code="systemd_stop")
        await self.record_device_event("agent_stopped", detail_code="clean_shutdown")
        try:
            _RUNNING_MARK.unlink(missing_ok=True)
        except Exception:
            pass
        # 停止直前に1回だけ送信を試みる（届かなければ次回起動後に再送される）
        try:
            await asyncio.wait_for(self.flush_once(), timeout=5)
        except Exception:
            pass

    # ── ブラウザの生死 ──────────────────────────────────────────────────────
    async def on_browser_heartbeat(self, payload: dict) -> None:
        """`POST /device/kiosk-heartbeat` から呼ぶ。ページの起動/リロードを検出する。"""
        page_id = payload.get("page_id")
        if isinstance(page_id, str) and page_id:
            if self._last_page_id is None:
                await self.record_device_event("browser_started")
            elif page_id != self._last_page_id:
                await self.record_device_event("page_reloaded")
            self._last_page_id = page_id
        if payload.get("booted"):
            # 受付アプリが立ち上がりきった（ページ読み込み＝browser_started とは別に残す）
            await self.record_device_event("app_started")
        ui = payload.get("ui_version")
        if isinstance(ui, str) and ui:
            self._ui_version = ui[:32]
        self._browser_alive = True
        self._crash_reported = False

    async def check_browser_health(self) -> None:
        """ハートビートが途切れたら `app_crashed` を1回だけ記録する。"""
        age = self.browser_state.snapshot().get("last_age_sec")
        if age is None or self._crash_reported:
            return
        if age > BROWSER_STALE_SEC:
            self._crash_reported = True
            await self.record_device_event(
                "app_crashed", detail_code="heartbeat_stale", duration_ms=int(age * 1000)
            )

    # ── アップロード ────────────────────────────────────────────────────────
    async def _upload_kind(self, client: httpx.AsyncClient, token: str, kind: str) -> bool | None:
        """1バッチ送る。True=送れた / False=失敗 / None=送るものが無い。"""
        batch = await self.spool.take(kind, UPLOAD_BATCH)
        if not batch:
            return None
        resp = await client.post(
            f"{settings.remote_api_url}{_ENDPOINT[kind]}",
            headers={"X-Kiosk-Token": token},
            json={"events": batch},
            timeout=20,
        )
        if resp.status_code >= 500 or resp.status_code in (401, 403, 408, 429):
            # 一時的な失敗・認証待ち（承認前を含む）。捨てずに残して次回へ。
            return False
        if resp.status_code >= 400:
            # 400/413/422 など「送り直しても通らない」バッチ。無限リトライでスプールを
            # 詰まらせないよう捨て、件数だけ log_dropped に残す（本文は残さない）。
            await self.spool.drop(
                kind, {rec.get(_ID_FIELD[kind]) for rec in batch if rec.get(_ID_FIELD[kind])}
            )
            await self.record_device_event(
                "log_dropped", detail_code="upload_failed", count=len(batch)
            )
            return True
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        done: set[str] = set()
        done.update(data.get("accepted") or [])
        done.update(data.get("duplicate") or [])
        # reject された行は送り直しても通らないので消す（理由はサーバ側に残る）
        done.update(r.get("id") for r in (data.get("rejected") or []) if isinstance(r, dict) and r.get("id"))
        if not done and resp.status_code < 400:
            # 何も返ってこない実装差異への保険。送れた分は消す。
            done = {rec.get(_ID_FIELD[kind]) for rec in batch if rec.get(_ID_FIELD[kind])}
        await self.spool.drop(kind, {d for d in done if d})
        return True

    async def flush_once(self) -> bool:
        """全種類を1巡させる。1つでも送れたら True。"""
        token = get_device_token()
        if not token:
            return False
        sent_any = False
        async with httpx.AsyncClient() as client:
            for kind in (KIND_DEVICE_EVENTS, KIND_EVENTS, KIND_METRICS):
                try:
                    result = await self._upload_kind(client, token, kind)
                except Exception:
                    await self._set_online(False)
                    return False
                if result is False:
                    await self._set_online(False)
                    return False
                if result:
                    sent_any = True
        # 送るものが無かった回は到達性が分からないので online の判定を変えない
        # （根拠なく online イベントを出さない）。
        if sent_any:
            await self._set_online(True)
        return sent_any

    async def _set_online(self, value: bool) -> None:
        if self.online is value:
            return
        previous = self.online
        self.online = value
        if value:
            downtime = None
            if self._offline_since is not None:
                downtime = int((time.monotonic() - self._offline_since) * 1000)
                self._offline_since = None
            if previous is False:
                await self.record_device_event("network_recovered", duration_ms=downtime)
            await self.record_device_event("online")
        else:
            self._offline_since = time.monotonic()
            await self.record_device_event("offline")

    # ── ループ ──────────────────────────────────────────────────────────────
    async def uploader_loop(self) -> None:
        """指数バックオフ付きのアップローダ。短時間に大量リクエストを出さない。"""
        delay = FLUSH_SEC
        while True:
            try:
                await asyncio.sleep(delay)
                ok = await self.flush_once()
                if ok or self.online:
                    delay = FLUSH_SEC
                else:
                    delay = min(_BACKOFF_MAX_SEC, max(_BACKOFF_BASE_SEC, delay * 2))
                    delay *= 1 + random.uniform(-0.2, 0.2)  # ジッタ（同時再送の山を崩す）
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = min(_BACKOFF_MAX_SEC, max(_BACKOFF_BASE_SEC, delay * 2))

    async def metrics_loop(self) -> None:
        """ハートビート（既定60秒）。既定300秒ごとに CPU/温度/メモリ等も載せる。"""
        ticks = 0
        every = max(1, METRICS_SEC // max(1, HEARTBEAT_SEC))
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_SEC)
                ticks += 1
                await self.check_browser_health()
                await self.record_metric(with_metrics=(ticks % every == 0))
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def status(self) -> dict:
        """`/health` に載せる軽量な状態（秘密情報は含まない）。"""
        return {
            "online": self.online,
            "pending": self.spool.pending_counts(),
            "agent_version": self._agent_version,
            "ui_version": self._ui_version,
            "os_version": self._os_version,
            "heartbeat_sec": HEARTBEAT_SEC,
            "metrics_sec": METRICS_SEC,
        }


# ── ヘルパ ───────────────────────────────────────────────────────────────────

_SCREEN_ALIAS = {
    "lockerMode": "locker_mode",
    "resultOk": "result_ok",
    "resultPhone": "result_phone",
    "resultDecline": "result_decline",
    "kiosk-settings": "kiosk_settings",
}


def _normalize_screen(screen: str | None) -> str | None:
    """`go()` の内部名を分析ログの `screen_id` へ正規化する。

    スタッフ専用の設定画面は記録しない（Wi-Fi パスワード等を含む画面のため）。
    """
    if not screen:
        return None
    name = _SCREEN_ALIAS.get(screen, screen)
    if name == "kiosk_settings":
        return None
    return name


def _peripheral_status(with_metrics: bool) -> tuple[bool | None, bool | None]:
    """(カメラ, マイク) の接続状態。重いので metrics のタイミングだけ実測する。"""
    if not with_metrics or platform.system() != "Linux":
        return None, None
    try:
        import main as agent_main  # 遅延 import（起動時の循環を避ける）

        cam = bool(agent_main._camera_status().get("available"))
        mic = bool(agent_main._microphone_status().get("available"))
        return cam, mic
    except Exception:
        return None, None
