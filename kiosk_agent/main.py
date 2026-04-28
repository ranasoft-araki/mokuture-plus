"""mokuture+ Local Kiosk Device Agent

Responsibilities:
  - Serve downloaded media files from ~/kiosk-media/
  - Serve the bundled Next.js static build (kiosk_agent/static/)
  - Control GPIO: locker relay, PIR motion sensor
  - Run background content-sync against the remote API
"""
import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from gpio import LockerController, PirSensor
from state import get_device_name, get_device_token, is_registered, save_device_state
from sync import find_media, sync_loop

locker_ctrl = LockerController(settings.locker_pins)
pir = PirSensor(settings.pir_pin)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(sync_loop())
    yield
    task.cancel()
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


@app.post("/setup")
async def setup_device(body: PinRequest):
    """管理画面で発行した PIN を使ってデバイスを登録する（一度だけ実行）。"""
    if is_registered():
        return {"status": "already_registered", "device_name": get_device_name()}
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
    return {"status": "registered", "device_name": data["device_name"]}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "registered": is_registered(),
        "device_name": get_device_name(),
        "media_dir": str(settings.media_dir),
        "mock_gpio": settings.mock_gpio,
    }


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


# Mount Next.js static build last (catches all remaining paths)
if settings.static_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
