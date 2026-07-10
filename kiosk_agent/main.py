"""mokuture+ Local Kiosk Device Agent"""
import asyncio
import os
import platform
import re
import socket
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

import locker_store
from config import settings
from gpio import DoorSensor, LockerController, PirSensor
from state import get_device_name, get_device_token, is_registered, save_device_state
from sync import find_media, heartbeat_loop, sync_loop
from updater import updater, read_version


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


def _parse_nmcli_multiline(output: str) -> list[dict]:
    """nmcli --mode multiline 出力をパース (SSIDに:が含まれても安全)。"""
    nets: list[dict] = []
    seen: set[str] = set()
    for block in re.split(r'\n{2,}', output.strip()):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, sep, val = line.partition(':')
            if sep:
                fields[key.strip()] = val.strip()
        ssid = fields.get("SSID", "").strip()
        if not ssid or ssid == "--" or ssid in seen:
            continue
        seen.add(ssid)
        in_use  = fields.get("IN-USE", "").strip() == "*"
        sig_str = fields.get("SIGNAL", "0").strip()
        sig     = int(sig_str) if sig_str.isdigit() else 0
        security = fields.get("SECURITY", "--").strip()
        level   = 4 if sig >= 75 else 3 if sig >= 50 else 2 if sig >= 25 else 1
        nets.append({
            "ssid": ssid,
            "signal": sig,
            "level": level,
            "lock": bool(security and security not in ("--", "")),
            "connected": in_use,
        })
    nets.sort(key=lambda n: (not n["connected"], -n["signal"]))
    return nets


def _wifi_networks() -> tuple[list[dict], str | None]:
    """(ネットワーク一覧, エラー文字列|None) を返す。"""
    try:
        r = _run(
            ["nmcli", "--mode", "multiline", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
             "dev", "wifi", "list"],
            timeout=12,
        )
        if r.returncode != 0:
            return [], f"nmcli エラー: {r.stderr.strip()}"
        nets = _parse_nmcli_multiline(r.stdout)
        return nets, None
    except FileNotFoundError:
        return [], "nmcli が見つかりません (NetworkManager がインストールされていますか?)"
    except subprocess.TimeoutExpired:
        return [], "nmcli タイムアウト"
    except Exception as e:
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


locker_ctrl = LockerController(
    settings.locker_pins,
    default_pulse_sec=settings.locker_pulse_sec,
)
pir = PirSensor(settings.pir_pin)
doors = {
    door_id: DoorSensor(pin)
    for door_id, pin in sorted(settings.door_pins.items(), key=lambda item: item[0])
}

# ── ドアセンサー連動の自動施錠 ──────────────────────────────────────────────────
# 電気ストライク(通電ON=解錠 / 無通電OFF=施錠位置)向け。解錠通電後、扉が開いたら即無通電に
# 戻す。以後は閉扉でラッチ(ツノ)が自動施錠されるため、開錠パルス長や「扉を閉めました」操作の
# タイミングに依存せず確実に施錠できる。ドアセンサーが無いロッカーは従来の固定パルスにフォール
# バックする。※有効化には DOOR_PINS_JSON のキーを door_number(=LOCKER_PINS_JSON のキー)と
# 一致させること。
_OPEN_WINDOW_SEC = float(os.getenv("LOCKER_OPEN_WINDOW_SEC", "12"))
_bg_tasks: set = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def _open_with_autolock(locker_id: str, door: DoorSensor) -> None:
    locker_ctrl.set_state(locker_id, True)   # 解錠(通電)
    waited = 0.0
    try:
        while waited < _OPEN_WINDOW_SEC:
            if door.configured and door.is_closed is False:   # 扉が開いた → 施錠位置へ戻す
                break
            await asyncio.sleep(0.15)
            waited += 0.15
    finally:
        locker_ctrl.set_state(locker_id, False)  # 無通電=施錠位置(閉扉で自動施錠)


_KIOSK_HTML = Path(__file__).parent / "static" / "kiosk.html"
_JSQR_JS   = Path(__file__).parent / "static" / "jsqr.min.js"
_TAP_MP3   = Path(__file__).parent / "static" / "tap.mp3"
_CONTROL_PANEL_HTML = Path(__file__).parent / "static" / "device-control.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(sync_loop())
    update_task = asyncio.create_task(updater.run())
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    update_task.cancel()
    heartbeat_task.cancel()
    locker_ctrl.close()
    pir.close()
    for door in doors.values():
        door.close()


