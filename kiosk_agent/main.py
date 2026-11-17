"""mokuture+ Local Kiosk Device Agent"""
import asyncio
import ipaddress
import os
import platform
import re
import socket
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import analytics as analytics_mod
import kana_kanji
import locker_store
from config import settings
from gpio import DoorSensor, LockerController, PirSensor
try:
    from gpio import gpio_status
except ImportError:  # OTA で main.py だけ先に新しくなっても起動を止めない
    def gpio_status() -> dict[str, object]:
        import gpio as _g
        return {"hardware": bool(getattr(_g, "_HW", False)), "reason": None}
from state import clear_device_state, get_device_name, get_device_token, is_registered, save_device_state
from sync import find_media, heartbeat_loop, sync_loop
from updater import updater, read_version
from watchdog import BrowserHeartbeatState, SystemdWatchdog


def _hardware_id() -> str:
    """物理端末の安定ID。/etc/machine-id → MAC の順で解決する。
    (tenant_slug, hardware_id) でバックエンドが再登録を冪等化し、承認待ちの重複を防ぐ。"""
    try:
        mid = Path("/etc/machine-id").read_text().strip()
        if mid:
            return mid
    except Exception:
        pass
    return f"mac-{uuid.getnode():012x}"


def _hostname() -> str:
    try:
        return socket.gethostname() or "kiosk"
    except Exception:
        return "kiosk"

# Linux以外(Windowsなど開発環境)は自動でモック扱いにする
_MOCK_DEVICE = (
    os.getenv("MOCK_GPIO", "false").lower() == "true"
    or platform.system() != "Linux"
)

# ── device helpers ────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 5) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _get_volume_linux() -> tuple[int, str | None]:
    """(音量0-100, エラー文字列|None) を返す。"""
    # amixer: Master → PCM → Headphone → Digital の順で試す
    for ctrl in ("Master", "PCM", "Headphone", "Digital", "Speaker"):
        try:
            r = _run(["amixer", "get", ctrl])
            if r.returncode == 0:
                m = re.search(r'\[(\d+)%\]', r.stdout)
                if m:
                    return int(m.group(1)), None
        except FileNotFoundError:
            break  # amixer 自体が無い
        except Exception:
            continue
    # pactl (PulseAudio / PipeWire)
    try:
        r = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        if r.returncode == 0:
            m = re.search(r'(\d+)%', r.stdout)
            if m:
                return int(m.group(1)), None
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return 70, "amixer/pactl が見つからないか、有効なミキサーコントロールがありません"


def _set_volume_linux(level: int) -> str | None:
    """音量を設定。成功時 None、失敗時エラー文字列を返す。"""
    pct = f"{level}%"
    errors: list[str] = []
    for ctrl in ("Master", "PCM", "Headphone", "Digital", "Speaker"):
        try:
            r = _run(["amixer", "sset", ctrl, pct])
            if r.returncode == 0:
                return None
            errors.append(f"amixer {ctrl}: {r.stderr.strip()}")
        except FileNotFoundError:
            errors.append("amixer: コマンドが見つかりません")
            break
        except Exception as e:
            errors.append(f"amixer {ctrl}: {e}")
    try:
        r = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pct])
        if r.returncode == 0:
            return None
        errors.append(f"pactl: {r.stderr.strip()}")
    except FileNotFoundError:
        errors.append("pactl: コマンドが見つかりません")
    except Exception as e:
        errors.append(f"pactl: {e}")
    return " / ".join(errors)


_wifi_last_debug: dict[str, object] = {}


def _split_nmcli_terse(line: str) -> list[str]:
    """nmcli -t の ':' 区切りを、バックスラッシュエスケープ込みで分解する。"""
    parts: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == ":":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if escaped:
        buf.append("\\")
    parts.append("".join(buf))
    return parts


def _parse_nmcli_wifi_rows(output: str) -> list[dict]:
    """nmcli terse 出力をパースする。"""
    nets: list[dict] = []
    seen: set[str] = set()
    malformed = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_nmcli_terse(line)
        if len(parts) != 4:
            malformed += 1
            continue
        in_use_raw, ssid, sig_str, security = (part.strip() for part in parts)
        if not ssid or ssid == "--" or ssid in seen:
            continue
        seen.add(ssid)
        in_use = in_use_raw in ("*", "yes", "はい")
        sig = int(sig_str) if sig_str.isdigit() else 0
        level = 4 if sig >= 75 else 3 if sig >= 50 else 2 if sig >= 25 else 1
        nets.append({
            "ssid": ssid,
            "signal": sig,
            "level": level,
            "lock": bool(security and security not in ("--", "")),
            "connected": in_use,
        })
    nets.sort(key=lambda n: (not n["connected"], -n["signal"]))
    if malformed:
        print(f"[wifi] skipped malformed rows: {malformed}", flush=True)
    return nets


def _wifi_saved_ssids() -> tuple[set[str], str | None]:
    """保存済みのWi-Fi接続プロファイル名(=通常はSSID)を返す。"""
    try:
        r = _run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            timeout=12,
        )
        if r.returncode != 0:
            return set(), r.stderr.strip() or r.stdout.strip() or "saved profiles lookup failed"
        names: set[str] = set()
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            parts = _split_nmcli_terse(line)
            if len(parts) != 2:
                continue
            name, conn_type = (part.strip() for part in parts)
            if conn_type == "802-11-wireless" and name:
                names.add(name)
        return names, None
    except FileNotFoundError:
        return set(), "nmcli が見つかりません"
    except subprocess.TimeoutExpired:
        return set(), "saved profiles lookup timeout"
    except Exception as e:
        return set(), str(e)


def _wifi_networks() -> tuple[list[dict], str | None]:
    """(ネットワーク一覧, エラー文字列|None) を返す。"""
    global _wifi_last_debug
    try:
        r = _run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,SIGNAL,SECURITY",
                "dev",
                "wifi",
                "list",
            ],
            timeout=12,
        )
        if r.returncode != 0:
            _wifi_last_debug = {
                "mode": "terse",
                "returncode": r.returncode,
                "stderr": r.stderr.strip(),
                "stdout_sample": r.stdout.splitlines()[:8],
            }
            return [], f"nmcli エラー: {r.stderr.strip()}"
        nets = _parse_nmcli_wifi_rows(r.stdout)
        saved_ssids, saved_err = _wifi_saved_ssids()
        for net in nets:
            net["known"] = net["ssid"] in saved_ssids
        row_count = len([ln for ln in r.stdout.splitlines() if ln.strip()])
        _wifi_last_debug = {
            "mode": "terse",
            "returncode": r.returncode,
            "rows": row_count,
            "parsed": len(nets),
            "stdout_sample": r.stdout.splitlines()[:8],
            "ssids": [n["ssid"] for n in nets[:8]],
            "saved_profiles": len(saved_ssids),
        }
        if saved_err:
            _wifi_last_debug["saved_profiles_error"] = saved_err
        print(f"[wifi] nmcli rows={row_count} parsed={len(nets)}", flush=True)
        if nets:
            print(f"[wifi] ssids={[n['ssid'] for n in nets[:8]]}", flush=True)
        else:
            sample = r.stdout.splitlines()[:8]
            print(f"[wifi] raw sample={sample}", flush=True)
        return nets, None
    except FileNotFoundError:
        _wifi_last_debug = {"mode": "terse", "error": "nmcli not found"}
        return [], "nmcli が見つかりません (NetworkManager がインストールされていますか?)"
    except subprocess.TimeoutExpired:
        _wifi_last_debug = {"mode": "terse", "error": "timeout"}
        return [], "nmcli タイムアウト"
    except Exception as e:
        _wifi_last_debug = {"mode": "terse", "error": str(e)}
        return [], str(e)


