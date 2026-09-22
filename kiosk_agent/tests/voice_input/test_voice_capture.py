"""マイクの可否判定(arecord)。

日本語の Raspberry Pi では `arecord -l` の見出しが「カード 0: ...」に翻訳される。
可否判定が英語の "card" を探していたため、マイクが挿さっていても available=false に
なり、キオスク本体のデバイス確認画面では AVAILABLE なのに音声入力だけ使えない、
という食い違いが起きていた。機械で読む呼び出しはロケールを C に固定する。
"""
from __future__ import annotations

import subprocess

import pytest

from voice import capture, settings

_ARECORD_EN = """**** List of CAPTURE Hardware Devices ****
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""

_ARECORD_JA = """**** ハードウェアデバイス CAPTURE のリスト ****
カード 1: Device [USB PnP Sound Device], デバイス 0: USB Audio [USB Audio]
  サブデバイス: 1/1
  サブデバイス #0: subdevice #0
"""


@pytest.fixture
def arecord(monkeypatch):
    """arecord がある体にして、`-l` の出力をロケールで持ち替える偽物を差す。"""
    calls: list[dict] = []

    def fake_run(cmd, **kw):
        env = kw.get("env") or {}
        calls.append({"cmd": cmd, "env": env})
        out = _ARECORD_EN if env.get("LC_ALL") == "C" else _ARECORD_JA
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(capture.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    settings.cfg()["audio"]["backend"] = "arecord"
    return calls


def test_日本語のPiでもマイクを見つけられる(arecord):
    ok, detail = capture.available()
    assert ok, detail


def test_可否判定はロケールをCに固定して読む(arecord):
    capture.available()
    assert arecord[-1]["env"].get("LC_ALL") == "C"


def test_デバイスが無ければ理由が分かる(monkeypatch):
    monkeypatch.setattr(capture.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        capture.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, "**** List of CAPTURE Hardware Devices ****\n", ""))
    settings.cfg()["audio"]["backend"] = "arecord"

    ok, detail = capture.available()
    assert not ok and "USB マイク" in detail
