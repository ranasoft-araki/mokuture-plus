"""録音ループと VAD(§8)。

合成した PCM を流し、発話区間の切り出しと終了条件を確かめる。時計は差し替えて、
実時間を待たずに「5 秒待っても話し始めない」などの経路まで通す。
"""
from __future__ import annotations

import pytest

from voice import capture, settings, vad
from voice_audio import noise, room, silence, tone

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
    seg = record(room(400) + tone(1000) + silence(2000), clock)
    assert seg.stop_reason == "silence"
    assert 800 <= seg.speech_ms <= 1300
    assert seg.pcm


def test_leading_and_trailing_silence_is_not_sent_to_recognition(clock):
    """前後の不要な無音は認識処理へ渡さない(§8)。

    3.5 秒ぶん流しても、認識に回すのは発話 1 秒 + 前後の余白だけ。
    """
    seg = record(room(1000) + tone(1000) + silence(1500), clock)
    assert seg.stop_reason == "silence"
    audio_ms = ms_of(seg.pcm)
    pre = float(settings.get("vad.pre_roll_ms"))
    post = float(settings.get("vad.post_roll_ms"))
    assert audio_ms <= 1000 + pre + post + 200, "無音まで認識に渡している"
    assert audio_ms >= 900, "発話が削られている"


def test_pre_roll_keeps_the_beginning_of_speech(clock):
    """発話の直前を少し残す(語頭の子音が切れないように)。"""
    seg = record(room(600) + tone(800) + silence(1500), clock)
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


def test_loud_room_waits_for_the_speaker(clock):
    """暗騒音が大きくても、話し始めるまで録音を始めない。

    以前は暗騒音の見積もりが -55 dBFS から始まり、それより 9dB うるさい場所では窓を開けた
    瞬間に話し始めと判定され、話していると判定している間は暗騒音を学ばないので、声と関係なく
    上限(max_record_sec)で切れていた(実機で「話している最中に認識が始まる」)。
    """
    starts: list[float] = []
    seg = record(noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40), clock,
                 max_record_sec=3.0, on_speech_start=lambda: starts.append(clock.t))
    assert seg.stop_reason == "silence"
    assert starts and 2.9 <= starts[0] <= 3.4, f"声の前に録音が始まっている: {starts}"
    assert 600 <= seg.speech_ms <= 1100


def test_lead_in_is_pre_roll_before_the_first_voiced_frame(clock):
    """頭に残すのは「最初に声と判定したコマ」の pre_roll 前から。

    話し始めの判定(onset_ms)を待ったぶんまで残すと頭の無音が長くなり、短い数字
    (「にばん」の「に」)が頭の雑音に吸われる(合成音声で信頼度 0.81 → 0.53)。
    """
    seg = record(noise(1000, dbfs=-55) + tone(800, dbfs=-20) + noise(2000, dbfs=-55), clock)
    assert seg.stop_reason == "silence"
    pre = float(settings.get("vad.pre_roll_ms"))
    post = float(settings.get("vad.post_roll_ms"))
    assert ms_of(seg.pcm) <= 800 + pre + post + 60, "頭に判定待ちのぶんまで残している"


def test_without_start_guard_the_floor_is_measured_before_judging(clock):
    """開始音ガードが 0 で履歴も無くても、測る前に判定しない(うるさい場所で最初のコマが話し始めになる)。"""
    settings.cfg()["audio"]["start_guard_ms"] = 0
    seg = record(noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40), clock, max_record_sec=3.0)
    assert seg.stop_reason == "silence"
    assert 600 <= seg.speech_ms <= 1100


def test_late_first_frame_is_still_measured_before_judging():
    """録音の立ち上がりが遅れて、最初の音が開始音ガードの後に届いても、測ってから判定する。"""
    class LateClock(FakeClock):
        calls = 0

        def __call__(self) -> float:
            self.calls += 1
            if self.calls == 2:
                self.t += 0.5                     # 最初の 1 コマが 0.5 秒遅れて届いた
            return super().__call__()

    seg = record(noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40),
                 LateClock(int(settings.get("vad.frame_ms"))), max_record_sec=3.0)
    assert seg.stop_reason == "silence"
    assert 600 <= seg.speech_ms <= 1100