def _wifi_connect(ssid: str, password: str) -> tuple[bool, str | None]:
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    try:
        r = _run(cmd, timeout=30)
        if r.returncode == 0:
            return True, None
        return False, r.stderr.strip() or r.stdout.strip() or "接続に失敗しました"
    except FileNotFoundError:
        return False, "nmcli が見つかりません"
    except subprocess.TimeoutExpired:
        return False, "接続タイムアウト"
    except Exception as e:
        return False, str(e)


def _wifi_toggle(on: bool) -> str | None:
    try:
        r = _run(["nmcli", "radio", "wifi", "on" if on else "off"])
        if r.returncode != 0:
            return r.stderr.strip()
        return None
    except FileNotFoundError:
        return "nmcli が見つかりません"
    except Exception as e:
        return str(e)


def _camera_status() -> dict[str, object]:
    if _MOCK_DEVICE:
        return {
            "device": settings.camera_device,
            "available": True,
            "name": "Mock USB Camera",
            "detail": "mock",
        }

    device = Path(settings.camera_device)
    status: dict[str, object] = {
        "device": settings.camera_device,
        "available": device.exists(),
        "name": None,
        "detail": None,
    }
    if not device.exists():
        status["detail"] = "device not found"
        return status

    try:
        r = _run(["v4l2-ctl", "--device", settings.camera_device, "--all"])
        if r.returncode == 0:
            match = re.search(r"Card type\s*:\s*(.+)", r.stdout)
            if match:
                status["name"] = match.group(1).strip()
        elif r.stderr.strip():
            status["detail"] = r.stderr.strip()
    except FileNotFoundError:
        status["detail"] = "v4l2-ctl not found"
    except Exception as e:
        status["detail"] = str(e)
    return status


def _microphone_status() -> dict[str, object]:
    if _MOCK_DEVICE:
        return {
            "available": True,
            "name": "Mock USB Microphone",
            "detail": "mock",
        }

    status: dict[str, object] = {
        "available": False,
        "name": None,
        "detail": None,
    }

    try:
        r = _run(["arecord", "-l"])
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                # Support both English and Japanese locale outputs from `arecord -l`.
                bracket_names = re.findall(r"\[([^\]]+)\]", line)
                if not bracket_names:
                    continue
                match = re.search(r"(?:card|カード)\s+\d+.*?(?:device|デバイス)\s+\d+:\s*([^\[]+)", line)
                if match:
                    card_name = bracket_names[0].strip()
                    device_name = match.group(1).strip()
                    status["available"] = True
                    status["name"] = f"{card_name} / {device_name}"
                    return status
            status["detail"] = "capture device not found"
            return status
        if r.stderr.strip():
            status["detail"] = r.stderr.strip()
    except FileNotFoundError:
        status["detail"] = "arecord not found"
    except Exception as e:
        status["detail"] = str(e)

    return status


# ── ロッカーの口数プリセット（3口/7口。設置者がキオスク設定画面でタッチ選択） ──────
# 商品ラインナップは 3口/7口 の2パターンで、増設分の電気錠リレー/ドアセンサーの配線は
# 標準化されている＝ピンマップは既知の定数。よって「口数」の選択だけで台帳・GPIO が決まり、
# 現場では JSON を触らせずタッチUIで 3口↔7口 を切り替えられる（選択は locker_store に
# ローカル永続化）。GPIO の物理検出では口数を自動判定できない（リードスイッチは pull_up で
# 「未接続」と「開扉」が同じHIGH、リレーは出力でフィードバック無し）ため、この明示選択を採る。
#
# 1〜3口のベースは env(LOCKER_PINS_JSON/DOOR_PINS_JSON)を優先（後方互換）。7口の増設4口は
# 下記の既定ピンで補う。※実機ハーネスに合わせて確定すること（配線は標準化＝固定値）。env に
# 7口ぶん書けばそちらが優先されるので、既定ピンが実配線と違う場合は env で上書きも可能。
LOCKER_COUNTS = [3, 7]
DEFAULT_LOCKER_COUNT = 3
_EXTRA_LOCKER_PINS = {"4": 23, "5": 24, "6": 25, "7": 8}   # 増設4口の電子錠リレー(BCM)
_EXTRA_DOOR_PINS = {"4": 5, "5": 6, "6": 13, "7": 19}       # 増設4口のドアセンサー(BCM)


def _pins_for_count(base: dict[str, int], extra: dict[str, int], count: int) -> dict[str, int]:
    """口数 count 分のピンマップを作る。base(env優先)に無い口は extra(既定ピン)で補う。"""
    out: dict[str, int] = {}
    for i in range(1, count + 1):
        k = str(i)
        if k in base:
            out[k] = int(base[k])
        elif k in extra:
            out[k] = int(extra[k])
    return out


def _locker_pins_for(count: int) -> dict[str, int]:
    return _pins_for_count(settings.locker_pins, _EXTRA_LOCKER_PINS, count)


def _door_pins_for(count: int) -> dict[str, int]:
    return _pins_for_count(settings.door_pins, _EXTRA_DOOR_PINS, count)


def _env_default_locker_count() -> int:
    """未選択時の既定口数を env のピン構成から推定する。既存の実機端末が env(7口ぶんの
    *_PINS_JSON)で運用されていた場合に、この変更で 3口 へ勝手に縮小しないための後方互換。
    env のスロット数を満たす最大の許可口数（無ければ 3）を返す。"""
    nums: set[int] = set()
    for src in (settings.door_pins, settings.locker_pins):
        for key in (src or {}).keys():
            try:
                nums.add(int(key))
            except (TypeError, ValueError):
                continue
    n = len(nums)
    best = DEFAULT_LOCKER_COUNT
    for c in sorted(LOCKER_COUNTS):
        if n >= c:
            best = c
    return best


def _current_locker_count() -> int:
    """設置者が選んだ口数。未選択(初回/既存端末)は env 構成から既定を推定、不正値は既定3。"""
    c = locker_store.get_locker_count()
    if c in LOCKER_COUNTS:
        return c
    return _env_default_locker_count()


locker_ctrl = LockerController(
    _locker_pins_for(DEFAULT_LOCKER_COUNT),
    default_pulse_sec=settings.locker_pulse_sec,
)
try:
    from gpio import make_presence_sensor
    pir = make_presence_sensor(
        getattr(settings, "presence_sensor", "pir"),
        settings.pir_pin,
        threshold_mm=getattr(settings, "tof_threshold_mm", 1000),
        confirm_reads=getattr(settings, "tof_confirm_reads", 3),
        stale_sec=getattr(settings, "tof_stale_sec", 60.0),
    )
except ImportError:  # OTA で main.py だけ先に新しくなっても起動を止めない
    pir = PirSensor(settings.pir_pin)
doors = {
    door_id: DoorSensor(pin)
    for door_id, pin in sorted(_door_pins_for(DEFAULT_LOCKER_COUNT).items(), key=lambda item: item[0])
}


def _apply_locker_count(count: int) -> None:
    """選択された口数に合わせて GPIO コントローラ（リレー/ドアセンサー）を作り直す。"""
    global locker_ctrl, doors
    _cancel_all_state_timers()   # 作り直す前の錠に向けた自動の通電OFFを残さない
    try:
        locker_ctrl.close()
    except Exception:
        pass
    for d in doors.values():
        try:
            d.close()
        except Exception:
            pass
    locker_ctrl = LockerController(
        _locker_pins_for(count),
        default_pulse_sec=settings.locker_pulse_sec,
    )
    doors = {
        door_id: DoorSensor(pin)
        for door_id, pin in sorted(_door_pins_for(count).items(), key=lambda item: item[0])
    }


def _gpio_unintended_mock() -> bool:
    """実機(Linux)なのに GPIO が模擬に落ちているか(gpiozero が読み込めない等)。

    開発機(非Linux)と MOCK_GPIO=true は意図した模擬なので False。この状態では電子錠を
    動かせないのに、模擬は「動かした」と答えてしまう。"""
    return not _MOCK_DEVICE and not bool(gpio_status().get("hardware"))


