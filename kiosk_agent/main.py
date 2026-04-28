"""mokuture+ Local Kiosk Device Agent

Responsibilities:
  - Serve downloaded media files from ~/kiosk-media/
  - Serve the bundled Next.js static build (kiosk_agent/static/)
  - Control GPIO: locker relay, PIR motion sensor
  - Run background content-sync against the remote API
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from gpio import LockerController, PirSensor
from sync import find_media, sync_loop

locker_ctrl = LockerController(settings.locker_pins)
pir = PirSensor(settings.pir_pin)


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "token_set": bool(settings.device_token),
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
