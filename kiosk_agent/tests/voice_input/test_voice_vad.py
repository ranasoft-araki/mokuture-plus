"""録音ループと VAD(§8)。

合成した PCM を流し、発話区間の切り出しと終了条件を確かめる。時計は差し替えて、
実時間を待たずに「5 秒待っても話し始めない」などの経路まで通す。
"""
from __future__ import annotations

import pytest

from voice import capture, settings, vad
from voice_audio import noise, silence, tone

RATE = 16000


class FakeClock:
    """呼ばれるたびに 1 フレームぶん進む時計。録音ループは 1 周に 1 回呼ぶ。"""

    def __init__(self, frame_ms: int) -> None:
        self.t = 0.0
        self.step = frame_ms / 1000.0

    def __call__(self) -> float:
        self.t += self.step
        return self.t


@pytest.fixture
def clock():
    return FakeClock(int(settings.get("vad.frame_ms")))


def record(pcm: bytes, clock, **kw):
    stream = capture.BufferStream(pcm)
    try:
        return vad.record_utterance(stream, now=clock, **kw)
    finally:
        stream.close()


def ms_of(pcm: bytes) -> int:
    return int(len(pcm) / 2 / RATE * 1000)


# ── 正常系 ────────────────────────────────────────────────────────────────────

def test_speech_then_silence_stops_automatically(clock):
    """話し終えて無音が続いたら自動で終わる(§8)。"""
    seg = record(silence(400) + tone(1000) + silence(2000), clock)
    assert seg.stop_reason == "silence"
    assert 800 <= seg.speech_ms <= 1300
    assert seg.pcm


def test_leading_and_trailing_silence_is_not_sent_to_recognition(clock):
    """前後の不要な無音は認識処理へ渡さない(§8)。

    3.5 秒ぶん流しても、認識に回すのは発話 1 秒 + 前後の余白だけ。
    """
    seg = record(silence(1000) + tone(1000) + silence(1500), clock)
    assert seg.stop_reason == "silence"
    audio_ms = ms_of(seg.pcm)
    pre = float(settings.get("vad.pre_roll_ms"))
    post = float(settings.get("vad.post_roll_ms"))
    assert audio_ms <= 1000 + pre + post + 200, "無音まで認識に渡している"
    assert audio_ms >= 900, "発話が削られている"


def test_pre_roll_keeps_the_beginning_of_speech(clock):
    """発話の直前を少し残す(語頭の子音が切れないように)。"""
    seg = record(silence(600) + tone(800) + silence(1500), clock)
    assert ms_of(seg.pcm) > 800


def test_quiet_room_adapts_noise_floor(clock):
    """暗騒音があっても、それを発話と取り違えない。"""
    seg = record(noise(1500, dbfs=-55) + silence(3000), clock)
    assert seg.stop_reason == "no_speech"
    assert seg.speech_ms == 0


def test_noisy_room_still_detects_speech(clock):
    """空調音が乗っていても、はっきりした発話は拾う。"""
    seg = record(noise(600, dbfs=-50) + tone(900, dbfs=-18) + silence(2000), clock)
    assert seg.stop_reason == "silence"
    assert seg.speech_ms >= 600


# ── 終了条件 ──────────────────────────────────────────────────────────────────

def test_no_speech_within_start_timeout(clock):
    """話し始めなければ「発話開始待ち」で終わる(§7 の「音声が検出されない」)。"""
    seg = record(silence(9000), clock)
    assert seg.stop_reason == "no_speech"
    assert seg.speech_ms == 0
    assert seg.pcm == b""


def test_max_record_sec_cuts_long_speech(clock):
    """最大録音時間で打ち切る(§8)。"""
    seg = record(tone(12000), clock, max_record_sec=2.0)
    assert seg.stop_reason == "max_duration"
    assert ms_of(seg.pcm) <= 2600


def test_manual_stop_finishes_immediately(clock):
    """「入力を終了」ボタンでそこまでを発話として確定する(§8)。"""
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 30        # 発話が始まってしばらくしたら押す

    seg = record(tone(9000), clock, should_stop=should_stop)
    assert seg.stop_reason == "manual"
    assert seg.speech_ms > 0


def test_stop_before_speaking_ends_immediately(clock):
    """話す前に「入力を終了」を押したら、発話開始待ちを待たずに終わる。

    待たせると画面のボタンが効いていないように見える。
    """
    seg = record(silence(9000), clock, should_stop=lambda: True)
    assert seg.stop_reason == "no_speech"
    assert seg.speech_ms == 0
    # 発話開始待ち(5 秒)を消化していないこと
    assert seg.total_ms < 1000


def test_cancel_discards_everything(clock):
    """キャンセルは録音を捨てる。"""
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 20

    seg = record(tone(9000), clock, should_cancel=should_cancel)
    assert seg.stop_reason == "cancelled"


# ── 画面へのフィードバック ────────────────────────────────────────────────────

def test_level_callback_drives_the_meter(clock):
    """録音中は音量が画面へ流れる(§5「入力音量または簡易的な波形」)。"""
    levels: list[float] = []
    record(silence(300) + tone(800) + silence(1500), clock,
           on_level=lambda level, db: levels.append(level))
    assert levels, "音量が 1 度も通知されていない"
    assert max(levels) > 0.2, "発話中の音量が上がっていない"
    assert min(levels) < 0.1, "無音時に音量が下がっていない"


def test_speech_start_callback_fires_once(clock):
    """「聞き取り中」へ切り替える合図は、発話を検出したときだけ。"""
    fired = {"n": 0}
    record(silence(400) + tone(700) + silence(1500), clock,
           on_speech_start=lambda: fired.__setitem__("n", fired["n"] + 1))
    assert fired["n"] == 1


def test_start_guard_drops_the_beginning(clock):
    """開始音の回り込み対策で、頭の数百 ms は判定に使わない(§9)。"""
    cfg = settings.cfg()
    cfg["audio"]["start_guard_ms"] = 400
    # ガード中にだけ鳴っている音は発話として拾わない
    seg = record(tone(300) + silence(9000), clock)
    assert seg.stop_reason == "no_speech"


# ── 音量計 ────────────────────────────────────────────────────────────────────

def test_dbfs_of_silence_and_tone():
    assert vad.dbfs(silence(100)) < -90
    assert -25 < vad.dbfs(tone(100, dbfs=-20)) < -15


def test_meter_level_is_bounded():
    assert vad.meter_level(-100.0) == 0.0
    assert vad.meter_level(0.0) == 1.0
    assert 0.0 < vad.meter_level(-30.0) < 1.0