def _door_closed(door_number) -> bool | None:
    """扉センサーの読み。True=閉 / False=開 / None=分からない。

    None になるのは、その扉にセンサーが設定されていないときと、センサーが実機の GPIO で
    読めていないとき(開発機・MOCK_GPIO・実機で模擬に落ちた場合)。模擬の DoorSensor は
    設定済みの扉を常に「開」(False)と答えるので、そのまま使うと全ロッカーが使えなくなる。"""
    if not bool(gpio_status().get("hardware")):
        return None
    if door_number is None:
        return None
    sensor = doors.get(str(door_number))
    if sensor is None or not sensor.configured:
        return None
    try:
        value = sensor.is_closed
    except Exception:
        return None
    if not isinstance(value, bool):
        return None
    if value:
        locker_store.mark_door_seen_closed(door_number)
        return True
    # 「開」は、その扉で一度でも「閉」を読めたことがあるときだけ信じる。センサーを
    # つないでいない入力はずっと「開」と読めるので、真に受けると全部の口が使えなくなる。
    try:
        seen = int(door_number) in locker_store.doors_seen_closed()
    except (TypeError, ValueError):
        seen = False
    return False if seen else None


def _configured_door_numbers() -> list[int]:
    """ロッカー台帳の口数（＝置き配で使える口数）を返す。設置者が選んだ口数（3 or 7）を
    そのまま台帳のドア番号 [1..N] にする。GPIO の物理検出では口数を自動判定できないため、
    キオスク設定画面のタッチ選択（locker_store に永続化）を真実の源とする。"""
    return list(range(1, _current_locker_count() + 1))


def _doors_without_lock() -> list[int]:
    """いまの口数のうち、電子錠のつなぎ先(LOCKER_PINS_JSON)が登録されていない口の番号。

    台帳は口数から作るので、つなぎ先が無い口も来訪者の画面には「空き」で出て、タッチすると
    /open が 404 で開けられない(古い .env の LOCKER_PINS_JSON={} など)。設定画面と
    デバイスチェックに原因を出すために返す。"""
    return [n for n in _configured_door_numbers() if not locker_ctrl.is_configured(str(n))]

# ── ドアセンサー連動の自動施錠 ──────────────────────────────────────────────────
# 電気ストライク(通電ON=解錠 / 無通電OFF=施錠位置)向け。解錠通電後、扉が開いたら即無通電に
# 戻す。以後は閉扉でラッチ(ツノ)が自動施錠されるため、開錠パルス長や「扉を閉めました」操作の
# タイミングに依存せず確実に施錠できる。ドアセンサーが無いロッカーは従来の固定パルスにフォール
# バックする。※有効化には DOOR_PINS_JSON のキーを door_number(=LOCKER_PINS_JSON のキー)と
# 一致させること。
_OPEN_WINDOW_SEC = float(os.getenv("LOCKER_OPEN_WINDOW_SEC", "12"))
_OPEN_AFTER_DELAY_SEC = float(os.getenv("LOCKER_OPEN_AFTER_DELAY_SEC", "1"))
_bg_tasks: set = set()
browser_heartbeat_state = BrowserHeartbeatState()
systemd_watchdog = SystemdWatchdog(
    browser_state=browser_heartbeat_state,
    browser_required=settings.systemd_watchdog_browser_required,
    browser_startup_grace_sec=settings.systemd_watchdog_browser_startup_grace_sec,
    browser_stale_sec=settings.systemd_watchdog_browser_stale_sec,
)
# 分析ログ（ANALYTICS.md）: 端末稼働イベント/メトリクスの記録と、ブラウザイベントの中継。
# ブラウザのハートビート状態は watchdog と共有する（二重に持たない）。
device_analytics = analytics_mod.DeviceAnalytics(browser_heartbeat_state)


