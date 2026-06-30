"""mokuture+ Local Kiosk Device Agent"""
import asyncio
import os
import platform
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from config import settings
from gpio import DoorSensor, LockerController, PirSensor
from state import get_device_name, get_device_token, is_registered, save_device_state
from sync import find_media, heartbeat_loop, sync_loop
from updater import updater, read_version

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

_KIOSK_HTML = Path(__file__).parent / "static" / "kiosk.html"
_JSQR_JS   = Path(__file__).parent / "static" / "jsqr.min.js"
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


class PinRequest(BaseModel):
    pin_code: str


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
    return {
        "tenant_slug": settings.tenant_slug,
        "remote_api_url": settings.remote_api_url,
        "device_name": get_device_name(),
        "registered": is_registered(),
        "mock": settings.kiosk_mock,
    }


@app.post("/setup")
async def setup_device(body: PinRequest):
    """管理画面で発行した PIN を使ってデバイスを登録する。毎回リモートAPIで検証する。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.remote_api_url}/kiosk/verify-pin",
                json={"pin_code": body.pin_code},
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail="PIN が無効または期限切れです")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"リモートAPIに接続できません: {e}")

    data = resp.json()
    save_device_state(data["device_token"], data["device_name"])
    return {
        "status": "registered",
        "device_name": data["device_name"],
        "device_token": data["device_token"],
    }


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
    ok = await locker_ctrl.open(locker_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {"locker_id": locker_id, "state": "opened"}


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
