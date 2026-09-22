"""マイクの可否判定とデバイスの解決(arecord)。

現場で踏んだ穴は2つとも「一覧に出るかどうか」を当てにしたせいで起きた。

1. 日本語の Pi では `arecord -l` の見出しが「カード 0: ...」に翻訳される。英語の
   "card" を探していたので、マイクが挿さっていても使えない判定になった。
2. `default` は asym プラグインで再生側しか定義されておらず、`arecord -l` には
   出るのに開くと EINVAL で落ちた。画面には「使える」と出て、「話す」を押した
   瞬間に「マイクの調子が悪いようです」になった。

さらに USB マイクのカード番号は挿し位置や起動順で変わるので、設定に焼き込めない。
ここでは「開けるかは開いてみて確かめる」「設定の指定は尊重する」「駄目なら挿さって
いるマイクへ移る」「挿し替えには次の録音から追従する」を押さえる。
"""
from __future__ import annotations

import subprocess

import pytest

from voice import capture, settings

_LIST_HEADER_EN = "**** List of CAPTURE Hardware Devices ****\n"
_LIST_HEADER_JA = "**** ハードウェアデバイス CAPTURE のリスト ****\n"

_USB_EN = "card 2: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]\n"
_USB_JA = "カード 2: Device [USB PnP Sound Device], デバイス 0: USB Audio [USB Audio]\n"
_I2S_EN = "card 0: sndrpii2scard [snd_rpi_i2s_card], device 0: simple-card_codec [dmic]\n"
_I2S_JA = "カード 0: sndrpii2scard [snd_rpi_i2s_card], デバイス 0: simple-card_codec [dmic]\n"


class FakeArecord:
    """arecord の偽物。見えるカードと「実際に開けるデバイス」を別々に決められる。"""

    def __init__(self, *, cards: str = "usb", openable: set[str] | None = None) -> None:
        self.cards = cards
        self.openable = openable if openable is not None else {"default"}
        self.listed = 0
        self.list_env: dict = {}
        self.opened: list[str] = []

    def _listing(self, c_locale: bool) -> str:
        if self.cards == "none":
            return _LIST_HEADER_EN if c_locale else _LIST_HEADER_JA
        head = _LIST_HEADER_EN if c_locale else _LIST_HEADER_JA
        usb = _USB_EN if c_locale else _USB_JA
        if self.cards == "usb":
            return head + usb
        return head + (_I2S_EN if c_locale else _I2S_JA) + usb    # i2s → usb の順

    def run(self, cmd, **kw):
        env = kw.get("env") or {}
        if "-l" in cmd:
            self.listed += 1
            self.list_env = dict(env)
            # 翻訳されるかはロケール次第。C を渡していなければ日本語で返す。
            return subprocess.CompletedProcess(
                cmd, 0, self._listing(env.get("LC_ALL") == "C"), "")
        device = cmd[cmd.index("-D") + 1]
        self.opened.append(device)
        if device in self.openable:
            return subprocess.CompletedProcess(cmd, 0, b"\x00" * 3200, b"")
        return subprocess.CompletedProcess(
            cmd, 1, b"", b"arecord: main:850: audio open error: Invalid argument")


@pytest.fixture
def arecord(monkeypatch):
    """arecord がある体にして偽物を差す。既定は USB マイク1本・default が開ける。"""
    fake = FakeArecord()
    monkeypatch.setattr(capture.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(capture.subprocess, "run", fake.run)
    monkeypatch.setattr(capture, "_is_usb_card", lambda card: card == 2)
    settings.cfg()["audio"]["backend"] = "arecord"
    return fake


# ── 表示言語に左右されない ────────────────────────────────────────────────────

def test_日本語のPiでもマイクを見つけられる(arecord):
    ok, detail = capture.available()
    assert ok, detail


def test_一覧はロケールをCに固定して読む(arecord):
    """翻訳された出力を読まされないこと(上のテストが成り立つ土台)。"""
    capture.available()
    assert arecord.list_env.get("LC_ALL") == "C"


# ── 開けるかどうかは開いて確かめる ────────────────────────────────────────────

def test_デバイスが無ければ理由が分かる(arecord):
    arecord.cards = "none"
    ok, detail = capture.available()
    assert not ok and "USB マイク" in detail


def test_一覧に出ても開けなければ使えないと分かる(arecord):
    """「画面では使えるのに押すと落ちる」を作らない。"""
    arecord.openable = set()
    ok, detail = capture.available()
    assert not ok and "開けませんでした" in detail
    assert "plughw:2,0" in detail


def test_開けないときも毎回は試さない(arecord):
    """画面は status を繰り返し引く。失敗のたびにテスト録音を走らせない。"""
    arecord.openable = set()
    assert not capture.available()[0]
    tried = len(arecord.opened)
    capture.available()
    assert len(arecord.opened) == tried


def test_defaultが開けなければ挿さっているマイクへ移る(arecord):
    arecord.openable = {"plughw:2,0"}
    ok, detail = capture.available()
    assert ok and "plughw:2,0" in detail
    assert arecord.opened[0] == "default"      # 設定の指定を先に試している


def test_設定で名指ししたデバイスが開けるならそれを使う(arecord):
    settings.cfg()["audio"]["device"] = "plughw:2,0"
    arecord.openable = {"plughw:2,0", "default"}
    ok, detail = capture.available()
    assert ok and "plughw:2,0" in detail
    assert arecord.opened == ["plughw:2,0"]    # 余計なデバイスを触らない


def test_USBのマイクを先に試す(arecord):
    """カード番号順ではなく USB から。内蔵(I2S/HDMI)は当たりにくい。"""
    arecord.cards = "i2s+usb"
    arecord.openable = {"plughw:0,0", "plughw:2,0"}
    ok, detail = capture.available()
    assert ok and "plughw:2,0" in detail


# ── 決めた結果を覚える / 挿し替えで決め直す ───────────────────────────────────

def test_一度決めたら毎回は試さない(arecord):
    arecord.openable = {"plughw:2,0"}
    capture.available()
    tried = len(arecord.opened)
    capture.available()
    capture.available()
    assert len(arecord.opened) == tried


def test_録音が止まったら次の録音で選び直す(arecord, monkeypatch):
    """挿し替えでカード番号が変わっても、次の録音から追従できること。"""
    arecord.openable = {"plughw:2,0"}
    capture.available()
    tried = len(arecord.opened)

    monkeypatch.setattr(capture.subprocess, "Popen", lambda cmd, **kw: _DeadProc())
    stream = capture.ArecordStream("plughw:2,0", 16000, 1)
    try:
        with pytest.raises(capture.CaptureFailed):
            stream.read(3200, timeout=1.0)
    finally:
        stream.close()

    capture.available()
    assert len(arecord.opened) > tried


class _DeadProc:
    """起動した直後に終わってしまう arecord(デバイスが消えた・開けない)。"""

    def __init__(self) -> None:
        import io
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"arecord: main:850: audio open error: No such device\n")

    def terminate(self) -> None:
        pass

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        pass