def _spawn(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def _open_with_autolock(locker_id: str, door: DoorSensor, *, energized: bool = False) -> None:
    """解錠(通電)し、扉が開いたら(または上限時間で)無通電へ戻す。
    energized=True は呼び出し側が通電まで済ませて成否を確かめた場合(_drive_unlock)。"""
    if not energized:
        locker_ctrl.set_state(locker_id, True)   # 解錠(通電)
    waited = 0.0
    try:
        while waited < _OPEN_WINDOW_SEC:
            if door.configured:
                # 扉が開いたら少し待ってから施錠位置へ戻す
                if door.is_closed is False:
                    await asyncio.sleep(_OPEN_AFTER_DELAY_SEC)
                    break
            await asyncio.sleep(0.15)
            waited += 0.15
    finally:
        locker_ctrl.set_state(locker_id, False)  # 無通電=施錠位置(閉扉で自動施錠)


_LOCK_DRIVE_FAILED = "電子錠を動かせませんでした。担当者にお知らせください。"


async def _drive_unlock(locker_id: str) -> dict | None:
    """電子錠を解錠側へ動かす。動かせたら {state, autolock}、動かせなければ None。

    「動かせなかった」に含めるもの: 錠が構成されていない・リレー操作の失敗・実機で GPIO が
    模擬に落ちている(模擬は成功と答えるが錠は動いていない)。開発機・MOCK_GPIO の模擬は成功扱い。
    扉センサーがある口は、通電の成否をここで確かめてから「開いたら無通電へ戻す」見張りを裏で回す。"""
    lid = str(locker_id)
    if not locker_ctrl.is_configured(lid) or _gpio_unintended_mock():
        return None
    _cancel_state_timer(lid)
    door = doors.get(lid)
    if door is not None and door.configured:
        try:
            ok = locker_ctrl.set_state(lid, True)
        except Exception as e:
            print(f"[locker] unlock {lid} failed: {e}")
            ok = False
        if not ok:
            return None
        _spawn(_open_with_autolock(lid, door, energized=True))
        return {"state": "opening", "autolock": True}
    # センサーの無い口: 固定パルス。通電の成否だけここで確かめ、戻すのは裏で行う
    # (パルスが終わるまで待って返すと、画面の「扉を押して開けてください」が錠の戻った後に出る)。
    try:
        ok = locker_ctrl.set_state(lid, True)
    except Exception as e:
        print(f"[locker] unlock {lid} failed: {e}")
        ok = False
    if not ok:
        return None
    _spawn(_pulse_off_later(lid))
    return {"state": "opened", "autolock": False}


async def _pulse_off_later(locker_id: str) -> None:
    try:
        await asyncio.sleep(max(0.0, float(settings.locker_pulse_sec)))
    finally:
        try:
            locker_ctrl.set_state(locker_id, False)
        except Exception as e:
            print(f"[locker] relock {locker_id} failed: {e}")


# ── 「錠を通電したままにする」(デバイスチェックのトグル)の自動 OFF ──────────────
# 電気ストライクは通電しっぱなしだと解錠のまま・コイルも熱を持つ。押し忘れや誤操作の ON が
# 残らないよう、ON から一定時間で自動的に OFF に戻す。ON を押し直すと数え直し、OFF で取り消す。
_STATE_ON_MAX_SEC = 30.0
_state_off_tasks: dict[str, asyncio.Task] = {}


def _cancel_state_timer(locker_id: str) -> None:
    task = _state_off_tasks.pop(str(locker_id), None)
    if task is not None and not task.done():
        task.cancel()


def _cancel_all_state_timers() -> None:
    for lid in list(_state_off_tasks):
        _cancel_state_timer(lid)


async def _state_auto_off(locker_id: str) -> None:
    lid = str(locker_id)
    try:
        await asyncio.sleep(_STATE_ON_MAX_SEC)
        try:
            locker_ctrl.set_state(lid, False)
        except Exception as e:
            print(f"[locker] auto-off {lid} failed: {e}")
    finally:
        if _state_off_tasks.get(lid) is asyncio.current_task():
            _state_off_tasks.pop(lid, None)


def _start_state_timer(locker_id: str) -> None:
    lid = str(locker_id)
    _cancel_state_timer(lid)
    _state_off_tasks[lid] = _spawn(_state_auto_off(lid))


# ── ロッカー操作の直列化と、暗証番号の試行回数 ──────────────────────────────
# 占有・受け取り・全解除は await をまたぐ(照合は別スレッド・錠の駆動も待つ)ので、同じ口を
# 2 つの操作が同時に触らないよう 1 本のロックで順番にする(locker_store の RLock は同じ
# イベントループ上のコルーチン同士を止めない)。
_locker_op_lock = asyncio.Lock()
# 暗証番号の総当たりを防ぐ。口ごとに続けて 5 回違えば 5 分受け付けない(合えば数え直し)。
# メモリだけに持つ(再起動で消える)。
_PIN_MAX_FAILS = 5
_PIN_LOCKOUT_SEC = 300.0
_PIN_FAIL_WINDOW_SEC = 600.0   # この時間のうちに _PIN_MAX_FAILS 回違えたら受け付けを止める
_pin_failures: dict[str, dict] = {}
_PIN_LOCKED_DETAIL = "暗証番号を続けて間違えたため、このロッカーはしばらく受け付けません。担当者にお知らせいただくか、時間をおいてお試しください。"


def _pin_locked_remaining(locker_id: str) -> float:
    st = _pin_failures.get(str(locker_id))
    if not st or not st.get("until"):
        return 0.0
    left = st["until"] - time.monotonic()
    if left <= 0:
        _pin_failures.pop(str(locker_id), None)   # 期限が過ぎたら数え直し
        return 0.0
    return left


def _pin_record_failure(locker_id: str) -> bool:
    """違う暗証番号を 1 回数える。上限に達したら True(以後しばらく受け付けない)。"""
    now = time.monotonic()
    st = _pin_failures.setdefault(str(locker_id), {"count": 0, "until": 0.0, "first": now})
    # 「続けて」違えた回数だけを数える。何日も前の打ち間違いまで積み上げない。
    if now - st.get("first", now) > _PIN_FAIL_WINDOW_SEC:
        st["count"] = 0
        st["first"] = now
    st["count"] += 1
    if st["count"] >= _PIN_MAX_FAILS:
        st["until"] = time.monotonic() + _PIN_LOCKOUT_SEC
        return True
    return False


# 名刺読み取り（QR無し来訪者の受付フォーム自動入力）。
# opencv / onnxruntime は任意依存なので、入っていない端末では import に失敗する。
# その場合でもキオスク本体は従来どおり動かし、/card/* を生やさないだけにする。
# 画面側は起動時に /card/status を見て、使えなければ名刺の導線を出さない。
try:
    from card.api import purge_loop as card_purge_loop, router as card_router, warmup_sync as card_warmup
    _CARD_IMPORT_ERROR = ""
except Exception as _e:          # ImportError 以外（モデル破損など）でも止めない
    card_purge_loop = None       # type: ignore[assignment]
    card_router = None           # type: ignore[assignment]
    card_warmup = None           # type: ignore[assignment]
    _CARD_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

_KIOSK_HTML = Path(__file__).parent / "static" / "kiosk.html"
_JSQR_JS   = Path(__file__).parent / "static" / "jsqr.min.js"
_ANALYTICS_JS = Path(__file__).parent / "static" / "analytics.js"
_TAP_MP3   = Path(__file__).parent / "static" / "tap.mp3"
_CONTROL_PANEL_HTML = Path(__file__).parent / "static" / "device-control.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    # ロッカー台帳は端末が権威。設置者が選んだ口数(永続化)に合わせて GPIO を組み、台帳を生成
    _apply_locker_count(_current_locker_count())
    locker_store.ensure_local_roster(_configured_door_numbers())
    task = asyncio.create_task(sync_loop())
    update_task = asyncio.create_task(updater.run())
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    watchdog_task = asyncio.create_task(systemd_watchdog.run())
    pending_notify_task = asyncio.create_task(_pending_notify_loop())
    # 分析ログ: 起動/再起動の判定を先に済ませてから、アップローダとメトリクス採取を回す。
    await device_analytics.on_startup()
    analytics_tasks = [
        asyncio.create_task(device_analytics.uploader_loop()),
        asyncio.create_task(device_analytics.metrics_loop()),
    ]
    # かな漢字辞書: 無ければ取得→事前ロード(別スレッド)。OTA 更新の Pi でも自動で辞書を揃え、
    # 初回変換の遅延も回避する。取得失敗(オフライン)時は同梱 kana_dict.tsv にフォールバック。
    async def _prepare_convert_dict():
        await asyncio.to_thread(kana_kanji.ensure_dict)
        await asyncio.to_thread(kana_kanji.warmup)
    warmup_task = asyncio.create_task(_prepare_convert_dict())
    # 名刺読み取り: OCR モデルの事前ロード（初回の待ち時間を消す）と、
    # 期限切れセッション（＝メモリ上の画像）の定期破棄。
    card_tasks: list[asyncio.Task] = []
    if card_router is not None:
        card_tasks.append(asyncio.create_task(asyncio.to_thread(card_warmup)))
        card_tasks.append(asyncio.create_task(card_purge_loop()))
    elif _CARD_IMPORT_ERROR:
        print(f"[card] disabled: {_CARD_IMPORT_ERROR}")
    await systemd_watchdog.ready("mokuture kiosk agent started")
    yield
    # 分析ログ: 正常停止として記録し、最後に1回だけ送信を試みる（届かなければ次回起動後に再送）。
    await device_analytics.on_shutdown()
    for t in analytics_tasks:
        t.cancel()
    task.cancel()
    update_task.cancel()
    heartbeat_task.cancel()
    watchdog_task.cancel()
    pending_notify_task.cancel()
    warmup_task.cancel()
    for t in card_tasks:
        t.cancel()
    _cancel_all_state_timers()
    locker_ctrl.close()
    pir.close()
    for door in doors.values():
        door.close()


app = FastAPI(title="mokuture+ Kiosk Agent", lifespan=lifespan)


# ── 端末の中からだけ受け付ける ──────────────────────────────────────────────────
# このエージェントの利用者は、同じ端末で動くキオスク画面(Chromium)だけ。ロッカー・Wi-Fi・
# 登録などの操作には認証が無いので、端末の外からの要求は受け付けない(card/api.py の
# _require_local と同じ判定)。保守で別の機器から触る必要があるときだけ、.env に
# KIOSK_ALLOW_REMOTE=1 を書いて明示的に開ける(待ち受けアドレスも合わせて変える必要がある)。
def _remote_allowed() -> bool:
    return os.getenv("KIOSK_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")


def _is_loopback_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)   # ::ffff:127.0.0.1 の表記
    if mapped is not None:
        addr = mapped
    return addr.is_loopback


@app.middleware("http")
async def _local_only(request: Request, call_next):
    if not _remote_allowed() and not _is_loopback_client(request):
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    return await call_next(request)


# CORS はキオスク画面のオリジン(この端末の 8080)だけ。画面は同じオリジンから配信されるので
# 本来は不要だが、localhost と 127.0.0.1 の表記ゆれで別オリジン扱いになっても通るようにする。
# 音声サービス(127.0.0.1:8181)は画面から呼ばれる側で、このエージェントは呼ばない。
_LOCAL_ORIGINS = [f"http://localhost:{settings.port}", f"http://127.0.0.1:{settings.port}"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_LOCAL_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Kiosk-Token"],
)

if card_router is not None:
    app.include_router(card_router)


class ReceptionBody(BaseModel):
    visitor_name: str
    company: str = ""
    purpose: str = ""
    staff: str = ""
    method: str = "form"
    appointment_id: str | None = None
    # ここに無い項目は pydantic が黙って捨てるので、キオスク画面が送り backend が受け取る
    # 項目はすべて宣言する(以前は部署と、通知の成否を書き戻すための匿名セッションIDが
    # backend へ届いていなかった)。
    department: str | None = None
    analytics_session_id: str | None = None


class LockerPinBody(BaseModel):
    pin: str


