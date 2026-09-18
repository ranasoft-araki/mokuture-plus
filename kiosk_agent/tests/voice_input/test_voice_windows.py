"""Windows 開発機での動作試験まわり。

実機(Pi)は arecord + 自前ビルドの whisper-cli、Windows は sounddevice + 配布バイナリ、
という二本立てになる。**同じ設定ファイルで両方動く**ことと、マイクが無い環境でも
WAV で経路を通せることを確かめる。
"""
from __future__ import annotations

import wave
from array import array

import pytest

from voice import capture, settings, whisper_cpp
from voice_audio import silence, tone


def write_wav(path, pcm: bytes, *, rate: int = 16000, channels: int = 1, width: int = 2) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)


# ── whisper-cli の場所を OS で持ち替える ──────────────────────────────────────

def test_windowsでは配布バイナリを見る(monkeypatch):
    monkeypatch.setattr(whisper_cpp.platform, "system", lambda: "Windows")
    assert whisper_cpp.binary_path().name == "whisper-cli.exe"


def test_linuxではビルドしたものを見る(monkeypatch):
    monkeypatch.setattr(whisper_cpp.platform, "system", lambda: "Linux")
    assert whisper_cpp.binary_path().name == "whisper-cli"


def test_windows用が空なら共通の設定に落ちる(monkeypatch):
    """片方の環境だけ別の場所に置きたいときに、空にして共通側へ寄せられる。"""
    monkeypatch.setattr(whisper_cpp.platform, "system", lambda: "Windows")
    settings.cfg()["whisper"]["binary_windows"] = ""
    assert whisper_cpp.binary_path().name == "whisper-cli"


def test_未導入の案内がOSごとに変わる(monkeypatch, tmp_path):
    settings.cfg()["whisper"]["binary"] = str(tmp_path / "nope")
    settings.cfg()["whisper"]["binary_windows"] = str(tmp_path / "nope.exe")

    monkeypatch.setattr(whisper_cpp.platform, "system", lambda: "Windows")
    ok, detail = whisper_cpp.available()
    assert not ok and "install_voice_windows.ps1" in detail

    monkeypatch.setattr(whisper_cpp.platform, "system", lambda: "Linux")
    ok, detail = whisper_cpp.available()
    assert not ok and "install_voice.sh" in detail


# ── WAV をマイクの代わりに流す ────────────────────────────────────────────────

def test_wavを流して録音ループを通せる(tmp_path):
    """マイクが無い環境でも、本番と同じ VAD 経路を通せること。"""
    wav = tmp_path / "speech.wav"
    write_wav(wav, silence(200) + tone(800) + silence(1200))

    cfg = settings.cfg()
    cfg["audio"]["backend"] = "file"
    cfg["audio"]["file_path"] = str(wav)
    cfg["audio"]["start_guard_ms"] = 0

    ok, detail = capture.available()
    assert ok, detail

    from voice import vad
    stream = capture.open_stream()
    try:
        seg = vad.record_utterance(stream)
    finally:
        stream.close()

    assert seg.stop_reason == "silence"
    assert seg.speech_ms >= 600


def test_音源が無ければ使えないと分かる(tmp_path):
    cfg = settings.cfg()
    cfg["audio"]["backend"] = "file"
    cfg["audio"]["file_path"] = str(tmp_path / "missing.wav")
    ok, detail = capture.available()
    assert not ok and "見つかりません" in detail


def test_file_path未設定なら使えないと分かる():
    settings.cfg()["audio"]["backend"] = "file"
    ok, detail = capture.available()
    assert not ok and "file_path" in detail


# ── WAV の読み込み（録った音源をそのまま使えるように） ───────────────────────

def test_16kモノラルはそのまま読める(tmp_path):
    wav = tmp_path / "a.wav"
    pcm = tone(500)
    write_wav(wav, pcm)
    assert capture.read_wav_as_pcm(wav, 16000) == pcm


def test_ステレオはモノラルに落とす(tmp_path):
    wav = tmp_path / "s.wav"
    mono = array("h", [100, 200, 300, 400])
    stereo = array("h", [100, 100, 200, 200, 300, 300, 400, 400])
    write_wav(wav, stereo.tobytes(), channels=2)

    out = array("h")
    out.frombytes(capture.read_wav_as_pcm(wav, 16000))
    assert list(out) == list(mono)


def test_サンプリングレートを合わせる(tmp_path):
    """スマホやレコーダーで録った 44.1kHz の音源をそのまま渡せるように。"""
    wav = tmp_path / "hi.wav"
    write_wav(wav, tone(1000, rate=48000), rate=48000)

    pcm = capture.read_wav_as_pcm(wav, 16000)
    ms = len(pcm) / 2 / 16000 * 1000
    assert 950 <= ms <= 1050, f"長さが変わっている ({ms:.0f}ms)"


def test_8bitのWAVは理由をつけて断る(tmp_path):
    wav = tmp_path / "8bit.wav"
    write_wav(wav, b"\x80" * 1000, width=1)
    with pytest.raises(capture.CaptureFailed) as e:
        capture.read_wav_as_pcm(wav, 16000)
    assert "16bit" in str(e.value)


# ── デバイス指定の解釈 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("", None),
    ("default", None),
    ("  ", None),
    ("3", 3),
    ("マイク配列", "マイク配列"),
])
def test_デバイス指定の解釈(value, expected):
    """番号は int で渡す（名前は環境によって化けるので番号指定が確実）。"""
    assert capture.parse_device(value) == expected


def test_sounddeviceが無ければマイクは使えないと分かる(monkeypatch):
    settings.cfg()["audio"]["backend"] = "sounddevice"
    monkeypatch.setattr(capture, "_probe_sounddevice",
                        lambda: (False, "sounddevice が入っていません (pip install sounddevice)"))
    ok, detail = capture.available()
    assert not ok and "sounddevice" in detail
