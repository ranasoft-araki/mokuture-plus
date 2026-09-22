"""実機(Raspberry Pi)での音声認識の性能計測(§3-1・§12)。

    # マイクから 1 回録って、一文の名乗りで使うエンジンを測る
    .venv/bin/python scripts/voice_bench.py --models vosk --field reception

    # whisper と比べる
    .venv/bin/python scripts/voice_bench.py --models vosk,base,small --field reception

    # 同じ音声で何度も測る(ばらつきを見る)
    .venv/bin/python scripts/voice_bench.py --wav /dev/shm/sample.wav --repeat 5

    # 録音だけして WAV に残す(比較用の音源を作る。計測が終わったら消すこと)
    .venv/bin/python scripts/voice_bench.py --record-only --out /dev/shm/sample.wav

測るもの:
    入力レベル(発話・暗騒音・S/N・割れ) / 音声の長さ / 認識処理時間 /
    発話終了から結果が出るまでの時間 / 使用モデル /
    認識成功・再入力・キャンセルの別(ここでは自動判定の可否として出す)

**精度が出ないときは、まず入力レベルを見る。** 認識器を替える前に、音が小さい
(alsamixer でマイクの入力が上がっていない)・割れている・暗騒音に埋もれている、の
どれかであることが多い。

**認識したテキストは既定では表示しない。** 精度を目で確かめたいときだけ
`--show-text` を付ける(画面に出るだけで、どこにも保存しない)。
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from array import array
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from voice import capture, quality, settings, textnorm, vad, vosk_engine, whisper_cpp  # noqa: E402
from voice.types import AudioSegment  # noqa: E402

#: 測れるもの。whisper はモデルの大きさ違い、vosk は別エンジン。
MODELS = {
    "base":  ("voice_models/ggml-base-q5_1.bin", "whisper-base-q5"),
    "small": ("voice_models/ggml-small-q5_1.bin", "whisper-small-q5"),
    "vosk":  (None, "vosk-small-ja-0.22"),
}
#: 受付で人が黙って待てる上限。これを超えるなら画面の案内だけでは間が持たない。
TARGET_SEC = 3.0


def machine() -> str:
    """実機を取り違えて比べないように、機械の素性を出しておく。"""
    bits = []
    model = Path("/proc/device-tree/model")
    if model.exists():
        bits.append(model.read_text(errors="ignore").strip("\x00").strip())
    else:
        import platform
        bits.append(f"{platform.system()} {platform.machine()}")
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                bits.append(f"メモリ {int(line.split()[1]) / 1024 / 1024:.1f}GB")
                break
    except OSError:
        pass
    import os
    bits.append(f"{os.cpu_count()} コア")
    return " / ".join(bits)


def rss_mb() -> float | None:
    """いまのプロセスが使っているメモリ(MB)。Pi 4 は 4GB しかないので見ておく。"""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def sample_peak(pcm: bytes) -> tuple[float, float]:
    """(最大振幅 dBFS, 割れた標本の割合)。フレーム RMS では割れを見落とすので別に見る。"""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return -100.0, 0.0
    peak = max(abs(s) for s in samples)
    clipped = sum(1 for s in samples if abs(s) >= 32000) / len(samples)
    db = 20.0 * math.log10(peak / 32768.0) if peak else -100.0
    return db, clipped


def measure(pcm: bytes, rate: int) -> tuple[float, float]:
    """(発話のピーク, 暗騒音) を 20ms フレームの RMS から推定する。WAV 用。"""
    step = max(2, int(rate * 0.02) * 2)
    frames = [vad.dbfs(pcm[i:i + step]) for i in range(0, max(0, len(pcm) - step), step)]
    if not frames:
        return -100.0, -100.0
    ordered = sorted(frames)
    return ordered[-1], ordered[len(ordered) // 10]      # 下位 10% を暗騒音の目安に


def level_report(seg: AudioSegment) -> None:
    """入力レベルの講評。精度が出ない原因はたいていここで分かる。

    目安(16bit PCM):
      発話のピーク  -18〜-6 dBFS   小さすぎると子音が量子化で潰れる
      暗騒音        -50 dBFS 以下  これより大きいとロビーの環境音に埋もれる
      S/N           20dB 以上ほしい
    """
    peak_db, clipped = sample_peak(seg.pcm)
    snr = seg.peak_db - seg.noise_floor_db
    print(f"  レベル: 発話 {seg.peak_db:.1f}dBFS / 暗騒音 {seg.noise_floor_db:.1f}dBFS"
          f" / S/N {snr:.1f}dB / 最大振幅 {peak_db:.1f}dBFS / 割れ {clipped * 100:.2f}%")
    notes = []
    if clipped > 0.001 or peak_db > -1.0:
        notes.append("割れています。alsamixer でマイクの入力を下げてください")
    if seg.peak_db < -30.0:
        notes.append("小さすぎます。alsamixer(F4 で Capture)でマイクの入力を上げてください。"
                     "それでも足りなければ voice_input.yaml の audio.input_gain")
    if snr < 15.0:
        notes.append("S/N が足りません。マイクを話者へ近づける・向きを変える・"
                     "暗騒音(空調やスピーカー)を下げる")
    for n in notes:
        print(f"  ※ {n}")
    if not notes:
        print("  → レベルは妥当です。精度の原因はここではありません")


def record(seconds: float | None) -> AudioSegment:
    """マイクから 1 項目ぶん録る。VAD の終了条件は本番と同じ。"""
    ok, detail = capture.available()
    if not ok:
        print(f"マイクを使えません: {detail}")
        sys.exit(1)
    print("開始音の代わりに 1 秒待ちます。ピッと鳴ったつもりで話し始めてください…")
    time.sleep(1.0)
    stream = capture.open_stream()
    print("録音中(話し終えて黙ると自動で止まります)")
    try:
        seg = vad.record_utterance(stream, max_record_sec=seconds or None)
    finally:
        stream.close()
    print(f"  音声 {seg.total_ms}ms / うち発話 {seg.speech_ms}ms / 終了理由 {seg.stop_reason}")
    if seg.speech_ms <= 0:
        print("  発話を検出できませんでした")
        sys.exit(1)
    return seg


def load_wav(path: Path) -> AudioSegment:
    import wave
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            print("16bit モノラルの WAV を指定してください")
            sys.exit(1)
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    ms = int(len(pcm) / 2 / rate * 1000)
    peak_db, floor_db = measure(pcm, rate)
    return AudioSegment(pcm=pcm, sample_rate=rate, total_ms=ms, speech_ms=ms,
                        stop_reason="manual", peak_db=peak_db, noise_floor_db=floor_db)


def run_model(key: str, seg: AudioSegment, repeat: int, field: str, show_text: bool) -> None:
    rel, name = MODELS[key]
    cfg = settings.cfg()
    if key == "vosk":
        engine = vosk_engine
        head = f"\n[{key}] {name}"
    else:
        engine = whisper_cpp
        cfg["whisper"]["model_path"] = rel
        cfg["whisper"]["model_name"] = name
        head = f"\n[{key}] {name}  threads={cfg['whisper']['threads']}"

    ok, detail = engine.available()
    if not ok:
        print(f"\n[{key}] 使えません: {detail}")
        return

    # モデルの読み込みは 1 回だけ。**この時間は待ち時間に入らない**(常駐中に済む)。
    before = rss_mb()
    started = time.monotonic()
    engine.warmup()
    load_ms = int((time.monotonic() - started) * 1000)
    after = rss_mb()
    print(head)
    mem = f" / モデルで +{after - before:.0f}MB" if (after and before) else ""
    print(f"  モデル読み込み {load_ms}ms（常駐中に済むので待ち時間には入らない）{mem}")

    times: list[int] = []
    for i in range(repeat):
        started = time.monotonic()
        try:
            tr = engine.transcribe(seg)
        except whisper_cpp.EngineTimeout:
            print(f"  {i + 1}/{repeat}: タイムアウト")
            continue
        except Exception as e:
            print(f"  {i + 1}/{repeat}: 失敗 ({type(e).__name__})")
            continue
        end_to_display = int((time.monotonic() - started) * 1000)
        times.append(tr.recognition_ms)
        normalized = textnorm.normalize(field, tr.text)
        verdict = quality.judge(seg, tr, normalized)
        prob = f"{tr.avg_token_prob:.2f}" if tr.avg_token_prob is not None else "—"
        state = "成功" if verdict.accepted else f"再入力({verdict.code})"
        print(f"  {i + 1}/{repeat}: 認識 {tr.recognition_ms}ms / 表示まで {end_to_display}ms"
              f" / 平均確率 {prob} / {state}")
        if show_text:
            print(f"        認識: {normalized}")

    if times:
        rtf = statistics.median(times) / max(1, seg.total_ms)
        worst = max(times) / 1000
        print(f"  中央値 {int(statistics.median(times))}ms"
              f" / 最小 {min(times)}ms / 最大 {max(times)}ms"
              f" / RTF {rtf:.2f}(音声長に対する処理時間の比)")
        # 1 回目だけ大きく遅いことがある(Vosk は実測で 4.7秒 → 0.7秒)。
        # 平均に混ぜると実態を見誤るので、分けて出す。
        if len(times) >= 2 and times[0] > statistics.median(times[1:]) * 2:
            rest = statistics.median(times[1:])
            print(f"  ※ 1 回目だけ {times[0]}ms、2 回目以降は中央値 {int(rest)}ms。"
                  "サービス起動後の最初の 1 人だけが余分に待ちます")
            worst = max(times[1:]) / 1000
        if worst <= TARGET_SEC:
            print(f"  → 実用的です（最悪でも {worst:.1f} 秒）")
        elif worst <= TARGET_SEC * 2:
            print(f"  → 待たされます（最悪 {worst:.1f} 秒）。画面の案内でごまかせる範囲の上限")
        else:
            print(f"  → 受付には遅すぎます（最悪 {worst:.1f} 秒）")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="vosk",
                    help="比較するモデル(vosk,base,small)。既定は一文の名乗りで使う vosk")
    ap.add_argument("--wav", type=Path, help="録音の代わりに使う WAV(16bit モノラル)")
    ap.add_argument("--seconds", type=float, default=None, help="最大録音時間(秒)")
    ap.add_argument("--repeat", type=int, default=3, help="同じ音声で繰り返す回数")
    ap.add_argument("--field", default="reception",
                    choices=("reception", "company", "person_name", "staff"),
                    help="どの項目として整形・判定するか。既定は受付の入口の一文")
    ap.add_argument("--record-only", action="store_true", help="録音して WAV に保存するだけ")
    ap.add_argument("--out", type=Path, help="--record-only の保存先")
    ap.add_argument("--show-text", action="store_true",
                    help="認識結果を画面に出す(保存はしない。精度確認用)")
    args = ap.parse_args()

    if args.record_only:
        seg = record(args.seconds)
        level_report(seg)
        out = args.out or Path("/dev/shm/voice-bench.wav")
        out.write_bytes(capture.to_wav(seg.pcm, seg.sample_rate))
        print(f"保存しました: {out}  (計測が終わったら消してください)")
        seg.clear()
        return 0

    seg = load_wav(args.wav) if args.wav else record(args.seconds)
    level_report(seg)
    keys = [k.strip() for k in args.models.split(",") if k.strip()]
    unknown = [k for k in keys if k not in MODELS]
    if unknown:
        print(f"不明なモデル: {', '.join(unknown)}  (使えるのは {', '.join(MODELS)})")
        return 2

    print(f"\n機械: {machine()}")
    print(f"音声 {seg.total_ms}ms / 発話 {seg.speech_ms}ms"
          f" / 目標は話し終わってから {TARGET_SEC:.0f} 秒以内")
    try:
        for key in keys:
            run_model(key, seg, args.repeat, args.field, args.show_text)
    finally:
        # 計測が終わったら音声は捨てる(§11)
        seg.clear()
    print("\n注意: この結果は端末の負荷状況で変わります。キオスクの通常運用中に"
          "測ると本番に近い値になります。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