class CallStaffBody(BaseModel):
    message: str | None = None
    analytics_session_id: str | None = None


class LockerStateBody(BaseModel):
    on: bool


class LockerConfigBody(BaseModel):
    count: int


class KioskHeartbeatBody(BaseModel):
    screen: str = ""
    hidden: bool = False
    focused: bool | None = None
    href: str = ""
    ts: int | None = None
    # ページ読み込みごとに変わるランダムID。ブラウザ起動/リロードの検出に使う（分析ログ）。
    page_id: str | None = None
    # キオスク画面(kiosk.html)の版数ラベル。端末イベント/メトリクスに載せる。
    ui_version: str | None = None
    # 受付アプリの起動完了(boot 完了)。起動ごとに1回だけ true が来る（分析ログの app_started）。
    booted: bool = False


@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse(url="/kiosk.html")


@app.get("/jsqr.min.js", include_in_schema=False)
async def serve_jsqr():
    if not _JSQR_JS.exists():
        raise HTTPException(status_code=404, detail="jsqr.min.js not found")
    return FileResponse(_JSQR_JS, media_type="application/javascript")


@app.get("/kiosk-oplog.js", include_in_schema=False)
@app.get("/analytics.js", include_in_schema=False)  # 旧名。古い kiosk.html のため残す
async def serve_analytics_js():
    """キオスク画面が読み込む行動ログのロガー（ANALYTICS.md §7）。

    画面が読む URL は /kiosk-oplog.js。名前に analytics を入れないのは、Pi の Chromium に
    最初から入っている広告ブロッカー(uBlock Origin Lite)の規則に当たらないようにするため
    （下の /device/oplog と同じ理由）。
    無い端末（OTA 未着など）でも 404 になるだけで、kiosk.html は従来どおり動く
    （ロガーが無ければログを取らないだけ）。"""
    if not _ANALYTICS_JS.exists():
        raise HTTPException(status_code=404, detail="analytics.js not found")
    return FileResponse(_ANALYTICS_JS, media_type="application/javascript")


@app.get("/tap.mp3", include_in_schema=False)
async def serve_tap_mp3():
    # キオスクの全画面タップ音(木琴C6の単音。VSQ plus+のフリー効果音を加工=商用利用可)。kiosk.html が先読みして再生する。
    if not _TAP_MP3.exists():
        raise HTTPException(status_code=404, detail="tap.mp3 not found")
    return FileResponse(_TAP_MP3, media_type="audio/mpeg")


@app.get("/kiosk.html", include_in_schema=False)
async def serve_kiosk_html():
    if not _KIOSK_HTML.exists():
        raise HTTPException(status_code=404, detail="kiosk.html not found")
    return FileResponse(_KIOSK_HTML, media_type="text/html")


@app.get("/device-control", include_in_schema=False)
async def serve_device_control():
    if not _CONTROL_PANEL_HTML.exists():
        raise HTTPException(status_code=404, detail="device-control.html not found")
    return FileResponse(_CONTROL_PANEL_HTML, media_type="text/html")


@app.get("/config")
async def get_config():
    # 注: ブラウザ全スタブ用の "mock" フラグは廃止。ハードは agent 層(_MOCK_DEVICE / gpio.py)
    # で自動モックし、ブラウザは常に実経路を通す。完全オフラインは kiosk.html?mock=1 のみ。
    return {
        "tenant_slug": settings.tenant_slug,
        "remote_api_url": settings.remote_api_url,
        "device_name": get_device_name(),
        "registered": is_registered(),
        # 分析ログ用: バンドル版数(app_version)と、ブラウザ側ロガーの送信間隔。
        "app_version": read_version(),
        "analytics": {
            "flush_sec": analytics_mod.FLUSH_SEC,
            "max_batch": analytics_mod.MAX_BROWSER_BATCH,
        },
    }


@app.post("/register")
async def register_device():
    """端末を自己登録する（PIN 不要）。tenant_slug + ホスト名 + hardware_id を送り、
    承認待ち(pending)の Device を作成してトークンを取得・保存する。

    既にトークンを保持していれば再登録せず、現在の承認状態をリモートから取得して返す
    （ブラウザキャッシュ消去や再起動での重複登録を防ぐ）。"""
    if not settings.tenant_slug:
        raise HTTPException(status_code=400, detail="tenant_slug が未設定です（.env を確認してください）")

    # 既に登録済み: 保存トークンで現在の status を取得して返す（新規行を作らない）
    existing_token = get_device_token()
    if existing_token:
        status, name = await _fetch_remote_status(existing_token)
        if status == _STATUS_UNREACHABLE:
            # バックエンド不達: 既存の承認済み端末を誤って再登録しないよう、ここでは登録せず
            # 503 を返す。呼び出し側(キオスク)は数秒後に再試行する。
            raise HTTPException(status_code=503, detail="承認状態の確認に失敗しました（リモートAPIに接続できません）")
        if status is not None:
            if name:
                save_device_state(existing_token, name)
            return {"status": status, "device_name": name or get_device_name(), "device_token": existing_token}
        # status is None = トークンが無効(401) → 新規登録に進む

    # 手元にトークンがあれば添える。backend は、いまのトークンを添えた再登録にだけ同じトークンを
    # 返し、添えていない再登録には新しいトークンを発行して承認待ちに戻す(ハードウェア ID だけで
    # 既存端末のトークンを渡さないため)。返ってきたトークンは常に保存し直し、status が pending なら
    # キオスク画面が初回登録と同じく承認待ち画面を出す。
    headers = {}
    current_token = get_device_token()
    if current_token:
        headers["X-Kiosk-Token"] = current_token
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/register",
                json={
                    "tenant_slug": settings.tenant_slug,
                    "device_name": get_device_name() or _hostname(),
                    "hardware_id": _hardware_id(),
                },
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")

    data = resp.json()
    save_device_state(data["device_token"], data["device_name"])
    return {
        "status": data.get("status", "pending"),
        "device_name": data["device_name"],
        "device_token": data["device_token"],
    }


@app.post("/device/unregister")
async def device_unregister():
    """端末の紐づけを解除する。保存済みトークン(device_state.json)を削除し、次回 /register で
    TENANT_SLUG による新規登録をやり直せるようにする（別テナントへの付け替え・再登録用）。
    ブラウザ側の localStorage トークン削除はキオスク UI が別途行う。"""
    clear_device_state()
    return {"ok": True}


_STATUS_UNREACHABLE = "__unreachable__"


