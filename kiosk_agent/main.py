"""mokuture+ Local Kiosk Device Agent"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings
from gpio import LockerController, PirSensor
from state import get_device_name, get_device_token, is_registered, save_device_state
from sync import find_media, sync_loop
from updater import updater, read_version

locker_ctrl = LockerController(settings.locker_pins)
pir = PirSensor(settings.pir_pin)

_KIOSK_HTML = Path(__file__).parent / "static" / "kiosk.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(sync_loop())
    update_task = asyncio.create_task(updater.run())
    yield
    task.cancel()
    update_task.cancel()
    locker_ctrl.close()
    pir.close()


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


@app.get("/kiosk.html", include_in_schema=False)
async def serve_kiosk_html():
    if not _KIOSK_HTML.exists():
        raise HTTPException(status_code=404, detail="kiosk.html not found")
    return FileResponse(_KIOSK_HTML, media_type="text/html")


@app.get("/config")
async def get_config():
    return {
        "tenant_slug": settings.tenant_slug,
        "remote_api_url": settings.remote_api_url,
        "device_name": get_device_name(),
        "registered": is_registered(),
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


@app.get("/media/{media_id}")
async def serve_media(media_id: str):
    path = find_media(media_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Media not cached")
    return FileResponse(path)


@app.post("/device/locker/{locker_id}/open")
async def open_locker(locker_id: str):
    ok = await locker_ctrl.open(locker_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Locker {locker_id} not configured")
    return {"locker_id": locker_id, "state": "opened"}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
