"""OS / ハードウェアの状態取得（標準ライブラリのみ）。

ブラウザからは取れない値を Raspberry Pi 上で読む。**新しい pip 依存は増やさない**
（psutil 等を入れない）ため、すべて `/proc` `/sys` と `shutil` から読む。

Linux 以外（Windows 開発機）では取得できない項目を `None` で返す。
既存のモック方針（実機でしか動かないものだけ agent 層でスタブ）と同じ扱い。
"""
from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path

_IS_LINUX = platform.system() == "Linux"

# CPU 使用率は /proc/stat の差分でしか出せないので、前回値を覚えておく。
_last_cpu: tuple[int, int] | None = None


def is_linux() -> bool:
    return _IS_LINUX


def os_version() -> str:
    """例: "Debian GNU/Linux 12 (bookworm) / 6.6.51+rpt-rpi-v8"（64文字まで）。"""
    pretty = ""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip().strip('"')
                break
    except Exception:
        pretty = platform.system()
    rel = platform.release()
    value = f"{pretty} / {rel}" if pretty else rel
    return value[:64]


def uptime_sec() -> int | None:
    """OS の連続稼働秒。稼働率の分母（電源が入っていた時間）の裏取りに使う。"""
    if not _IS_LINUX:
        return None
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        return None


def cpu_percent() -> float | None:
    """前回呼び出しからの CPU 使用率。初回は None（差分が取れないため）。"""
    global _last_cpu
    if not _IS_LINUX:
        return None
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [int(v) for v in parts]
    except Exception:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    prev = _last_cpu
    _last_cpu = (idle, total)
    if prev is None:
        return None
    d_idle = idle - prev[0]
    d_total = total - prev[1]
    if d_total <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - d_idle / d_total) * 100)), 1)


def cpu_temp_c() -> float | None:
    if not _IS_LINUX:
        return None
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        try:
            raw = int(path.read_text().strip())
        except Exception:
            continue
        # millidegree (Pi) か degree かを桁数で判定する
        temp = raw / 1000 if abs(raw) > 1000 else float(raw)
        if -50 < temp < 200:
            return round(temp, 1)
    return None


def memory_mb() -> tuple[int | None, int | None]:
    """(使用中 MB, 合計 MB)。MemAvailable があればそれを優先する。"""
    if not _IS_LINUX:
        return None, None
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split()
            if value and value[0].isdigit():
                info[key] = int(value[0])  # kB
    except Exception:
        return None, None
    total = info.get("MemTotal")
    if not total:
        return None, None
    available = info.get("MemAvailable")
    if available is None:
        available = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
    return int((total - available) / 1024), int(total / 1024)


def disk_mb(path: str = "/") -> tuple[int | None, int | None]:
    """(空き MB, 合計 MB)。"""
    try:
        usage = shutil.disk_usage(path if _IS_LINUX else os.path.abspath(os.sep))
    except Exception:
        return None, None
    return int(usage.free / 1024 / 1024), int(usage.total / 1024 / 1024)


_TOUCH_HINTS = ("touchscreen", "touch screen", "ft5406", "goodix", "edt-ft5x06", "hid-multitouch")


def touch_connected() -> bool | None:
    """タッチパネルが接続されているか。/proc/bus/input/devices の名前で判定する。"""
    if not _IS_LINUX:
        return None
    try:
        text = Path("/proc/bus/input/devices").read_text(errors="ignore").lower()
    except Exception:
        return None
    if any(hint in text for hint in _TOUCH_HINTS):
        return True
    # 名前で分からない機種向けの保険: 絶対座標イベントを持つデバイスがあるか
    return "abs" in text and "event" in text and "touch" in text


def snapshot(*, with_metrics: bool = True) -> dict:
    """メトリクス1件ぶんのハードウェア情報。取得できない項目は None。"""
    data: dict = {
        "uptime_sec": uptime_sec(),
        "os_version": os_version(),
    }
    if not with_metrics:
        return data
    mem_used, mem_total = memory_mb()
    disk_free, disk_total = disk_mb()
    data.update(
        {
            "cpu_percent": cpu_percent(),
            "cpu_temp_c": cpu_temp_c(),
            "mem_used_mb": mem_used,
            "mem_total_mb": mem_total,
            "disk_free_mb": disk_free,
            "disk_total_mb": disk_total,
            "touch_connected": touch_connected(),
        }
    )
    return data


def monotonic() -> float:
    return time.monotonic()
