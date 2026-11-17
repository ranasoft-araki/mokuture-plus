"""距離センサー(ToF)で来訪を検知する。

人感センサー(PIR)と違い、距離センサーは「物があるだけ」で近いと読み続ける。
1 回だけの誤った読みで起こさないこと・置かれた物で起き続けないこと・読めないときに
黙って「検知なし」にならず理由が画面へ出ることを確かめる。実機の I2C には触れない。
"""
from __future__ import annotations

import asyncio
import importlib
import time

import pytest

import gpio


@pytest.fixture(autouse=True)
def _restore_gpio():
    yield
    importlib.reload(gpio)


def _feed(p, readings, start=0.0, step=0.1):
    t = start
    for mm in readings:
        p.feed(mm, t)
        t += step
    return t


def test_近い読みが続いたときだけ検知する():
    p = gpio.TofPresence(threshold_mm=1000, confirm_reads=3)
    _feed(p, [800, 800])
    assert not p.detected, "2 回ではまだ検知しない"
    p.feed(800, 0.2)
    assert p.detected


def test_1回だけの近い読みでは起こさない():
    p = gpio.TofPresence(threshold_mm=1000, confirm_reads=3)
    _feed(p, [None, 500, None, 500, None, 500, None])
    assert not p.detected


def test_しきい値より遠い読みは検知しない():
    p = gpio.TofPresence(threshold_mm=1000, confirm_reads=3)
    _feed(p, [1001] * 10)
    assert not p.detected
    _feed(p, [1000] * 3, start=1.0)
    assert p.detected, "しきい値ちょうどは範囲内"


def test_離れたら解除し_1回の読み落としでは解除しない():
    p = gpio.TofPresence(threshold_mm=1000, confirm_reads=3)
    t = _feed(p, [700] * 3)
    p.feed(None, t)
    assert p.detected, "読み落とし 1 回で解除しない"
    _feed(p, [None] * 3, start=t + 0.1)
    assert not p.detected


def test_置かれた物では起き続けない():
    p = gpio.TofPresence(threshold_mm=1000, confirm_reads=3, stale_sec=60)
    _feed(p, [600] * 3)
    assert p.detected
    p.feed(600, 61.0)
    assert p.suppressed and not p.detected, "近いままが長く続いたら止める"
    # 読みが 1 回ぶれても止めたまま(ぶれるたびに起き直さない)
    p.feed(None, 61.1)
    p.feed(600, 61.2)
    assert not p.detected
    # いったん離れてから近づけば、また検知する
    t = _feed(p, [None] * 3, start=62.0)
    t = _feed(p, [600] * 3, start=t)
    assert p.detected


def _wait(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_センサーは読み続けて距離と検知を返す():
    s = gpio.TofSensor("vl53l0x", threshold_mm=1000, confirm_reads=2,
                       interval_sec=0.02, opener=lambda: (lambda: 450))
    try:
        assert _wait(lambda: s.motion_detected)
        info = s.info()
        assert info["kind"] == "tof" and info["model"] == "vl53l0x"
        assert info["distance_mm"] == 450 and info["threshold_mm"] == 1000
        assert info["error"] is None
    finally:
        s.close()


@pytest.mark.parametrize("exc, code", [
    (ImportError("No module named 'board'"), "no_library"),
    (ValueError("No I2C device at address: 0x29"), "no_device"),
    (RuntimeError("Wrong sensor ID or type!"), "wrong_model"),
])
def test_つながらない理由を残す(exc, code):
    def opener():
        raise exc

    s = gpio.TofSensor("vl53l0x", opener=opener)
    try:
        assert _wait(lambda: s.info()["error"] == code)
        assert s.motion_detected is False
    finally:
        s.close()


def test_途中で読めなくなったら検知を外し_つなぎ直すと戻る(monkeypatch):
    monkeypatch.setattr(gpio.TofSensor, "RETRY_SEC", 0.05)
    state = {"broken": False}

    def read():
        if state["broken"]:
            raise OSError("[Errno 121] Remote I/O error")
        return 300

    s = gpio.TofSensor("vl53l1x", confirm_reads=3, interval_sec=0.02, opener=lambda: read)
    try:
        assert _wait(lambda: s.motion_detected)
        state["broken"] = True
        assert _wait(lambda: s.info()["error"] is not None)
        # 読めないと分かった時点で外す(遠い読みが confirm_reads 回たまるのを待たない)
        assert s.motion_detected is False
        state["broken"] = False
        assert _wait(lambda: s.info()["error"] is None and s.motion_detected)
    finally:
        s.close()


def test_読むスレッドが止まったら検知を返さない(monkeypatch):
    import threading

    hang = threading.Event()

    def read():
        if hang.is_set():
            threading.Event().wait(1.0)  # 結果が返らないまま止まる
        return 300

    monkeypatch.setattr(gpio.TofSensor, "FROZEN_SEC", 0.2)
    s = gpio.TofSensor("vl53l0x", confirm_reads=1, interval_sec=0.02, opener=lambda: read)
    try:
        assert _wait(lambda: s.motion_detected)
        hang.set()
        assert _wait(lambda: s.motion_detected is False and s.info()["error"] == "read_failed")
    finally:
        s.close()


def test_模擬モードでは読まない(monkeypatch):
    monkeypatch.setenv("MOCK_GPIO", "true")
    s = gpio.TofSensor("vl53l0x")
    assert s.info()["error"] == "mock" and s.motion_detected is False
    s.close()


def test_設定でセンサーを選ぶ(monkeypatch):
    monkeypatch.setenv("MOCK_GPIO", "true")
    g = importlib.reload(gpio)
    assert isinstance(g.make_presence_sensor("pir", 4), g.PirSensor)
    assert isinstance(g.make_presence_sensor("", 4), g.PirSensor)
    assert isinstance(g.make_presence_sensor("なにか", 4), g.PirSensor), "知らない値は従来どおり"
    tof = g.make_presence_sensor(" VL53L1X ", 4, threshold_mm=1500)
    assert isinstance(tof, g.TofSensor) and tof.info()["threshold_mm"] == 1500
    tof.close()


def test_既定は人感センサーのまま_画面へ種類を返す():
    import main

    data = asyncio.run(main.device_status())
    assert data["pir"]["kind"] == "pir", "設定しない端末(既設)は変わらない"
    assert "motion_detected" in data["pir"] and "pin" in data["pir"]
