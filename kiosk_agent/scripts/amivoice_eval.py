"""AmiVoice API での一文受付の精度計測（クラウド ASR を採るかどうかの判断材料）。

**このスクリプトは音声を端末の外へ送る。** 既定はログを残さないエンドポイント
(`/v1/nolog/recognize`) を使う。同梱の音源 `voice_eval_audio/` は架空の名乗りで、
実在の個人・法人を含まない。実機で録った肉声を投げるときは、それが来訪者の個人情報で
あることを承知したうえで行うこと。

    set AMIVOICE_APPKEY=...             # Windows。マイページで発行した APPKEY
    export AMIVOICE_APPKEY=...          # Raspberry Pi

    # 素 vs 単語登録（担当者を profileWords で渡す）
    .venv/bin/python scripts/amivoice_eval.py

    # ローカル(Vosk 2パス)とも並べる
    .venv/bin/python scripts/amivoice_eval.py --with-local

    # 実機のマイクで3回録って、そのつどローカルと並べる（本番と同じ録音経路）
    .venv/bin/python scripts/amivoice_eval.py --record 3

    # **鍵を端末に置きたくないとき**: 端末では録るだけ。認識は手元でまとめて。
    .venv/bin/python scripts/amivoice_eval.py --record 3 --save ~/rec   # 実機(鍵不要)
    python scripts/amivoice_eval.py --wav rec/*.wav                     # 手元

    # すでに録ってある WAV で比べる
    .venv/bin/python scripts/amivoice_eval.py --wav /dev/shm/s.wav

測るもの: 会社名・氏名・訪問先・用件・アポ有無の正解数 / 往復時間 / 概算費用。

**なぜ単語登録を測るのか。** ローカルで分かったのは「この用途の精度は候補を渡せるか
で決まる」ということ（VOICE_INPUT.md §4-7）。クラウドでも同じはずで、渡せないなら
乗り換える意味は薄い。AmiVoice は `profileWords` でリクエストごとに単語を足せる。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import wave
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
for _p in (str(AGENT_DIR), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402

from voice import extract  # noqa: E402
from voice_eval import CASES_FILE, FIELDS, WAV_DIR, score_case  # noqa: E402

#: ログを残さない方。単価は高い（158.4円/時間 対 99円/時間）が、受付の音声を
#: 預けない形にできる。--log を用意してあるのは、認識結果をマイページで確認したいとき。
ENDPOINT_NOLOG = "https://acp-api.amivoice.com/v1/nolog/recognize"
ENDPOINT_LOG = "https://acp-api.amivoice.com/v1/recognize"
ENGINE = "-a-general"          # 日本語の汎用エンジン
YEN_PER_HOUR = {"nolog": 158.4, "log": 99.0}


def profile_words(staff: list[dict]) -> str:
    """担当者を profileWords の書式にする。

    書式は「表記 読み」を "|" で連ねたもの。値ごと URL エンコードして d に載せる。
    読みが無い人は渡さない（読みを推測してはいけない。VOICE_INPUT.md 2-4）。
    """
    entries = [f"{s['name'].replace(' ', '')} {s['name_kana']}"
               for s in staff if s.get("name") and s.get("name_kana")]
    return "|".join(entries)


def recognize(appkey: str, wav: bytes, *, words: str = "", nolog: bool = True,
              timeout: float = 30.0) -> tuple[dict, float]:
    """1 発話を投げる。(応答, 往復ミリ秒)。

    音声の a は必ず最後に置くこと。後ろに置いたパラメータは無視される仕様なので、
    順番を間違えると認証エラーや認識エラーになる。
    """
    d = f"grammarFileNames={ENGINE}"
    if words:
        d += " profileWords=" + urllib.parse.quote(words, safe="")
    files = [("u", (None, appkey)), ("d", (None, d)),
             ("a", ("audio.wav", wav, "audio/wav"))]
    started = time.monotonic()
    r = httpx.post(ENDPOINT_NOLOG if nolog else ENDPOINT_LOG, files=files, timeout=timeout)
    elapsed = (time.monotonic() - started) * 1000
    r.raise_for_status()
    return r.json(), elapsed


def load_segment(wav_path: Path):
    """WAV を本番と同じ形(16bit モノラル PCM)の AudioSegment にする。"""
    from voice.types import AudioSegment

    with wave.open(str(wav_path), "rb") as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    ms = int(len(pcm) / 2 / rate * 1000)
    return AudioSegment(pcm=pcm, sample_rate=rate, total_ms=ms, speech_ms=ms,
                        stop_reason="manual", peak_db=-12.0, noise_floor_db=-60.0)


def local_from_segment(seg, staff_names: list[str]) -> dict | None:
    """比較用のローカル認識（フリー＋担当者の語彙の2パス目）。使えなければ None。"""
    from voice import vosk_engine

    ok, _ = vosk_engine.available()
    if not ok:
        return None
    started = time.monotonic()
    tr = vosk_engine.transcribe(seg)
    try:
        gtext, sure = vosk_engine.transcribe_vocabulary(seg, staff_names)
    except Exception:
        gtext, sure = "", []
    return {"text": tr.text, "grammar_text": gtext, "sure": sure,
            "ms": (time.monotonic() - started) * 1000}


def local_passes(wav_path: Path, staff_names: list[str]) -> dict | None:
    return local_from_segment(load_segment(wav_path), staff_names)


def compare_one(args, label: str, seg, wav: bytes, book, purposes,
                staff_names: list[str], words: str) -> None:
    """1 発話について ローカル / AmiVoice素 / AmiVoice単語登録 を並べる。

    実機で確かめるとき用。正解が分からないので採点はせず、文字起こしと取り出した
    項目をそのまま出す。判断するのは人。
    """
    print(f"\n── {label} ({seg.total_ms}ms) ──")
    rows: list[tuple[str, str, float]] = []
    blob = local_from_segment(seg, staff_names)
    if blob is not None:
        rows.append(("ローカル Vosk 2パス", blob["text"], blob["ms"]))
    for name, w in (("AmiVoice 素", ""), ("AmiVoice 単語登録", words)):
        if not args.appkey:
            break
        if w and args.no_words:
            continue
        try:
            payload, ms = recognize(args.appkey, wav, words=w, nolog=not args.log)
        except Exception as e:
            print(f"  [{name}] 送れません: {type(e).__name__}")
            continue
        if payload.get("code"):
            print(f"  [{name}] エラー {payload.get('code')} {payload.get('message')}")
            continue
        rows.append((name, str(payload.get("text") or ""), ms))

    for name, text, ms in rows:
        if name.startswith("ローカル") and blob is not None:
            got = extract.extract(text, book, purposes,
                                  grammar_text=blob["grammar_text"], host_tokens=blob["sure"])
        else:
            got = extract.extract(text, book, purposes)
        print(f"  [{name}] {ms:.0f}ms")
        print(f"      {text}")
        print(f"      会社={got.visitor_company} 氏名={got.visitor_name}"
              f" 訪問先={got.host_candidates} 用件={got.purpose} アポ={got.has_appointment}")


def tally(name: str, rows: list[dict]) -> None:
    """1 方式ぶんの集計。"""
    if not rows:
        return
    n = len(rows)
    hits = {f: sum(1 for r in rows if r["score"]["hit"][f]) for f in FIELDS}
    host_in = sum(1 for r in rows if r["host_ok"])
    invented = sum(len(r["score"]["invented"]) for r in rows)
    ms = [r["ms"] for r in rows if r["ms"]]
    print(f"\n[{name}]  件数 {n}")
    print("  " + " / ".join(f"{f.replace('visitor_', '')} {hits[f]}/{n}" for f in FIELDS))
    print(f"  訪問先が候補に出た {host_in}/{n} / null に値を入れた(生成) {invented}")
    if ms:
        print(f"  時間 中央値 {statistics.median(ms):.0f}ms / 最大 {max(ms):.0f}ms")


def audio_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appkey", default=os.environ.get("AMIVOICE_APPKEY", ""),
                    help="既定は環境変数 AMIVOICE_APPKEY")
    ap.add_argument("--wav", type=Path, nargs="+",
                    help="この WAV を比べる（採点はしない。複数可）")
    ap.add_argument("--record", type=int, metavar="N",
                    help="実機のマイクから N 回録って比べる（本番と同じ録音経路）")
    ap.add_argument("--save", type=Path, metavar="DIR",
                    help="録った音を WAV で残す。鍵を端末に置かず、手元でまとめて"
                         "認識にかけるときに使う（音声が残るので、済んだら消すこと）")
    ap.add_argument("--log", action="store_true",
                    help="ログを残すエンドポイントを使う（マイページで確認したいとき）")
    ap.add_argument("--with-local", action="store_true", help="ローカル Vosk とも並べる")
    ap.add_argument("--no-words", action="store_true", help="単語登録なしだけ測る")
    ap.add_argument("--show-text", action="store_true", help="文字起こしを出す")
    ap.add_argument("--local-only", action="store_true",
                    help="通信しない。ローカルの基準値だけ出す（鍵を取る前の下ごしらえ）")
    args = ap.parse_args()

    if args.local_only:
        args.with_local, args.appkey = True, args.appkey or "-"
    # 録るだけなら鍵は要らない。発売済みの端末すべてに鍵を置いて回るのは現実的で
    # ないので、「端末は録音だけ・認識は手元で」を最初から通る道にしておく。
    if args.record and not args.appkey:
        print("APPKEY が無いので、録音とローカル認識だけ行います"
              "（AmiVoice には送りません）。")
        if not args.save:
            args.save = Path.home() / "mokuture-voice-rec"
        args.appkey = ""
    elif not args.appkey:
        print("APPKEY がありません。AmiVoice のマイページで発行し、環境変数"
              " AMIVOICE_APPKEY に入れてください。")
        return 2

    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    staff_master, purposes = data["staff_master"], data["purposes"]
    words = profile_words(staff_master)
    staff_names = [s["name"] for s in staff_master]
    book = extract.build_staff(staff_names)

    if args.local_only or not args.appkey:
        print("通信しません。ローカルの認識だけ行います。")
    else:
        print(f"エンドポイント: {'ログあり' if args.log else 'ログなし'} / エンジン {ENGINE}")
        print(f"単語登録: {len(words.split('|')) if words else 0} 件")
        print("※ 音声を外部へ送ります。")

    if args.record:
        from voice import capture
        from voice_bench import level_report, record

        print("\n実機のマイクで録ります。一文で名乗ってください。")
        print("例:「磯野木工所の荒木と申します。服部様と打ち合わせのお約束で参りました」")
        saved = []
        for i in range(args.record):
            seg = record(None)
            level_report(seg)
            wav = capture.to_wav(seg.pcm, seg.sample_rate)
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                out = args.save / f"{time.strftime('%Y%m%d-%H%M%S')}-{i + 1}.wav"
                out.write_bytes(wav)
                saved.append(out)
            compare_one(args, f"{i + 1}回目", seg, wav, book, purposes, staff_names, words)
            seg.clear()
        if saved:
            print(f"\n保存しました: {args.save}")
            print("手元へ持っていって、まとめて比べられます:")
            print("  scp 'mokuture@<この端末>:" + str(args.save) + "/*.wav' .")
            print("  python scripts/amivoice_eval.py --wav *.wav")
            print("**音声が残っています。済んだら消してください。**")
        return 0

    if args.wav:
        for path in args.wav:
            seg = load_segment(path)
            compare_one(args, path.name, seg, path.read_bytes(),
                        book, purposes, staff_names, words)
            seg.clear()
        return 0

    runs: dict[str, list[dict]] = {}
    seconds = 0.0
    calls = 0
    for case in data["cases"]:
        path = WAV_DIR / f"{case['id']}.wav"
        if not path.is_file():
            print(f"  音源がありません: {path.name}"
                  "（scripts/voice_eval.py --synth か --record で作れます）")
            continue
        wav = path.read_bytes()
        seconds += audio_seconds(path)
        want_host = case["expect"].get("host_name_spoken")

        variants: list[tuple[str, str | None]] = []
        if not args.local_only:
            variants.append(("AmiVoice 素", ""))
            if not args.no_words:
                variants.append(("AmiVoice 単語登録", words))
        if args.with_local:
            variants.append(("ローカル Vosk 2パス", None))

        for label, w in variants:
            if w is None:
                blob = local_passes(path, staff_names)
                if blob is None:
                    continue
                text, ms = blob["text"], blob["ms"]
                got = extract.extract(text, book, purposes,
                                      grammar_text=blob["grammar_text"],
                                      host_tokens=blob["sure"])
            else:
                payload, ms = recognize(args.appkey, wav, words=w, nolog=not args.log)
                calls += 1
                if payload.get("code"):
                    print(f"  {case['id']}: エラー {payload.get('code')} {payload.get('message')}")
                    continue
                text = str(payload.get("text") or "")
                got = extract.extract(text, book, purposes)

            score = score_case(case, got.as_dict(), text, staff_master)
            # 訪問先は「候補に出たか」で見る。同姓がいると 1 人に絞らないのが正しい
            # 動きなので、絞れたかどうかとは別に数える。
            host_ok = ((not got.host_candidates) if not want_host else
                       any(want_host in n.replace(" ", "") for n in got.host_candidates))
            runs.setdefault(label, []).append({"score": score, "ms": ms, "host_ok": host_ok})
            if args.show_text:
                print(f"  {case['id']:11} [{label}] {text}")

    for label, rows in runs.items():
        tally(label, rows)

    rate = YEN_PER_HOUR["log" if args.log else "nolog"]
    if calls:
        print(f"\n概算費用: 音声 {seconds:.1f}秒 を {calls} 回 = "
              f"{seconds * calls / max(1, len(runs)) * rate / 3600:.2f}円"
              f"（{rate}円/時間・発話時間のみ課金）")
    print(f"受付 1 人 10 秒として、50人/日・22日なら月 {10 * 50 * 22 * rate / 3600:.0f}円/拠点。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
