"""GPIO helpers for relay, PIR, and door sensors."""
import asyncio
import os

_MOCK = os.getenv("MOCK_GPIO", "false").lower() == "true"

if not _MOCK:
    try:
        from gpiozero import Button as _BUTTON, LED as _LED, MotionSensor as _PIR  # type: ignore
        _HW = True
    except ImportError:
        _HW = False
        _MOCK = True
else:
    _HW = False


class LockerController:
    def __init__(self, pin_map: dict[str, int], default_pulse_sec: float = 1.0):
        self._pin_map = {str(locker_id): pin for locker_id, pin in pin_map.items()}
        self._default_pulse_sec = max(0.0, float(default_pulse_sec))
        self._pins: dict[str, object] = {}
        self._mock_state: dict[str, bool] = {locker_id: False for locker_id in self._pin_map}
        if _HW:
            for locker_id, pin in self._pin_map.items():
                self._pins[locker_id] = _LED(pin)

    def configured_lockers(self) -> list[dict[str, int]]:
        return [
            {"locker_id": locker_id, "pin": pin}
            for locker_id, pin in sorted(self._pin_map.items(), key=lambda item: item[0])
        ]

    def status(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for locker in self.configured_lockers():
            locker_id = locker["locker_id"]
            items.append(
                {
                    **locker,
                    "on": self.is_on(locker_id),
                }
            )
        return items

    def is_on(self, locker_id: str) -> bool:
        lid = str(locker_id)
        if _MOCK:
            return self._mock_state.get(lid, False)
        relay = self._pins.get(lid)
        if relay is None:
            return False
        return bool(relay.value)  # type: ignore[attr-defined]

    def set_state(self, locker_id: str, on: bool) -> bool:
        lid = str(locker_id)
        if lid not in self._pin_map:
            return False
        if _MOCK:
            self._mock_state[lid] = on
            print(f"[MOCK GPIO] locker {lid} set {'on' if on else 'off'}")
            return True
        relay = self._pins.get(lid)
        if relay is None:
            return False
        if on:
            relay.on()  # type: ignore[attr-defined]
        else:
            relay.off()  # type: ignore[attr-defined]
        return True

    async def open(self, locker_id: str, pulse_sec: float | None = None) -> bool:
        lid = str(locker_id)
        if not self.set_state(lid, True):
            return False
        wait_sec = self._default_pulse_sec if pulse_sec is None else max(0.0, float(pulse_sec))
        await asyncio.sleep(wait_sec)
        self.set_state(lid, False)
        return True

    def close(self) -> None:
        if _HW:
            for pin in self._pins.values():
                pin.close()  # type: ignore[attr-defined]


class PirSensor:
    def __init__(self, pin: int):
        self.pin = pin
        self._pir = _PIR(pin) if _HW else None  # type: ignore

    @property
    def motion_detected(self) -> bool:
        if self._pir is None:
            return False
        return bool(self._pir.motion_detected)  # type: ignore[attr-defined]

    def close(self) -> None:
        if self._pir is not None:
            self._pir.close()  # type: ignore[attr-defined]


class DoorSensor:
    def __init__(self, pin: int | None):
        self.pin = pin
        self._door = _BUTTON(pin, pull_up=True) if _HW and pin is not None else None  # type: ignore

    @property
    def configured(self) -> bool:
        return self.pin is not None

    @property
    def is_closed(self) -> bool | None:
        if self.pin is None:
            return None
        if self._door is None:
            return False
        return bool(self._door.is_pressed)  # type: ignore[attr-defined]

    def close(self) -> None:
        if self._door is not None:
            self._door.close()  # type: ignore[attr-defined]