async def _fetch_remote_status(token: str) -> tuple[str | None, str | None]:
    """(status, device_name) を返す。
    - 承認状態を取得できた場合: (status, name)
    - トークン無効(401): (None, None) — 呼び出し側は再登録に進む
    - 接続失敗/その他エラー: (_STATUS_UNREACHABLE, None) — トークンは破棄しない"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/status",
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                return None, None
            resp.raise_for_status()
            data = resp.json()
            return data.get("status", "active"), data.get("device_name")
        except Exception:
            return _STATUS_UNREACHABLE, None


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "registered": is_registered(),
        "device_name": get_device_name(),
        "media_dir": str(settings.media_dir),
        # env の MOCK_GPIO だけでなく、ライブラリが無くて模擬に落ちた場合も true にする
        "mock_gpio": not gpio_status()["hardware"],
        "gpio": gpio_status(),
        "watchdog": systemd_watchdog.status(),
        "analytics": device_analytics.status(),
    }


@app.post("/device/kiosk-heartbeat")
async def kiosk_heartbeat(body: KioskHeartbeatBody):
    payload = body.model_dump()
    browser_heartbeat_state.record(payload)
    # 分析ログ: ブラウザ起動/リロードの検出（失敗してもハートビートは成立させる）。
    try:
        await device_analytics.on_browser_heartbeat(payload)
    except Exception:
        pass
    return {"ok": True, "watchdog": systemd_watchdog.status()}


class AnalyticsBatchBody(BaseModel):
    events: list[dict] = []


@app.post("/device/oplog")
@app.post("/device/analytics/events")  # 旧名。古い analytics.js のため残す(Pi の Chromium では届かない)
async def device_analytics_events(body: AnalyticsBatchBody):
    """キオスク画面(ブラウザ)からの行動イベントを受け取る中継。

    **ここでディスク(スプール)へ書いてから ack する**ので、ブラウザは accepted に載った
    event_id だけを IndexedDB から消せばよい（ANALYTICS.md §7）。デバイストークンは
    エージェントだけが持ち、ブラウザのコードには渡さない。
    バックエンドへの送信はアップローダが指数バックオフで行う（通信断でも失われない）。

    **ブラウザが叩く名前は /device/oplog**。旧名 /device/analytics/events は、Raspberry Pi OS の
    Chromium に最初から入っている uBlock Origin Lite(EasyPrivacy の `/analytics/event`)に
    当たり、送信がブラウザ内で止められて 1 件も届いていなかった。名前に analytics / track /
    telemetry / beacon / collect などを入れないこと（tests/test_oplog_paths.py が見張る）。
    """
    return await device_analytics.submit_browser_events(body.events)


@app.get("/device/analytics/status")
async def device_analytics_status():
    """未送信件数・オンライン状態などの軽量な状態（秘密情報は含まない）。"""
    return device_analytics.status()


@app.get("/proxy/settings")
async def proxy_settings():
    """テナント設定をリモートAPIから取得して返す。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/settings/public/{settings.tenant_slug}",
                timeout=10,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail="テナント設定の取得に失敗しました")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.get("/proxy/schedule")
async def proxy_schedule(request: Request):
    """スケジュールをリモートAPIから取得して返す。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/schedule",
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.get("/proxy/status")
async def proxy_status(request: Request):
    """承認状態(status)をリモートAPIから取得する。承認待ち画面のポーリング用。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/status",
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/reception")
async def proxy_reception(request: Request, body: ReceptionBody):
    """受付をリモートAPIに送信する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/reception",
                json=body.model_dump(),
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.get("/proxy/reception/{log_id}")
async def proxy_reception_status(log_id: str, request: Request):
    """受付のスタッフ応答結果(state)をリモートAPIから取得する。待機画面のポーリング用。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/reception/{log_id}",
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="受付が見つかりません")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/reception/{log_id}/timeout")
async def proxy_reception_timeout(log_id: str, request: Request):
    """待機時間終了をリモートAPIへ送り、電話案内を先着確定する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/reception/{log_id}/timeout",
                json={},
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="受付が見つかりません")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.get("/proxy/appointment/{token}")
async def proxy_appointment(token: str, request: Request):
    """QR トークンから来社予定を取得する。"""
    kiosk_token = request.headers.get("x-kiosk-token", "")
    if not kiosk_token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/appointment/{token}",
                headers={"X-Kiosk-Token": kiosk_token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="予約が見つかりません")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.get("/proxy/lockers")
async def proxy_list_lockers(request: Request):
    """ロッカー一覧をリモートAPIから取得する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/lockers",
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/lockers/open-all")
async def proxy_open_all_lockers(request: Request):
    """全ロッカー解放をリモートAPIに転送する(緊急/メンテナンス)。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/open-all",
                json={},
                headers={"X-Kiosk-Token": token},
                timeout=15,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/lockers/{locker_id}/occupy")
async def proxy_occupy_locker(locker_id: str, request: Request, body: LockerPinBody):
    """ロッカーをPINで確保する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/{locker_id}/occupy",
                json=body.model_dump(),
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/lockers/{locker_id}/release")
async def proxy_release_locker(locker_id: str, request: Request, body: LockerPinBody):
    """ロッカーをPINで解放する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/{locker_id}/release",
                json=body.model_dump(),
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/lockers/{locker_id}/occupy-delivery")
async def proxy_occupy_locker_delivery(locker_id: str, request: Request):
    """ロッカーを置き配（PINなし）で確保する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/{locker_id}/occupy-delivery",
                json={},
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


@app.post("/proxy/call-staff")
async def proxy_call_staff(request: Request, body: CallStaffBody):
    """配達の呼び出しをリモートAPIに送信する。"""
    token = request.headers.get("x-kiosk-token", "")
    if not token:
        raise HTTPException(status_code=401, detail="X-Kiosk-Token required")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/call-staff",
                json=body.model_dump(),
                headers={"X-Kiosk-Token": token},
                timeout=10,
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid kiosk token")
            resp.raise_for_status()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=_proxy_detail(e.response))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")
    return resp.json()


def _proxy_detail(resp: httpx.Response) -> str:
    """Extract upstream {detail} (e.g. 409 already occupied, 403 invalid pin)."""
    try:
        data = resp.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except Exception:
        pass
    return "リモートAPIエラー"


@app.get("/media/{media_id}")
async def serve_media(media_id: str):
    path = find_media(media_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Media not cached")
    return FileResponse(path)


@app.get("/device/status")
async def device_status():
    door_items = [
        {
            "door_id": door_id,
            "pin": sensor.pin,
            "configured": sensor.configured,
            "is_closed": sensor.is_closed,
        }
        for door_id, sensor in doors.items()
    ]
    camera = await asyncio.to_thread(_camera_status)
    microphone = await asyncio.to_thread(_microphone_status)
    return {
        "registered": is_registered(),
        "device_name": get_device_name(),
        "mock_gpio": not gpio_status()["hardware"],
        "gpio": gpio_status(),
        "platform": platform.platform(),
        "pir": {
            "pin": settings.pir_pin,
            "motion_detected": pir.motion_detected,
            # kind=pir|tof。距離センサーのときは いまの距離・しきい値・読めない理由 も返す
            **(pir.info() if hasattr(pir, "info") else {"kind": "pir"}),
        },
        "door": door_items[0] if door_items else {
            "door_id": "1",
            "pin": settings.door_pin,
            "configured": False,
            "is_closed": None,
        },
        "doors": door_items,
        "camera": camera,
        "microphone": microphone,
        "relays": locker_ctrl.status(),
        "lockers": locker_ctrl.status(),
        "locks_missing": _doors_without_lock(),
    }


@app.get("/device/door")
async def get_door():
    return {"doors": [
        {
            "door_id": door_id,
            "configured": sensor.configured,
            "pin": sensor.pin,
            "is_closed": sensor.is_closed,
        }
        for door_id, sensor in doors.items()
    ]}


@app.get("/device/lockers")
async def list_device_lockers():
    return {"lockers": locker_ctrl.status()}


_DOOR_OPEN_DETAIL = "扉が開いているため、このロッカーは使えません。別のロッカーをお選びください。"


@app.post("/device/locker/{locker_id}/open")
async def open_locker(locker_id: str):
    """扉の錠を開ける(locker_id = 扉番号)。手荷物の預け入れ・置き配で空きの口を開けるときに使う。

    **空きの口で、扉センサーが「開」を示しているときは開けない(409)。** 預け入れや置き配の
    途中で画面が待機に戻ると、扉が開いたまま・未登録のまま「空き」に残る(誰かの荷物が
    入っているかもしれない)。その口を次の人に渡さないため。利用中の口(受け取り)は扉の
    状態にかかわらず開けられる。センサーが無い・読めない(None)ときは従来どおり開ける。"""
    lid = str(locker_id)
    if not locker_ctrl.is_configured(lid):
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    async with _locker_op_lock:
        if not locker_store.door_occupied(lid) and _door_closed(lid) is False:
            raise HTTPException(status_code=409, detail=_DOOR_OPEN_DETAIL)
        # ドアセンサー連動: 解錠→扉が開いたら即施錠位置へ→閉扉で自動施錠(パルス長非依存)。
        # センサー未設定なら従来の固定パルス。
        driven = await _drive_unlock(lid)
    if driven is None:
        raise HTTPException(status_code=503, detail=_LOCK_DRIVE_FAILED)
    return {"locker_id": lid, **driven}


@app.post("/device/locker/{locker_id}/pulse")
async def pulse_locker_default(locker_id: str):
    ok = await locker_ctrl.open(locker_id, pulse_sec=1.0)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {"locker_id": locker_id, "state": "pulsed", "pulse_sec": 1.0}


@app.post("/device/locker/{locker_id}/state")
async def set_locker_state(locker_id: str, body: LockerStateBody):
    """錠の通電を直接 ON/OFF する(デバイスチェックのトグル・キオスクの「扉を閉めました」の施錠)。
    ON は _STATE_ON_MAX_SEC 秒で自動的に OFF へ戻す(押し直すと数え直し、OFF で取り消し)。"""
    lid = str(locker_id)
    ok = locker_ctrl.set_state(lid, body.on)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    if body.on:
        _start_state_timer(lid)
    else:
        _cancel_state_timer(lid)
    return {
        "locker_id": lid,
        "on": locker_ctrl.is_on(lid),
        "auto_off_sec": _STATE_ON_MAX_SEC if body.on else None,
    }


# ── ローカルファースト・ロッカー状態（台帳・占有・PINすべて端末が権威／解錠はオフライン可） ──
# 台帳(何口あるか)は端末のドア構成から生成し(_configured_door_numbers)、状態系
# (list/occupy/occupy-delivery/release/open-all)もここ(agent)で完結する。backend へは
# best-effort でミラー＋置き配通知の中継のみ行い、台帳を backend へ問い合わせない。
# GPIO 開閉は従来どおり kiosk が /device/locker/{door}/open・/state を叩く。関連: locker_store.py


async def _mirror_locker_state() -> None:
    """管理画面可視化用に occupied/has_pin を backend へ best-effort ミラー（PINは送らない）。"""
    token = get_device_token()
    if not token:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/mirror",
                headers={"X-Kiosk-Token": token},
                json=locker_store.mirror_payload(), timeout=8,
            )
    except Exception:
        pass  # ミラーは best-effort（失敗しても解錠フローに影響なし）