def test_frames_measured_as_the_room_are_kept_as_the_lead_in(clock):
    """暗騒音を測っている間のコマも語頭の手前として残す。音源がすぐ話し始めると語頭がそこに入る。"""
    settings.cfg()["audio"]["start_guard_ms"] = 0
    speech = noise(800, dbfs=-20)             # 繰り返さない波形(tone は 5 コマごとに同じ形になる)
    seg = record(noise(60, dbfs=-60) + speech + noise(2000, dbfs=-60), clock)
    assert seg.stop_reason == "silence"
    step = int(settings.get("vad.frame_ms")) * 16 * 2
    assert speech[:step] in seg.pcm, "測っている間に来た語頭を捨てている"


def test_mic_that_returns_zeros_while_silent_still_hears_speech(clock):
    """ノイズゲート付きのマイクは無音を 0 で返す。0 が続けば静かな部屋とみなして判定する。

    0 を数えないだけだと履歴が育たず、毎回声の頭を暗騒音として測って声を拾えない
    (合成音声で 176/180 → 15/180)。
    """
    # 起動後、ゲートが閉じるのを見るまでは見分けられない(最初の 1 回は取りこぼしうる)
    record(room(300) + tone(800, dbfs=-20) + silence(2000), clock)
    for _ in range(3):                         # 以後は窓を開け直しても毎回拾う
        seg = record(silence(600) + tone(800, dbfs=-20) + silence(2000), FakeClock(int(settings.get("vad.frame_ms"))))
        assert seg.stop_reason == "silence"
        assert seg.speech_ms >= 600


def test_zero_room_ignores_a_floor_learned_from_speech(clock):
    """0 が続く部屋では、履歴に声の頭を覚えていても初期値より高くは見積もらない。"""
    record(noise(400, dbfs=-20) + silence(8000), clock)        # 窓の頭の声を暗騒音として覚えた(ゲートも見た)
    seg = record(silence(600) + noise(800, dbfs=-20) + silence(2000), FakeClock(int(settings.get("vad.frame_ms"))))
    assert seg.stop_reason == "silence"
    assert seg.speech_ms >= 600


def test_a_mistaken_gate_is_forgotten_after_running_to_the_limit(clock):
    """ミュートや USB の瞬断で一度だけ「音のあとに 0」が出ても、0 の部屋とみなした窓が上限まで
    鳴り続けたら見分け直す(開いた直後に 0 を返す機材 + うるさい部屋で打ち切りを繰り返さない)。"""
    vad._zero_gate_seen = True                 # 一度だけ 0 が出て、ゲートと見誤った
    fc = lambda: FakeClock(int(settings.get("vad.frame_ms")))
    loud = silence(400) + noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40)
    first = record(loud, fc(), max_record_sec=3.0)
    assert first.stop_reason == "max_duration"
    assert vad._zero_gate_seen is False
    seg = record(loud, fc(), max_record_sec=3.0)
    assert seg.stop_reason == "silence"
    assert 600 <= seg.speech_ms <= 1100


def test_zeros_only_at_stream_start_do_not_make_a_loud_room_quiet(clock):
    """マイクが開いた直後だけ 0 を返す機材では、0 が長くても「静かな部屋」にしない。

    窓の頭の 0 で決めると、うるさい部屋で元の打ち切りに戻り、窓ごとに繰り返す。
    """
    for _ in range(3):
        seg = record(silence(600) + noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40),
                     FakeClock(int(settings.get("vad.frame_ms"))), max_record_sec=3.0)
        assert seg.stop_reason == "silence"
        assert 600 <= seg.speech_ms <= 1100


def test_zeros_at_stream_start_are_not_taken_as_the_room(clock):
    """マイクが開いた直後に 0 を返しても(_ZERO_ROOM_MS より短い)、0 は暗騒音として数えず、
    本物の音を測ってから判定する。"""
    seg = record(silence(200) + noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40), clock,
                 max_record_sec=3.0)
    assert seg.stop_reason == "silence"
    assert 600 <= seg.speech_ms <= 1100


