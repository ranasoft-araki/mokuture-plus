"""Raspberry Pi 5 での音声認識の性能計測(§3-1・§12)。

    # マイクから 1 回録って、base と small で比べる
    .venv/bin/python scripts/voice_bench.py --models base,small

    # 同じ音声で何度も測る(ばらつきを見る)
    .venv/bin/python scripts/voice_bench.py --wav /dev/shm/sample.wav --repeat 5

    # 録音だけして WAV に残す(比較用の音源を作る。計測が終わったら消すこと)
    .venv/bin/python scripts/voice_bench.py --record-only --out /dev/shm/sample.wav

測るもの:
    音声の長さ / 認識処理時間 / 発話終了から結果が出るまでの時間 / 使用モデル /
    認識成功・再入力・キャンセルの別(ここでは自動判定の可否として出す)

**認識したテキストは既定では表示しない。** 精度を目で確かめたいときだけ
`--show-text` を付ける(画面に出るだけで、どこにも保存しない)。
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from voice import capture, quality, settings, textnorm, vad, whisper_cpp  # noqa: E402
from voice.types import AudioSegment  # noqa: E402

MODELS = {
    "base":  ("voice_models/ggml-base-q5_1.bin", "whisper-base-q5"),
    "small": ("voice_models/ggml-small-q5_1.bin", "whisper-small-q5"),
}


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
    return AudioSegment(pcm=pcm, sample_rate=rate, total_ms=ms, speech_ms=ms,
                        stop_reason="manual", peak_db=0.0, noise_floor_db=-60.0)


def run_model(key: str, seg: AudioSegment, repeat: int, field: str, show_text: bool) -> None:
    rel, name = MODELS[key]
    cfg = settings.cfg()
    cfg["whisper"]["model_path"] = rel
    cfg["whisper"]["model_name"] = name

    ok, detail = whisper_cpp.available()
    if not ok:
        print(f"\n[{key}] 使えません: {detail}")
        return

    print(f"\n[{key}] {name}  threads={cfg['whisper']['threads']}")
    times: list[int] = []
    for i in range(repeat):
        started = time.monotonic()
        try:
            tr = whisper_cpp.transcribe(seg)
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
        print(f"  中央値 {int(statistics.median(times))}ms"
              f" / 最小 {min(times)}ms / 最大 {max(times)}ms"
              f" / RTF {rtf:.2f}(音声長に対する処理時間の比)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="base", help="比較するモデル(base,small)")
    ap.add_argument("--wav", type=Path, help="録音の代わりに使う WAV(16bit モノラル)")
    ap.add_argument("--seconds", type=float, default=None, help="最大録音時間(秒)")
    ap.add_argument("--repeat", type=int, default=3, help="同じ音声で繰り返す回数")
    ap.add_argument("--field", default="company", choices=("company", "person_name", "staff"),
                    help="どの項目として整形・判定するか")
    ap.add_argument("--record-only", action="store_true", help="録音して WAV に保存するだけ")
    ap.add_argument("--out", type=Path, help="--record-only の保存先")
    ap.add_argument("--show-text", action="store_true",
                    help="認識結果を画面に出す(保存はしない。精度確認用)")
    args = ap.parse_args()

    if args.record_only:
        seg = record(args.seconds)
        out = args.out or Path("/dev/shm/voice-bench.wav")
        out.write_bytes(capture.to_wav(seg.pcm, seg.sample_rate))
        print(f"保存しました: {out}  (計測が終わったら消してください)")
        seg.clear()
        return 0

    seg = load_wav(args.wav) if args.wav else record(args.seconds)
    keys = [k.strip() for k in args.models.split(",") if k.strip()]
    unknown = [k for k in keys if k not in MODELS]
    if unknown:
        print(f"不明なモデル: {', '.join(unknown)}  (使えるのは {', '.join(MODELS)})")
        return 2

    print(f"\n音声 {seg.total_ms}ms / 発話 {seg.speech_ms}ms")
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