app = FastAPI(title="mokuture+ Kiosk Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReceptionBody(BaseModel):
    visitor_name: str
    company: str = ""
    purpose: str = ""
    staff: str = ""
    method: str = "form"
    appointment_id: str | None = None


class LockerPinBody(BaseModel):
    pin: str


class CallStaffBody(BaseModel):
    message: str | None = None


class LockerStateBody(BaseModel):
    on: bool


@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse(url="/kiosk.html")


@app.get("/jsqr.min.js", include_in_schema=False)
async def serve_jsqr():
    if not _JSQR_JS.exists():
        raise HTTPException(status_code=404, detail="jsqr.min.js not found")
    return FileResponse(_JSQR_JS, media_type="application/javascript")


@app.get("/tap.mp3", include_in_schema=False)
async def serve_tap_mp3():
    # キオスクの全画面タップ音(Business22-3 を参考に additive 合成した明るいチャイム)。kiosk.html が先読みして再生する。
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
        # status is None = トークンが無効(401) → 保存状態を破棄して新規登録に進む

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/register",
                json={
                    "tenant_slug": settings.tenant_slug,
                    "device_name": get_device_name() or _hostname(),
                    "hardware_id": _hardware_id(),
                },
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
        "mock_gpio": settings.mock_gpio,
    }


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
        "mock_gpio": settings.mock_gpio,
        "platform": platform.platform(),
        "pir": {
            "pin": settings.pir_pin,
            "motion_detected": pir.motion_detected,
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


@app.post("/device/locker/{locker_id}/open")
async def open_locker(locker_id: str):
    lid = str(locker_id)
    if not locker_ctrl.is_configured(lid):
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    door = doors.get(lid)
    if door is not None and door.configured:
        # ドアセンサー連動: 解錠→扉が開いたら即施錠位置へ→閉扉で自動施錠(パルス長非依存)
        _spawn(_open_with_autolock(lid, door))
        return {"locker_id": lid, "state": "opening", "autolock": True}
    # フォールバック: ドアセンサー未設定なら従来の固定パルス
    ok = await locker_ctrl.open(lid)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {"locker_id": lid, "state": "opened", "autolock": False}


@app.post("/device/locker/{locker_id}/pulse")
async def pulse_locker_default(locker_id: str):
    ok = await locker_ctrl.open(locker_id, pulse_sec=1.0)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {"locker_id": locker_id, "state": "pulsed", "pulse_sec": 1.0}


@app.post("/device/locker/{locker_id}/state")
async def set_locker_state(locker_id: str, body: LockerStateBody):
    ok = locker_ctrl.set_state(locker_id, body.on)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {
        "locker_id": str(locker_id),
        "on": locker_ctrl.is_on(locker_id),
    }


# ── ローカルファースト・ロッカー状態（占有/PINは端末が権威／解錠はオフライン可） ──────
# 状態系(list/occupy/occupy-delivery/release/open-all)はここ(agent)で完結し、backend へは
# best-effort でミラー＋置き配通知の中継のみ行う。GPIO 開閉は従来どおり kiosk が
# /device/locker/{door}/open・/state を叩く（この層は状態のみ扱う）。関連: locker_store.py

_ROSTER_TTL_SEC = 60


async def _sync_locker_roster() -> None:
    """台帳(id→name/door_number)を backend から best-effort 同期。占有/PIN は触らない。"""
    token = get_device_token()
    if not token:
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.remote_api_url}/kiosk/lockers",
                headers={"X-Kiosk-Token": token}, timeout=8,
            )
            resp.raise_for_status()
            locker_store.sync_roster(resp.json().get("lockers", []))
    except Exception:
        pass  # オフライン等: 前回の台帳をそのまま使う


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


async def _flush_pending_notify() -> None:
    """オフライン中に貯めた置き配通知を再送する。"""
    pending = locker_store.take_pending_notify()
    if not pending:
        return
    failed = [item for item in pending if not await _relay_delivery_notify(item)]
    if failed:
        locker_store.requeue_notify(failed)


@app.get("/device/locker-list")
async def device_locker_list():
    """kiosk グリッド用: 台帳＋ローカル状態。オンライン時のみ台帳を throttle 同期し、
    保留中の置き配通知も flush する。オフラインでも前回台帳＋ローカル状態を返す。"""
    age = locker_store.roster_age_sec()
    if age is None or age > _ROSTER_TTL_SEC:
        await _sync_locker_roster()
    await _flush_pending_notify()
    return locker_store.snapshot()


@app.post("/device/locker/{locker_id}/occupy")
async def device_locker_occupy(locker_id: str, body: LockerPinBody):
    """手荷物一時保管: 端末ローカルに PIN(ハッシュ)を保存して施錠状態にする。"""
    if not re.fullmatch(r"\d{4}", body.pin or ""):
        raise HTTPException(status_code=422, detail="pin must be exactly 4 digits")
    try:
        result = locker_store.occupy(locker_id, body.pin, kind="store")
    except locker_store.LockerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    _spawn(_mirror_locker_state())
    return result


@app.post("/device/locker/{locker_id}/occupy-delivery")
async def device_locker_occupy_delivery(locker_id: str):
    """置き配: ローカルでランダム4桁PINを生成・保存し、通知は backend 経由で発火する
    （平文PINは通知にのみ使用）。オフライン時は通知をキューして再接続時に送る。"""
    try:
        result = locker_store.occupy_delivery(locker_id)
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
    """受け取り: 端末ローカルで PIN 照合して解錠状態にする（クラウド往復なし・オフライン可）。"""
    try:
        result = locker_store.release(locker_id, body.pin)
    except locker_store.LockerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    _spawn(_mirror_locker_state())
    return result


@app.post("/device/lockers/open-all")
async def device_lockers_open_all():
    """全ロッカーのローカル状態をリセット（緊急・メンテ用）。GPIO 解錠は kiosk が実施。"""
    result = locker_store.release_all()
    _spawn(_mirror_locker_state())
    return result


@app.get("/device/pir")
async def get_pir():
    return {"motion_detected": pir.motion_detected}


@app.get("/update-status")
async def update_status():
    return {"ready": updater.is_ready(), "force": updater.is_force(), "version": read_version()}


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
            {"ssid": "mokuture-5G",   "signal": 82, "level": 4, "lock": True,  "connected": True},
            {"ssid": "mokuture-2G",   "signal": 75, "level": 4, "lock": True,  "connected": False},
            {"ssid": "GUEST-FREE",    "signal": 60, "level": 3, "lock": False, "connected": False},
            {"ssid": "TP-LINK_8841",  "signal": 30, "level": 2, "lock": True,  "connected": False},
        ], "mock": True}
    nets, err = await asyncio.to_thread(_wifi_networks)
    return {"networks": nets, "error": err}


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
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