async def _relay_delivery_notify(item: dict) -> bool:
    """置き配通知を backend 経由で発火（平文PIN＋ラベル）。item={id,pin,label,device}。"""
    token = get_device_token()
    if not token:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/lockers/{item['id']}/notify-delivery",
                headers={"X-Kiosk-Token": token},
                json={
                    "pin": item.get("pin"),
                    "locker_label": item.get("label"),
                    "device_name": item.get("device"),
                },
                timeout=10,
            )
            return resp.status_code < 400
    except Exception:
        return False


_flush_notify_lock = asyncio.Lock()


async def _flush_pending_notify() -> None:
    """オフライン中に貯めた置き配通知を再送する。

    保留は**送れたと確かめてから 1 件ずつ外す**。先に取り出して空にすると、送信の途中で
    エージェントが止まったとき(更新の適用は os._exit で即終了する・電源断)に失う。
    暗証番号の平文はこの保留にしか無いので、失うと担当者には二度と届かない。
    止まり方によっては同じ通知がもう一度届くことはあるが、届かないよりよい。"""
    if _flush_notify_lock.locked():
        return   # 別の再送が進行中(定期の再送とロッカー一覧からの再送が重なったとき)
    async with _flush_notify_lock:
        for item in locker_store.peek_pending_notify():
            if await _relay_delivery_notify(item):
                locker_store.remove_pending_notify(item)


_PENDING_NOTIFY_INTERVAL_SEC = 60


async def _pending_notify_loop() -> None:
    """保留中の置き配通知を、通信が戻りしだい送る。

    以前はロッカー一覧(GET /device/locker-list)を開いたときにしか再送していなかったので、
    通信断のあいだに置き配があると、次に誰かがロッカー画面を開くまで担当者へ暗証番号が
    届かなかった。
    """
    while True:
        await asyncio.sleep(_PENDING_NOTIFY_INTERVAL_SEC)
        try:
            await _flush_pending_notify()
        except Exception as e:
            print(f"[locker] pending notify flush failed: {e}")


@app.get("/device/locker-list")
async def device_locker_list():
    """kiosk グリッド用: 端末のドア構成から台帳を生成し、ローカル状態を返す。
    保留中の置き配通知の再送も試みるが、**結果は待たない**(通信断のとき、保留1件ごとに
    最大10秒この一覧が返らなくなるため)。完全オフラインでも成立（backend 非依存）。"""
    locker_store.ensure_local_roster(_configured_door_numbers())
    _spawn(_flush_pending_notify())
    snap = locker_store.snapshot()
    # 扉センサーの読み(True=閉 / False=開 / None=分からない)。空きで False の口は、画面が
    # 選べなくする(/device/locker/{id}/open も 409 で断る)。None は従来どおり選べる。
    for item in snap.get("lockers", []):
        item["door_closed"] = _door_closed(item.get("door_number"))
    return snap


@app.get("/device/locker-config")
async def get_locker_config():
    """設置者が選んだロッカーの口数と、選べる口数の候補を返す（キオスク設定画面のタッチUI用）。"""
    return {
        "count": _current_locker_count(),
        "options": [{"count": c} for c in LOCKER_COUNTS],
        # 設置者がこの画面で口数を選んだか。false のあいだは count は推定値(既定3口)。
        "chosen": locker_store.get_locker_count() in LOCKER_COUNTS,
        "locks_missing": _doors_without_lock(),
    }


@app.post("/device/locker-config")
async def set_locker_config(body: LockerConfigBody):
    """口数を切り替える（3口↔7口）。GPIO を組み直し台帳を再生成、backend へ best-effort ミラー。
    増設時に設置者がタッチで選ぶための経路。占有中のロッカーは縮小時も台帳に残す（中身を失わない）。"""
    if body.count not in LOCKER_COUNTS:
        raise HTTPException(status_code=422, detail=f"count must be one of {LOCKER_COUNTS}")
    # 縮小で台帳から外れる口に利用中があれば拒否。台帳には残せても GPIO を落とすと解錠できず
    # 中身が取り出せなくなる（物理的にも占有中の増設部は外せない）。先に解錠させる。
    wanted = set(range(1, body.count + 1))
    occupied_out = sorted(
        it.get("door_number")
        for it in locker_store.snapshot().get("lockers", [])
        if it.get("occupied") and it.get("door_number") not in wanted
    )
    if occupied_out:
        labels = "・".join(str(d) for d in occupied_out)
        raise HTTPException(
            status_code=409,
            detail=f"利用中のロッカー（{labels}番）があります。先に解錠してから口数を変更してください。",
        )
    locker_store.set_locker_count(body.count)
    _apply_locker_count(body.count)
    locker_store.ensure_local_roster(_configured_door_numbers())
    _spawn(_mirror_locker_state())
    return await get_locker_config()


@app.post("/device/locker/{locker_id}/occupy")
async def device_locker_occupy(locker_id: str, body: LockerPinBody):
    """手荷物一時保管: 端末ローカルに PIN(ハッシュ)を保存して施錠状態にする。"""
    if not re.fullmatch(r"\d{4}", body.pin or ""):
        raise HTTPException(status_code=422, detail="pin must be exactly 4 digits")
    try:
        async with _locker_op_lock:
            # pbkdf2 は重い(数十〜百ms)ので、イベントループの外で計算する。
            result = await asyncio.to_thread(locker_store.occupy, locker_id, body.pin, "store")
    except locker_store.LockerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    _spawn(_mirror_locker_state())
    return result


@app.post("/device/locker/{locker_id}/occupy-delivery")
async def device_locker_occupy_delivery(locker_id: str):
    """置き配: ローカルでランダム4桁PINを生成・保存し、通知は backend 経由で発火する
    （平文PINは通知にのみ使用）。オフライン時は通知をキューして再接続時に送る。"""
    try:
        async with _locker_op_lock:
            result = await asyncio.to_thread(locker_store.occupy_delivery, locker_id)
    except locker_store.LockerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    item = {"id": str(locker_id), "pin": result["pin"], "label": result["name"], "device": get_device_name()}

    async def _notify():
        if not await _relay_delivery_notify(item):
            locker_store.enqueue_notify(item)
        await _mirror_locker_state()

    _spawn(_notify())
    return {"ok": True, "door_number": result["door_number"]}


