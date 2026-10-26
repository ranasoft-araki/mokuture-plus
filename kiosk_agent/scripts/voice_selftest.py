"""声で操作するの動作試験（Windows 開発機でも Raspberry Pi でも動く）。

録音 → VAD → 画面の語彙で Vosk → どの選択肢か、まで**本番と同じ経路**を 1 回通して
結果を表示する。サービスを起動しなくても、ここだけで中身を確かめられる。

    # 状態を見る（マイク・Vosk・語彙を絞れるモデルか）
    .venv/Scripts/python scripts/voice_selftest.py --status

    # 入力デバイスの一覧（voice_input.yaml の audio.device に書く値）
    .venv/Scripts/python scripts/voice_selftest.py --devices

    # マイクに向かって 1 回話す（語彙は kiosk.html の画面ごとの語彙。既定はご用件の画面）
    .venv/Scripts/python scripts/voice_selftest.py --mic --screen top

    # 合成音声で 1 回（Windows のみ。マイク不要）/ 手元の WAV で 1 回
    .venv/Scripts/python scripts/voice_selftest.py --say "ロッカー" --screen top
    .venv/Scripts/python scripts/voice_selftest.py --wav sample.wav --screen lockerMode

    # 英語語彙で試す(表示言語を英語に切り替えたときと同じ経路)
    .venv/Scripts/python scripts/voice_selftest.py --say "locker" --screen top --lang en
    .venv/Scripts/python scripts/voice_selftest.py --mic --screen top --lang en

聞こえた語は画面に出すだけで、どこにも保存しない。多数の発話でまとめて当たり方を
測るのは scripts/voice_command_eval.py。
"""
from __future__ import annotations

import argparse
import platform
import sys
import tempfile
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from voice import capture, settings, vad, vosk_engine  # noqa: E402
from voice.api import command_available  # noqa: E402
import voice_command_eval as ev  # noqa: E402


def show_status() -> bool:
    print("== 声で操作する の状態 ==")
    print(f"  OS            : {platform.system()} {platform.machine()}")
    mic_ok, mic_detail = capture.available()
    print(f"  マイク        : {'OK' if mic_ok else 'NG'}  {mic_detail}")
    ok, detail = vosk_engine.available()
    print(f"  Vosk(ja)      : {'OK' if ok else 'NG'}  {detail}")
    cmd_ok, cmd_detail = command_available()
    print(f"  語彙を絞れるか(ja): {'OK' if cmd_ok else 'NG'}  {cmd_detail}")
    ok_en, detail_en = vosk_engine.available("en")
    print(f"  Vosk(en)      : {'OK' if ok_en else 'NG'}  {detail_en}")
    if ok_en:
        cmd_ok_en, cmd_detail_en = command_available("en")
        print(f"  語彙を絞れるか(en): {'OK' if cmd_ok_en else 'NG'}  {cmd_detail_en}")
    notes = settings.notes()
    if notes:
        print(f"  設定          : {' / '.join(notes)}")
    return mic_ok and cmd_ok


def show_devices() -> None:
    print("入力デバイス（voice_input.yaml の audio.device に書く値）:")
    for d in capture.list_devices():
        print(f"   {d}")


def run_once(screen: str, source: str, wav: Path | None, lang: str = "ja") -> int:
    vocab = ev.load_vocab()
    if screen not in ev.SCREENS:
        print(f"画面 {screen} の語彙はありません。使える画面: {', '.join(ev.SCREENS)}")
        return 2
    choices = ev.choices_for(screen, vocab, lang)
    words = " / ".join(f"{cid}: {'・'.join(ps)}" for cid, ps in choices)
    print(f"== 画面 {screen} の語彙(lang={lang}) ==\n  {words}")

    cfg = settings.cfg()
    if source == "file":
        cfg["audio"]["backend"] = "file"
        cfg["audio"]["file_path"] = str(wav)
        cfg["audio"]["start_guard_ms"] = 0
    ok, detail = capture.available()
    if not ok:
        print(f"マイク/音源を使えません: {detail}")
        return 1
    vosk_engine.load(lang)
    ccfg = settings.get("command")
    print("\nお話しください…" if source == "mic" else "\n音源を流しています…", flush=True)
    stream = capture.open_stream()
    try:
        seg = vad.record_utterance(stream, max_record_sec=float(ccfg["max_record_sec"]),
                                   silence_sec=float(ccfg["silence_sec"]),
                                   start_timeout_sec=float(ccfg["window_sec"]))
    finally:
        stream.close()
    if seg.stop_reason == "no_speech" or seg.speech_ms <= 0:
        print("  お声を聞き取れませんでした（窓のあいだに話し始めていない）")
        return 1
    started = time.monotonic()
    m = vosk_engine.recognize_command(seg, choices, lang=lang, fallback=screen.startswith("locker"))
    print(f"  音声 {seg.total_ms}ms / うち発話 {seg.speech_ms}ms / 終了理由 {seg.stop_reason}")
    print(f"  認識 {int((time.monotonic() - started) * 1000)}ms")
    print(f"  聞こえた語 : {[(w[0], round(w[1], 2)) for w in m.words]}")
    print(f"  判定       : {m.matched or '-'}  (信頼度 {m.confidence}, 外れた理由 {m.reason})")
    seg.clear()
    return 0 if m.matched else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="状態だけ見る")
    ap.add_argument("--devices", action="store_true", help="入力デバイスの一覧")
    ap.add_argument("--mic", action="store_true", help="マイクで 1 回話す")
    ap.add_argument("--say", help="Windows の合成音声で読ませる言葉")
    ap.add_argument("--wav", type=Path, help="この WAV を流す")
    ap.add_argument("--screen", default="top", help="語彙を使う画面（既定 top）")
    ap.add_argument("--lang", default="ja", choices=["ja", "en"], help="聞く言語(既定 ja)")
    args = ap.parse_args()

    if args.devices:
        show_devices()
        return 0
    if args.status or not (args.mic or args.say or args.wav):
        return 0 if show_status() else 1
    if args.mic:
        return run_once(args.screen, "mic", None, args.lang)
    if args.say:
        wavs = ev.synth_many([args.say], 0, args.lang)
        return run_once(args.screen, "file", wavs[args.say], args.lang)
    return run_once(args.screen, "file", args.wav, args.lang)


if __name__ == "__main__":
    sys.exit(main())
