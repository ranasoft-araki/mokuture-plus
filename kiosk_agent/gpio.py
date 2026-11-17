"""GPIO helpers for relay, PIR, and door sensors."""
import asyncio
import os
import threading
import time

_MOCK = os.getenv("MOCK_GPIO", "false").lower() == "true"
# 模擬になった理由。None=実機の GPIO を使っている。デバイスチェック画面に出す
# (ライブラリが入らず黙って模擬に落ちると、画面ではドア・電子錠が動かない原因が分からない)。
_MOCK_REASON: str | None = "env" if _MOCK else None

if not _MOCK:
    try:
        from gpiozero import Button as _BUTTON, LED as _LED, MotionSensor as _PIR  # type: ignore
        _HW = True
    except ImportError as exc:
        _HW = False
        _MOCK = True
        _MOCK_REASON = "no_library"
        print(f"[GPIO] gpiozero を読み込めないため模擬モードで動きます: {exc}")
else:
    _HW = False


def gpio_status() -> dict[str, object]:
    """実機の GPIO を使っているか。reason: env=MOCK_GPIO=true / no_library=gpiozero が無い。"""
    return {"hardware": _HW, "reason": _MOCK_REASON}


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

    def is_configured(self, locker_id: str) -> bool:
        return str(locker_id) in self._pin_map

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
        self._last_motion_detected = False

    @property
    def motion_detected(self) -> bool:
        if self._pir is None:
            return False
        # gpiozero's MotionSensor can occasionally raise "deque mutated during
        # iteration" while its smoothing queue is being updated. Keep the last
        # known state and retry once before falling back to that cached value.
        for _ in range(2):
            try:
                detected = bool(self._pir.motion_detected)  # type: ignore[attr-defined]
                self._last_motion_detected = detected
                return detected
            except RuntimeError as exc:
                if "deque mutated during iteration" not in str(exc):
                    raise
        return self._last_motion_detected

    def close(self) -> None:
        if self._pir is not None:
            self._pir.close()  # type: ignore[attr-defined]

    def info(self) -> dict[str, object]:
        return {"kind": "pir"}


# ── 距離センサー(ToF)で来訪を検知する ────────────────────────────────────────
# 人感センサー(PIR)は「動き」に 1 本の信号線で反応する。距離センサーは I2C で距離(mm)を
# 返すので、「しきい値より近くに何かある」を来訪とみなす。画面から見える形は PIR と同じ
# (motion_detected)にしてあり、kiosk.html は機種を知らなくてよい。

TOF_MODELS = ("vl53l0x", "vl53l1x")


class TofPresence:
    """距離の読みから「来訪あり」を決める(ハードに触れない＝テストできる)。

    - 近い読みが confirm_reads 回続いたら検知(1 回だけの誤った読みで起こさない)。
    - 遠い読みが confirm_reads 回続いたら解除。
    - 近い状態が stale_sec 秒続いたら、離れるまで検知を止める。距離センサーは
      「物があるだけ」で近いと読み続けるので、置かれた物や向かいの壁が範囲に入ると
      待機画面へ戻るたびにすぐ起きてしまう。人なら待機画面は 1 秒以内に切り替わるので、
      これだけ長く近いままなのは「利用中の人(画面は待機ではない)」か「物」のどちらか。
    """

    def __init__(self, threshold_mm: int, confirm_reads: int = 3, stale_sec: float = 60.0):
        self.threshold_mm = max(1, int(threshold_mm))
        self.confirm_reads = max(1, int(confirm_reads))
        self.stale_sec = max(0.0, float(stale_sec))
        self._near_count = 0
        self._far_count = 0
        self._near_since: float | None = None
        self._last = 0.0

    def feed(self, distance_mm: int | None, now: float) -> None:
        """読み 1 回ぶん。distance_mm=None は「範囲内に何も無い・読めなかった」。"""
        self._last = now
        if distance_mm is not None and 0 < distance_mm <= self.threshold_mm:
            self._far_count = 0
            self._near_count += 1
            if self._near_since is None and self._near_count >= self.confirm_reads:
                self._near_since = now
        else:
            self._near_count = 0
            self._far_count += 1
            if self._far_count >= self.confirm_reads:
                self._near_since = None

    def reset(self) -> None:
        """読めなくなったとき。前の「近い」を持ち越さない(故障を来訪に見せない)。"""
        self._near_count = 0
        self._far_count = 0
        self._near_since = None

    @property
    def near(self) -> bool:
        return self._near_since is not None

    @property
    def suppressed(self) -> bool:
        """近いままが長く続いたので、離れるまで検知を止めている。"""
        return (
            self._near_since is not None
            and self.stale_sec > 0
            and self._last - self._near_since >= self.stale_sec
        )

    @property
    def detected(self) -> bool:
        return self.near and not self.suppressed


def _open_vl53l0x():
    import adafruit_vl53l0x  # type: ignore
    import board  # type: ignore

    # io_timeout_s の既定 0 は結果を無期限に待つ(読むスレッドが黙って止まる)
    sensor = adafruit_vl53l0x.VL53L0X(board.I2C(), io_timeout_s=0.5)
    # 既定のままだと暗い色の服で 1m に届かないことがある。弱い反射も受け付け、
    # 1 回の測定に時間をかけて届く距離を伸ばす(機種の上限は実用 1m 前後)。
    try:
        sensor.signal_rate_limit = 0.1
        sensor.measurement_timing_budget = 100_000
    except Exception as exc:  # 設定できなくても既定値で測れる
        print(f"[ToF] VL53L0X の長距離設定を適用できなかった(既定値で続行): {exc}")

    def read() -> int | None:
        mm = int(sensor.range)
        return mm if 0 < mm < 8000 else None  # 8190 前後は「範囲外」

    return read