def test_history_cleared_by_another_window_is_measured_again(clock):
    """窓を開けたときは履歴があったのに、判定の前に別の窓が消しても、固定の初期値で判定しない。"""
    record(noise(3000, dbfs=-40) + silence(8000), clock)          # 履歴を作る
    guard_frames = int(float(settings.get("audio.start_guard_ms")) / int(settings.get("vad.frame_ms")))
    calls = {"n": 0}

    def clear_before_first_judgement(level: float, db: float) -> None:
        calls["n"] += 1
        if calls["n"] == guard_frames:                              # ガードの最後のコマ = 判定の直前
            vad.forget_noise_floor()

    seg = record(noise(3000, dbfs=-40) + tone(800, dbfs=-18) + noise(3000, dbfs=-40),
                 FakeClock(int(settings.get("vad.frame_ms"))), max_record_sec=3.0,
                 on_level=clear_before_first_judgement)
    assert seg.stop_reason == "silence"
    assert 600 <= seg.speech_ms <= 1100


def test_noise_history_survives_being_cleared_by_another_window():
    """セッションは最大 4 つ。別の窓が履歴を消しても、読む側は落ちない。"""
    import threading
    h = vad._NoiseHistory()
    h.begin(100, 60.0)
    stop = threading.Event()

    def churn():
        while not stop.is_set():
            for d in (-50.0, -51.0, -52.0, -53.0):
                h.add(d)
            h.clear()

    th = threading.Thread(target=churn)
    th.start()
    try:
        for _ in range(20000):
            m = h.median()
            assert m is None or -53.0 <= m <= -50.0
    finally:
        stop.set()
        th.join()


def test_the_first_voiced_frame_is_repeated_once(clock):
    """語頭を 1 コマ引き延ばす(onset_repeat_frames)。1 拍の数字の頭が雑音に吸われにくくなる。"""
    seg = record(noise(1000, dbfs=-55) + tone(800, dbfs=-20) + noise(2000, dbfs=-55), clock)
    step = int(settings.get("vad.frame_ms")) * 16 * 2
    frames = [seg.pcm[i:i + step] for i in range(0, len(seg.pcm), step)]
    repeats = [i for i in range(len(frames) - 1) if frames[i] == frames[i + 1]]
    assert len(repeats) == 1
    cfg = settings.cfg()
    cfg["vad"]["onset_repeat_frames"] = 0
    vad.forget_noise_floor()
    seg = record(noise(1000, dbfs=-55) + tone(800, dbfs=-20) + noise(2000, dbfs=-55), FakeClock(int(settings.get("vad.frame_ms"))))
    frames = [seg.pcm[i:i + step] for i in range(0, len(seg.pcm), step)]
    assert not any(frames[i] == frames[i + 1] for i in range(len(frames) - 1))


def test_a_voice_near_the_threshold_still_starts_recording(clock):
    """少し離れて話した声(暗騒音＋5〜9dB が続き、ときどき＋9dB を越える)でも録音を始める。

    「声の大きさが 0.1 秒」を求めていたとき、実機で「かなりマイクに近づかないと認識しない」になった。
    """
    voice = (tone(20, dbfs=-40) + tone(60, dbfs=-44)) * 10          # 4 コマに 1 コマだけ＋9dB を越える
    seg = record(noise(2000, dbfs=-50) + voice + noise(3000, dbfs=-50), clock)
    assert seg.stop_reason == "silence"
    # 話している間に判定ラインが上がって途中で「話し終わり」にならず、声の区間を丸ごと録る
    assert ms_of(seg.pcm) >= ms_of(voice), "小さめの声の途中で切れている"


def test_post_roll_is_the_sound_right_after_the_voice(clock):
    """話し終わりに足すのは声の直後の pre/post roll ぶん。無音の最後のほうではない。

    以前は溜める入れ物が post_roll ぶんしか無く、声の直後 0.46 秒が抜けて、無音の最後の
    0.25 秒が足されていた(語尾の余韻が録音から落ちる)。
    """
    after = noise(2000, dbfs=-60)                 # 繰り返さない波形で、どこが入ったかを見分ける
    seg = record(room(1000) + tone(800, dbfs=-20) + after, clock)
    assert seg.stop_reason == "silence"
    step = int(settings.get("vad.frame_ms")) * 16 * 2
    assert after[:step] in seg.pcm, "声の直後の音が録音に入っていない"


