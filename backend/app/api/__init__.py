from fastapi import APIRouter
from app.api import appointments, auth, content, reception, lockers, notifications, kiosk, devices, push, settings, operator, reseller, users, rooms

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(content.router)
api_router.include_router(reception.router)
api_router.include_router(lockers.router)
api_router.include_router(notifications.router)
api_router.include_router(push.router)
api_router.include_router(kiosk.router)
api_router.include_router(devices.router)
api_router.include_router(settings.router)
api_router.include_router(operator.router)
api_router.include_router(reseller.router)
api_router.include_router(users.router)
api_router.include_router(appointments.router)
api_router.include_router(rooms.router)
