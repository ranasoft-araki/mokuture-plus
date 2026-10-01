"""声で操作するの実地試験（実際の声・実際のマイクで、言葉ごとの当たり方と音量を測る）。

画面の案内に従って言葉を順に話すと、1 回ごとに**本番と同じ経路**(VAD → 画面の語彙で
Vosk → どの選択肢か)を通した結果と、マイクに入った音の大きさを表示する。最後に言葉ごとの
まとめを出す。Windows 開発機でも Raspberry Pi でも動く。

    # ふつうの距離で、全部の言葉を 2 回ずつ
    .venv/Scripts/python scripts/voice_fieldtest.py --distance 60cm

    # 苦手な言葉だけ 5 回ずつ / 離れて
    .venv/Scripts/python scripts/voice_fieldtest.py --words いいえ,ロッカー --reps 5 --distance 1m

    # 録っておいた試験をあとから設定を変えて測り直す(マイク不要)
    .venv/Scripts/python scripts/voice_command_eval.py --no-say --wav-dir <保存先>

**録音は、試験した人の声を解析するためだけに手元へ保存する**(既定 ~/mokuture-voice-test/日時/。
`--no-save` で保存しない)。保存するのはこの試験の録音だけで、キオスクの音声サービスは
これまでどおり何も保存しない。ファイル名は voice_command_eval.py の `--wav-dir` の規則
(`画面__語彙のキー__印.wav`)に合わせてある。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from voice import capture, settings, vad, vosk_engine  # noqa: E402
import voice_command_eval as ev  # noqa: E402

# (画面, 語彙のキー)。言う言葉は VOICE_VOCAB の札(label)。
ITEMS = [
    ("top", "top.visit"), ("top", "top.delivery"), ("top", "top.locker"),
    ("lockerMode", "lockerMode.store"), ("lockerMode", "lockerMode.pickup"), ("lockerMode", "common.back"),
    ("locker", "locker.n1"), ("locker", "locker.n2"), ("locker", "locker.n3"),
    ("confirm", "confirm.yes"), ("confirm", "confirm.no"),
    ("welcome", "welcome.form"),
]


def frame_dbs(pcm: bytes, rate: int, *, skip_zero: bool = False) -> list[float]:
    """20ms ごとの音量。skip_zero は 0 埋め(中身が全部 0)のコマを除く(VAD と同じ見方)。"""
    step = int(rate * 0.02) * 2
    frames = (pcm[i:i + step] for i in range(0, len(pcm) - step + 1, step))
    return [vad.dbfs(f) for f in frames if not skip_zero or f.strip(bytes(1))]


def pct(values: list[float], p: float) -> float:
    if not values:
        return -100.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round((len(s) - 1) * p)))]


def record(seconds: float) -> bytes:
    """マイクから seconds 秒そのまま録る(VAD は後で同じ音に本番のまま掛ける)。"""
    rate = int(settings.get("audio.sample_rate"))
    want = int(rate * seconds) * capture.SAMPLE_WIDTH
    stream = capture.open_stream()
    got = bytearray()
    try:
        deadline = time.monotonic() + seconds + 3.0
        while len(got) < want and time.monotonic() < deadline:
            chunk = stream.read(min(3200, want - len(got)), timeout=0.5)
            if chunk:
                got.extend(chunk)
    finally:
        stream.close()
    return bytes(got)


def run_vad(pcm: bytes, rate: int):
    """録った音に本番の VAD を掛ける(時計は流した音の長さ)。"""
    stream = capture.BufferStream(pcm, loop_silence=False, realtime=False, sample_rate=rate)
    clock = lambda: stream._delivered / (rate * capture.SAMPLE_WIDTH)  # noqa: E731,SLF001
    ccfg = settings.get("command")
    mark: dict = {}
    seg = vad.record_utterance(stream, max_record_sec=float(ccfg["max_record_sec"]),
                               silence_sec=float(ccfg["silence_sec"]),
                               start_timeout_sec=len(pcm) / (rate * 2), now=clock,
                               on_speech_start=lambda: mark.setdefault("t", clock()))
    return seg, mark.get("t")


def save_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distance", default="", help="記録に残す距離の印(例: 30cm / 60cm / 1m)")
    ap.add_argument("--reps", type=int, default=2, help="1 つの言葉を何回言うか(既定 2)")
    ap.add_argument("--words", default="", help="試す札の言葉をカンマ区切りで(既定は全部)")
    ap.add_argument("--window", type=float, default=4.0, help="1 回の聞き取りの秒数(既定 4)")
    ap.add_argument("--device", default="", help="録音デバイス(voice_input.yaml の audio.device と同じ書き方)")
    ap.add_argument("--gain", type=float, default=0.0, help="入力の利得(既定は設定値)")
    ap.add_argument("--out", type=Path, default=None, help="保存先(既定 ~/mokuture-voice-test/日時)")
    ap.add_argument("--no-save", action="store_true", help="録音を保存しない")
    args = ap.parse_args()

    cfg = settings.cfg()
    if args.device:
        cfg["audio"]["device"] = args.device
    if args.gain > 0:
        cfg["audio"]["input_gain"] = args.gain
    rate = int(settings.get("audio.sample_rate"))
    gain = float(settings.get("audio.input_gain"))

    mic_ok, mic_detail = capture.available()
    if not mic_ok:
        print("マイクを使えません:", mic_detail)
        return 1
    ok, detail = vosk_engine.available()
    if not ok or not vosk_engine.grammar_supported():
        print("Vosk を使えません:", detail)
        return 1
    print(f"マイク: {mic_detail} / 入力の利得 {gain}")
    vosk_engine.load()
    vocab = ev.load_vocab()

    wanted = [w for w in args.words.split(",") if w]
    items = [(s, k) for s, k in ITEMS if k in vocab and (not wanted or vocab[k]["label"] in wanted)]
    if not items:
        print("試す言葉がありません。--words には札の言葉(いいえ・ロッカー 等)を書いてください")
        return 2

    out = None
    if not args.no_save:
        out = args.out or Path.home() / "mokuture-voice-test" / datetime.now().strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        print(f"録音は解析のため {out} に保存します(--no-save で保存しない)")
    tag = (args.distance or "d").replace("_", "-")

    # 1) 周りの音
    print("\n== 周りの音を測ります。3 秒間、話さずにお待ちください ==")
    amb_raw = record(3.0)
    # 増幅は音量の表示にだけ使う。VAD は自分で audio.input_gain を掛け、保存する録音は生のまま
    # (voice_command_eval.py で測り直すときも VAD が同じ増幅を掛けるので、二重にしない)。
    amb = capture.apply_gain(amb_raw, gain) if gain != 1.0 else amb_raw
    adb = [max(d, -100.0) for d in frame_dbs(amb, rate, skip_zero=True)]
    room = {"median": pct(adb, 0.5), "p10": pct(adb, 0.1), "p90": pct(adb, 0.9)}
    print(f"   周りの音 中央値 {room['median']:.1f} dBFS(静かな 1 割 {room['p10']:.1f} / うるさい 1 割 {room['p90']:.1f})")
    if out:
        save_wav(out / f"neg__room__{tag}.wav", amb_raw, rate)

    # 2) 言葉ごと
    results = []
    total = len(items) * args.reps
    n = 0
    for rep in range(args.reps):
        for screen, key in items:
            n += 1
            label = vocab[key]["label"]
            choices = ev.choices_for(screen, vocab)
            want = ev.wire_id(key)
            print(f"\n[{n}/{total}] 画面「{screen}」  ▶ 「{label}」と言ってください(いまから {args.window:.0f} 秒聞きます)")
            time.sleep(0.3)
            raw = record(args.window)
            pcm = capture.apply_gain(raw, gain) if gain != 1.0 else raw      # 表示用
            seg, t0 = run_vad(raw, rate)                                      # VAD が利得を掛ける
            fdb = frame_dbs(pcm, rate)
            peak = pct(fdb, 0.98)
            row = {"screen": screen, "key": key, "label": label, "rep": rep + 1, "distance": args.distance,
                   "room_db": round(room["median"], 1), "peak_db": round(peak, 1),
                   "vad_floor_db": seg.noise_floor_db, "stop": seg.stop_reason,
                   "start_sec": None if t0 is None else round(t0, 2),
                   "segment_sec": round(len(seg.pcm) / (rate * 2), 2)}
            if seg.stop_reason == "no_speech" or seg.speech_ms <= 0:
                row.update(result="no_speech", matched=None, conf=None, reason="no_speech", words=[])
                print(f"   × 声を拾えませんでした(声の大きさ {peak:.1f} dBFS・周りより {peak - room['median']:+.1f} dB)")
            else:
                m = vosk_engine.recognize_command(seg, choices, fallback=(screen == "locker"))
                words = [(w[0], round(w[1], 2)) for w in m.words]
                res = "hit" if m.matched == want else ("wrong" if m.matched else "miss")
                row.update(result=res, matched=m.matched, conf=m.confidence, reason=m.reason, words=words)
                mark = {"hit": "○ 当たり", "wrong": f"× 取り違え({m.matched})", "miss": f"△ 外れ({m.reason})"}[res]
                print(f"   {mark}  聞こえた語 {words}")
                print(f"   声の大きさ {peak:.1f} dBFS(周りより {peak - room['median']:+.1f} dB)/ 録音の開始 {row['start_sec']} 秒・長さ {row['segment_sec']} 秒・{seg.stop_reason}")
            results.append(row)
            if out:
                save_wav(out / f"{screen}__{key}__{tag}_{rep + 1}.wav", raw, rate)
            seg.clear()

    # 3) まとめ
    print("\n== まとめ ==")
    print(f"{'言葉':<10}{'当たり':>6}{'外れ':>6}{'取違え':>6}{'拾えず':>6}   声の大きさ(周りとの差)")
    by: dict[str, list] = {}
    for r in results:
        by.setdefault(r["label"], []).append(r)
    for label, rs in by.items():
        c = {k: sum(1 for r in rs if r["result"] == k) for k in ("hit", "miss", "wrong", "no_speech")}
        lv = statistics.median(r["peak_db"] for r in rs)
        print(f"{label:<10}{c['hit']:>6}{c['miss']:>6}{c['wrong']:>6}{c['no_speech']:>6}   {lv:.1f} dBFS({lv - room['median']:+.1f} dB)")
    hits = sum(1 for r in results if r["result"] == "hit")
    print(f"計 {hits}/{len(results)}")
    if out:
        with open(out / "results.jsonl", "a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n録音と結果: {out}")
        print("   (試験した人の声です。解析が済んだらフォルダごと消してください)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