@app.post("/device/locker/{locker_id}/release")
async def device_locker_release(locker_id: str, body: LockerPinBody):
    """受け取り: 端末ローカルで PIN 照合 → 錠を動かす → 動いたときだけ空きに戻す
    （クラウド往復なし・オフライン可）。

    以前は照合と同時に空きへ戻し、錠は画面が別に開けていた。錠が動かなかった(GPIO が
    模擬に落ちている等)ときも画面は「解錠しました」と出し、お荷物は「空き」のロッカーに
    閉じ込められた。いまは錠を動かせなければ 503 を返し、利用中のまま残す。
    応答の unlocked=true は「錠もここで動かした」印(古いエージェントには無いので、画面は
    これが無いときだけ自分で /open を叩く)。

    暗証番号は口ごとに続けて _PIN_MAX_FAILS 回違えると _PIN_LOCKOUT_SEC 秒受け付けない(429)。"""
    lid = str(locker_id)
    async with _locker_op_lock:
        if _pin_locked_remaining(lid) > 0:
            raise HTTPException(status_code=429, detail=_PIN_LOCKED_DETAIL)
        try:
            # pbkdf2 は重い(数十〜百ms)ので、イベントループの外で照合する。
            found = await asyncio.to_thread(locker_store.verify_pin, lid, body.pin)
        except locker_store.LockerError as e:
            if e.status == 403 and _pin_record_failure(lid):
                raise HTTPException(status_code=429, detail=_PIN_LOCKED_DETAIL)
            raise HTTPException(status_code=e.status, detail=e.detail)
        _pin_failures.pop(lid, None)   # 合ったら数え直し
        door = found.get("door_number")
        driven = await _drive_unlock(str(door)) if door is not None else None
        if driven is None:
            raise HTTPException(status_code=503, detail=_LOCK_DRIVE_FAILED)
        try:
            result = locker_store.clear(lid)
        except locker_store.LockerError as e:
            raise HTTPException(status_code=e.status, detail=e.detail)
    _spawn(_mirror_locker_state())
    return {**result, "unlocked": True, "autolock": driven.get("autolock", False)}


@app.post("/device/lockers/open-all")
async def device_lockers_open_all():
    """全ロッカーのローカル状態をリセットし、全部の錠を開ける（緊急・メンテ用）。

    扉センサーの状態にかかわらず開ける(扉が少し開いたまま利用中の口も取り出せるように)。
    錠はここで動かす(driven=true)。古いエージェントには driven が無く、画面が 1 口ずつ
    /open を叩く。動かせなかった扉は failed に入れて返す。
    実機で GPIO が模擬に落ちているときは錠を 1 つも動かせない。それでも**記録は消す**
    (全部の扉を failed で返す)。ここまで断ると、その端末では利用中の口を暗証番号でも
    スタッフの操作でも空きに戻せなくなる。扉は鍵で開けてもらう。"""
    mocked = _gpio_unintended_mock()
    async with _locker_op_lock:
        result = locker_store.release_all()
        failed: list = []
        for dn in result.get("door_numbers", []):
            if mocked or await _drive_unlock(str(dn)) is None:
                failed.append(dn)
    _spawn(_mirror_locker_state())
    return {**result, "driven": True, "failed": failed}


@app.get("/device/pir")
async def get_pir():
    return {"motion_detected": pir.motion_detected}


# ── かな漢字変換 (実験: experiment/kanji-ime) ─────────────────────────────────
# 受付フォームの五十音キーボードで入力した読み(ひらがな)を漢字候補に変換する。
# ローカル辞書ベースでオフライン動作(ハードウェア不要 = 開発機でも同じ経路)。
@app.get("/device/convert")
async def device_convert(kana: str = "", limit: int = 60):
    limit = max(1, min(limit, 100))
    candidates = await asyncio.to_thread(kana_kanji.convert, kana, limit)
    return {"reading": kana, "candidates": candidates}


@app.get("/update-status")
async def update_status():
    # ready/force/version は待機画面の自動適用が使う。残りはデバイスチェック画面の
    # 「ソフトウェア更新」用(この端末の版・配信中の版・最後の確認・適用待ち)。
    return {"ready": updater.is_ready(), "force": updater.is_force(), "version": read_version(),
            **updater.status()}


@app.post("/update-check")
async def update_check():
    """今すぐ配信サーバーと突き合わせる(デバイスチェック画面の「今すぐ確認」)。
    自動更新が有効な端末では、違うファイルの取り寄せまで済ませてから返す。"""
    await updater.check()
    return await update_status()


@app.post("/apply-update")
async def apply_update():
    needs_restart = await updater.apply()
    if needs_restart:
        asyncio.create_task(_do_restart())
    return {"ok": True, "restart": needs_restart}


async def _do_restart():
    await asyncio.sleep(1.5)
    os._exit(0)


# ── device settings API ───────────────────────────────────────────────────────

class VolumeBody(BaseModel):
    level: int


@app.get("/device/volume")
async def device_get_volume():
    if _MOCK_DEVICE:
        level = int(os.environ.get("_MOCK_VOL", "70"))
        return {"level": level, "mock": True}
    level, err = await asyncio.to_thread(_get_volume_linux)
    return {"level": level, "error": err}


@app.post("/device/volume")
async def device_set_volume(body: VolumeBody):
    level = max(0, min(100, body.level))
    if _MOCK_DEVICE:
        os.environ["_MOCK_VOL"] = str(level)
        return {"level": level, "mock": True}
    err = await asyncio.to_thread(_set_volume_linux, level)
    if err:
        raise HTTPException(status_code=500, detail=err)
    return {"level": level}


@app.get("/device/wifi/networks")
async def device_wifi_networks():
    if _MOCK_DEVICE:
        return {"networks": [
            {"ssid": "mokuture-5G",   "signal": 82, "level": 4, "lock": True,  "connected": True,  "known": True},
            {"ssid": "mokuture-2G",   "signal": 75, "level": 4, "lock": True,  "connected": False, "known": True},
            {"ssid": "GUEST-FREE",    "signal": 60, "level": 3, "lock": False, "connected": False, "known": False},
            {"ssid": "TP-LINK_8841",  "signal": 30, "level": 2, "lock": True,  "connected": False, "known": False},
        ], "mock": True}
    nets, err = await asyncio.to_thread(_wifi_networks)
    return {"networks": nets, "error": err, "debug": _wifi_last_debug}


class WifiConnectBody(BaseModel):
    ssid: str
    password: str = ""


@app.post("/device/wifi/connect")
async def device_wifi_connect(body: WifiConnectBody):
    if _MOCK_DEVICE:
        return {"ok": True, "ssid": body.ssid, "mock": True}
    ok, err = await asyncio.to_thread(_wifi_connect, body.ssid, body.password)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "接続に失敗しました")
    return {"ok": True, "ssid": body.ssid}


class WifiToggleBody(BaseModel):
    on: bool


@app.post("/device/wifi/toggle")
async def device_wifi_toggle(body: WifiToggleBody):
    if _MOCK_DEVICE:
        return {"ok": True, "on": body.on, "mock": True}
    err = await asyncio.to_thread(_wifi_toggle, body.on)
    if err:
        raise HTTPException(status_code=500, detail=err)
    return {"ok": True, "on": body.on}


if __name__ == "__main__":
    import uvicorn
    # 端末の中(キオスク画面)からだけ使う。外から触る必要があるときは KIOSK_ALLOW_REMOTE を参照。
    uvicorn.run("main:app", host="127.0.0.1", port=settings.port, reload=False)
