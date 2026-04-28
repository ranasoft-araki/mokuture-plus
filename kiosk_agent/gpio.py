"""GPIO controller for locker relay and PIR motion sensor.

Set MOCK_GPIO=true to run without physical hardware (development / non-RPi).
"""
import asyncio
import os

_MOCK = os.getenv("MOCK_GPIO", "false").lower() == "true"

if not _MOCK:
    try:
        from gpiozero import LED as _LED, MotionSensor as _PIR  # type: ignore
        _HW = True
    except ImportError:
        _HW = False
        _MOCK = True
else:
    _HW = False


class LockerController:
    def __init__(self, pin_map: dict[str, int]):
        self._pins: dict[str, object] = {}
        if _HW:
            for locker_id, pin in pin_map.items():
                self._pins[str(locker_id)] = _LED(pin)

    async def open(self, locker_id: str, pulse_sec: float = 1.0) -> bool:
        lid = str(locker_id)
        if _MOCK:
            print(f"[MOCK GPIO] locker {lid} open pulse {pulse_sec}s")
            return True
        relay = self._pins.get(lid)
        if relay is None:
            return False
        relay.on()  # type: ignore
        await asyncio.sleep(pulse_sec)
        relay.off()  # type: ignore
        return True

    def close(self) -> None:
        if _HW:
            for pin in self._pins.values():
                pin.close()  # type: ignore


class PirSensor:
    def __init__(self, pin: int):
        self._pir = _PIR(pin) if _HW else None  # type: ignore

    @property
    def motion_detected(self) -> bool:
        if self._pir is None:
            return False
        return bool(self._pir.motion_detected)  # type: ignore

    def close(self) -> None:
        if self._pir is not None:
            self._pir.close()  # type: ignore