def _open_vl53l1x():
    import adafruit_vl53l1x  # type: ignore
    import board  # type: ignore

    sensor = adafruit_vl53l1x.VL53L1X(board.I2C())
    sensor.distance_mode = 2  # 長距離(最大約 4m)
    sensor.timing_budget = 100
    sensor.start_ranging()

    def read() -> int | None:
        deadline = time.monotonic() + 0.5
        while not sensor.data_ready:
            if time.monotonic() > deadline:
                raise TimeoutError("VL53L1X から測定結果が返らない")
            time.sleep(0.01)
        cm = sensor.distance  # 範囲内に何も無ければ None
        sensor.clear_interrupt()
        return int(round(cm * 10)) if cm else None

    return read


_TOF_OPENERS = {"vl53l0x": _open_vl53l0x, "vl53l1x": _open_vl53l1x}


class TofSensor:
    """I2C の距離センサー(VL53L0X / VL53L1X)。PirSensor と同じ motion_detected を持つ。

    別スレッドで読み続ける(I2C の読みは 1 回 0.1 秒ほど止まるので、要求のたびに読まない)。
    ライブラリが無い・配線が外れているときは黙って「検知なし」にせず、error に理由を残す
    (デバイスチェック画面に出す)。つなぎ直せば RETRY_SEC 秒以内に自分で戻る。
    """

    RETRY_SEC = 5.0
    # 読みがこの秒数届かなければ、読むスレッドが止まっているとみなす
    # (最後に読めた「近い」のまま待機画面を起こし続けない)
    FROZEN_SEC = 8.0

    def __init__(self, model: str, threshold_mm: int = 1000, confirm_reads: int = 3,
                 stale_sec: float = 60.0, interval_sec: float = 0.02, opener=None):
        self.pin = None
        self._fed_at = time.monotonic()
        self.model = model
        self._presence = TofPresence(threshold_mm, confirm_reads, stale_sec)
        self._interval = max(0.02, float(interval_sec))
        self._opener = opener or _TOF_OPENERS[model]
        self._lock = threading.Lock()
        self._distance_mm: int | None = None
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread = None
        if opener is None and os.getenv("MOCK_GPIO", "false").lower() == "true":
            self._error = "mock"
            return
        self._thread = threading.Thread(target=self._run, name="tof-sensor", daemon=True)
        self._thread.start()

    def _set(self, distance_mm: int | None, error: str | None) -> None:
        with self._lock:
            self._distance_mm = distance_mm
            self._error = error
            self._fed_at = time.monotonic()
            if error is not None:
                self._presence.reset()  # 読めないあいだ、前の「近い」で検知を返し続けない
            else:
                self._presence.feed(distance_mm, self._fed_at)

    def _frozen(self) -> bool:
        return self._thread is not None and time.monotonic() - self._fed_at > self.FROZEN_SEC

    def _run(self) -> None:
        last_logged = None
        while not self._stop.is_set():
            try:
                read = self._opener()
            except ImportError as exc:
                code, detail = "no_library", exc
            except RuntimeError as exc:  # 応答はあるが ID が違う＝設定した機種と別のセンサー
                code, detail = "wrong_model", exc
            except Exception as exc:
                code, detail = "no_device", exc
            else:
                code, detail = None, None
                if last_logged is not None:
                    print(f"[ToF] {self.model} につながった")
                    last_logged = None
                try:
                    while not self._stop.is_set():
                        self._set(read(), None)
                        self._stop.wait(self._interval)
                except Exception as exc:
                    code, detail = "read_failed", exc
            if code is None:
                return
            self._set(None, code)
            if code != last_logged:  # 5 秒ごとに同じ行を出し続けない
                print(f"[ToF] {self.model} を読めない({code}): {detail}")
                last_logged = code
            self._stop.wait(self.RETRY_SEC)

    @property
    def motion_detected(self) -> bool:
        with self._lock:
            return self._presence.detected and not self._frozen()

    def info(self) -> dict[str, object]:
        with self._lock:
            return {
                "kind": "tof",
                "model": self.model,
                "distance_mm": self._distance_mm,
                "threshold_mm": self._presence.threshold_mm,
                "suppressed": self._presence.suppressed,
                "error": "read_failed" if self._frozen() else self._error,
            }

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def make_presence_sensor(kind: str, pir_pin: int, threshold_mm: int = 1000,
                         confirm_reads: int = 3, stale_sec: float = 60.0):
    """設定(PRESENCE_SENSOR)から来訪検知のセンサーを作る。知らない値は PIR として扱う。"""
    name = (kind or "pir").strip().lower()
    if name in TOF_MODELS:
        return TofSensor(name, threshold_mm, confirm_reads, stale_sec)
    if name != "pir":
        print(f"[GPIO] PRESENCE_SENSOR={kind!r} は知らない値なので人感センサー(PIR)として動きます")
    return PirSensor(pir_pin)


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