def test_a_soft_voice_is_not_cut_until_it_falls_quiet(clock):
    """話し始めのあと小さめの声(＋5〜9dB)が続く間は話し終わりにしない(終わりは低い線で見る)。

    高い線のままだと 0.7 秒で途中終了し、溜めきれない声も録音から落ちる。
    """
    soft = tone(1000, dbfs=-44)
    seg = record(noise(2000, dbfs=-50) + tone(20, dbfs=-40) + soft + noise(3000, dbfs=-50), clock)
    assert seg.stop_reason == "silence"
    assert ms_of(seg.pcm) >= 1000 + 20, "小さめの声の途中で切れている"


def test_soft_voice_does_not_raise_the_noise_floor(clock):
    """話し始めにならなかった小さめの声を暗騒音に入れない(言い直すほど大きな声が要るようにならない)。"""
    almost = tone(60, dbfs=-44) + noise(200, dbfs=-50)                # 声らしいが、＋9dB を越えない
    record(noise(2000, dbfs=-50) + almost * 8 + silence(8000), clock)
    seg = record(noise(1000, dbfs=-50) + (tone(20, dbfs=-40) + tone(60, dbfs=-44)) * 10 + noise(3000, dbfs=-50),
                 FakeClock(int(settings.get("vad.frame_ms"))))
    assert seg.stop_reason == "silence"


def test_a_short_knock_does_not_start_recording(clock):
    """ドア・足音・咳のような一瞬の音では録音を始めない(onset_ms)。"""
    seg = record(noise(1000, dbfs=-55) + tone(60, dbfs=-15) + noise(1000, dbfs=-55) + silence(8000), clock)
    assert seg.stop_reason == "no_speech"


def test_speaking_when_the_window_opens_is_not_taken_as_noise(clock):
    """窓を開けた瞬間にもう話していても、前の窓の暗騒音を覚えていれば声として拾う。

    画面が選択を待つ間は窓を開け直し続けるので、言い直しが窓の頭にかかることがある。
    """
    first = record(noise(3000, dbfs=-55) + silence(8000), clock)
    assert first.stop_reason == "no_speech"
    seg = record(tone(900, dbfs=-20) + noise(3000, dbfs=-55), FakeClock(int(settings.get("vad.frame_ms"))))
    assert seg.stop_reason == "silence"
    assert seg.speech_ms >= 400


def test_noise_floor_is_relearned_after_running_to_the_limit(clock):
    """上限まで声が続いたら、暗騒音を低く見積もっていたかもしれないので次の窓で測り直す。"""
    record(noise(3000, dbfs=-55) + silence(8000), clock)
    assert len(vad._bg_history) > 0
    record(room(500) + tone(5000), FakeClock(int(settings.get("vad.frame_ms"))), max_record_sec=2.0)
    assert len(vad._bg_history) == 0


# ── 終了条件 ──────────────────────────────────────────────────────────────────

def test_no_speech_within_start_timeout(clock):
    """話し始めなければ「発話開始待ち」で終わる(§7 の「音声が検出されない」)。"""
    seg = record(silence(9000), clock)
    assert seg.stop_reason == "no_speech"
    assert seg.speech_ms == 0
    assert seg.pcm == b""


def test_max_record_sec_cuts_long_speech(clock):
    """最大録音時間で打ち切る(§8)。"""
    seg = record(room(500) + tone(12000), clock, max_record_sec=2.0)
    assert seg.stop_reason == "max_duration"
    assert ms_of(seg.pcm) <= 2600


def test_manual_stop_finishes_immediately(clock):
    """「入力を終了」ボタンでそこまでを発話として確定する(§8)。"""
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 60        # 発話が始まってしばらくしたら押す

    seg = record(room(500) + tone(9000), clock, should_stop=should_stop)
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
    record(room(300) + tone(800) + silence(1500), clock,
           on_level=lambda level, db: levels.append(level))
    assert levels, "音量が 1 度も通知されていない"
    assert max(levels) > 0.2, "発話中の音量が上がっていない"
    assert min(levels) < 0.1, "無音時に音量が下がっていない"


def test_speech_start_callback_fires_once(clock):
    """「聞き取り中」へ切り替える合図は、発話を検出したときだけ。"""
    fired = {"n": 0}
    record(room(400) + tone(700) + silence(1500), clock,
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
