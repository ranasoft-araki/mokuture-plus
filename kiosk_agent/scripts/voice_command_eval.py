"""声で操作する(画面操作のキーワード)の当たり方を測る。

kiosk.html の語彙表(VOICE_VOCAB)を読み、画面ごとに**本番と同じ語彙**で decode する。
見るのは 3 つ:

  当たり     画面に書いてある言葉どおりに言って、その選択肢になったか
  取りこぼし 言ったのに「もう一度お願いします」になったか(画面は動かない＝安全側)
  誤爆       **誰も話しかけていないのに**選択肢になったか(画面が勝手に動く＝危険側)

誤爆を 0 に近づけるのが先。取りこぼしは言い直せば済むが、誤爆は画面が勝手に動く。

    # Windows の合成音声で(マイク不要)。しきい値を振って比べる
    .venv/Scripts/python scripts/voice_command_eval.py --min-conf 0.8,0.85,0.9

    # 実際の声・ロビーの音で(こちらが本番の目安)
    .venv/Scripts/python scripts/voice_command_eval.py --no-say --wav-dir ~/cmd_wavs

`--wav-dir` のファイル名で正解を決める:
    top__top.locker__arak1.wav     … 画面 top で「ロッカー」と言った(正解 locker)
    neg__lobby_0930.wav            … 誰も話しかけていない音(ロビーの雑談・空調)。全画面で誤爆を数える
長い録音(ロビーを数分録ったもの)はそのまま置けばよい。本番と同じ VAD で発話ごとに
切り出して、1 つずつ decode する。

**合成音声は人の声でもロビーの音でもない**(肉声は速く崩れ、短い語はその逆もありうる)。数字は目安で、決めるのは Pi 実機・実際のロビーの音で測った値。
**Pi での時間は Windows の目安にならない。**

音声も認識した言葉もどこにも保存しない(合成音声のキャッシュは一時フォルダに置く)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from voice import capture, settings, vad, vosk_engine  # noqa: E402

KIOSK_HTML = AGENT_DIR / "static" / "kiosk.html"
COMMON = ["common.back", "common.home", "common.wait", "common.restart"]

# 画面ごとに登録している語彙(kiosk.html の voiceCommands の呼び出しに合わせる)。
# 共通語は、その画面の下部帯にある押す先のぶんだけ入る(ようこそは「戻る」が無い等)。
SCREENS: dict[str, list[str]] = {
    "welcome": ["welcome.form", "common.home", "common.wait"],
    "top": ["top.visit", "top.delivery", "top.locker", *COMMON],
    "lockerMode": ["lockerMode.store", "lockerMode.pickup", *COMMON],
    "delivery": ["delivery.dropoff", *COMMON],
    "reception": ["reception.card", *COMMON],
    "locker": [f"locker.n{i}" for i in range(1, 8)] + COMMON,
    "confirm": ["confirm.yes", "confirm.no"],
    "result": ["result.done", "common.home"],
}
# 番号で選ぶ画面。語彙を絞って外れたら通常の認識で聞き直す(本番と同じ)。
FALLBACK_SCREENS = {"locker"}

# 誰も話しかけていないときに聞こえそうなもの。受付のそばの雑談・電話・独り言。
LOBBY = [
    "今日はいい天気ですね", "さっきの会議どうだった", "えーと", "ありがとうございました",
    "田中さんいますか", "荷物を届けに来ました", "すみません、トイレはどこですか", "三時から会議です",
    "一度戻ってください", "晩ご飯なににする", "はいどうぞ", "もしもし、聞こえますか",
    "少々お待ちください", "お疲れさまです", "六角形の机", "受付はこちらでよろしいですか",
    "配達の人もう来た", "ロッカーの鍵どこだっけ", "最初に言ったでしょ", "続けて説明します",
    "はい、そうです", "キーボードが壊れてる", "名刺切らしてて", "もう一回言って",
    "わかりました、完了です", "ちょっと待って", "やめるって言ってたよ", "預かってもらえますか",
]
# 言い添え。実際には単語だけでなく「えーと、〜」「〜でお願いします」と言われる。
VARIANTS = ["{p}", "えーと、{p}", "{p}でお願いします"]


def load_vocab() -> dict:
    text = KIOSK_HTML.read_text(encoding="utf-8")
    m = re.search(r"/\* VOICE_VOCAB:BEGIN \*/\s*const VOICE_VOCAB = (\{.*?\});\s*/\* VOICE_VOCAB:END \*/", text, re.S)
    if not m:
        sys.exit("kiosk.html に VOICE_VOCAB が見つかりません")
    return json.loads(m.group(1))


def wire_id(key: str) -> str:
    return key.split(".")[-1].lower()


def choices_for(screen: str, vocab: dict) -> list[tuple[str, list[str]]]:
    return [(wire_id(k), list(vocab[k]["say"])) for k in SCREENS[screen] if k in vocab]


# ── 音源 ──────────────────────────────────────────────────────────────────────

def synth_many(texts: list[str], rate: int) -> dict[str, Path]:
    """Windows の音声合成でまとめて WAV を作る(1 つずつ PowerShell を起こすと遅い)。"""
    if platform.system() != "Windows":
        sys.exit("--say は Windows 専用です。--no-say --wav-dir で音源を渡してください")
    cache = Path(tempfile.gettempdir()) / "mokuture-voice-cmd-eval"
    cache.mkdir(exist_ok=True)
    out: dict[str, Path] = {}
    todo: list[tuple[str, Path]] = []
    for t in texts:
        p = cache / (hashlib.sha1(f"{t}|{rate}".encode()).hexdigest()[:16] + ".wav")
        out[t] = p
        if not p.exists():
            todo.append((t, p))
    if todo:
        lines = "\n".join(f"@('{str(p)}', @'\n{t}\n'@)," for t, p in todo)
        script = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$jp = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq 'ja-JP' }} | Select-Object -First 1
if ($jp) {{ $s.SelectVoice($jp.VoiceInfo.Name) }}
$s.Rate = {rate}
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$items = @(
{lines}
$null)
foreach ($it in $items) {{ if ($it -eq $null) {{ continue }}; $s.SetOutputToWaveFile($it[0], $fmt); $s.Speak($it[1].Trim()) }}
$s.Dispose()
'''
        print(f"  合成音声を作っています ({len(todo)} 本)…", flush=True)
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            sys.exit("音声合成に失敗しました: " + (r.stderr or "")[:300])
    return out


def utterances(path: Path, rate: int) -> list:
    """本番と同じ VAD で発話を切り出す(長い録音なら複数)。"""
    pcm = capture.read_wav_as_pcm(path, rate)
    # 窓が開いてから話し始めるまでの間を模して、頭に無音を足す。
    pcm = b"\x00\x00" * int(rate * 0.4) + pcm + b"\x00\x00" * int(rate * 1.0)
    stream = capture.BufferStream(pcm, loop_silence=True, realtime=False, sample_rate=rate)
    # 録音ループの時計を「流した音の長さ」にする(待たずに回すため)。
    clock = lambda: stream._delivered / (rate * capture.SAMPLE_WIDTH)  # noqa: E731,SLF001
    ccfg = settings.get("command")
    segs = []
    while stream._pos < len(pcm):  # noqa: SLF001 — 計測用に位置を直接見る
        seg = vad.record_utterance(
            stream,
            max_record_sec=float(ccfg["max_record_sec"]),
            silence_sec=float(ccfg["silence_sec"]),
            start_timeout_sec=2.0,
            now=clock,
        )
        if seg.stop_reason != "no_speech" and seg.speech_ms > 0:
            segs.append(seg)
    return segs


# ── 採点 ──────────────────────────────────────────────────────────────────────

def decode(seg, choices, fallback: bool) -> tuple[list, int, str | None]:
    """語の並びと認識時間。しきい値は後で振るので、ここでは 0 で当てる。

    番号の画面は聞き直しを含めた本番どおりの判定を 3 つ目に返す(しきい値は振らない)。
    """
    if fallback:
        m = vosk_engine.recognize_command(seg, choices, fallback=True)
        return m.words, m.recognition_ms, m.matched
    m = vosk_engine.recognize_command(seg, choices, min_conf=0.0)
    return m.words, m.recognition_ms, None


def judge(words, choices, floor: float) -> str | None:
    table, _ = vosk_engine.command_table(choices)
    matched, _, _ = vosk_engine.match_command(words, table, floor)
    return matched


def percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round((len(s) - 1) * pct)))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-conf", default="", help="比べるしきい値(カンマ区切り)。既定は設定値")
    ap.add_argument("--screens", default="", help="測る画面(カンマ区切り)。既定は全部")
    ap.add_argument("--no-say", action="store_true", help="合成音声を使わない")
    ap.add_argument("--rate", type=int, default=0, help="合成音声の話速(-10〜10)")
    ap.add_argument("--wav-dir", type=Path, help="実際の声・ロビーの録音(ファイル名の規則は冒頭)")
    ap.add_argument("--show", action="store_true", help="外れた回に聞こえた語を出す(画面に出すだけ)")
    args = ap.parse_args()

    ok, detail = vosk_engine.available()
    if not ok or not vosk_engine.grammar_supported():
        print("Vosk を使えません:", detail or "語彙を絞れないモデル")
        return 1
    vocab = load_vocab()
    screens = [s for s in (args.screens.split(",") if args.screens else SCREENS) if s in SCREENS]
    floors = [float(x) for x in args.min_conf.split(",") if x] or [float(settings.get("command.min_conf"))]
    rate = int(settings.get("audio.sample_rate"))

    # (画面, 正解 id or None, 名前, 音源)
    cases: list[tuple[str, str | None, str, Path]] = []
    if not args.no_say:
        # 言う言葉 = 語彙の言い回し＋ボタンの札に書いた読み(札どおりに言って当たらないと困る)。
        def spoken(k):
            v = vocab.get(k, {})
            return list(dict.fromkeys(list(v.get("say", [])) + ([v["label"]] if v.get("label") else [])))
        pos_texts = {v.format(p=p) for s in screens for k in SCREENS[s] if k in vocab
                     for p in spoken(k) for v in VARIANTS}
        wavs = synth_many(sorted(pos_texts | set(LOBBY)), args.rate)
        for s in screens:
            for k in SCREENS[s]:
                for p in spoken(k):
                    for v in VARIANTS:
                        t = v.format(p=p)
                        cases.append((s, wire_id(k), t, wavs[t]))
            for t in LOBBY:
                cases.append((s, None, t, wavs[t]))
    if args.wav_dir:
        for f in sorted(Path(args.wav_dir).expanduser().glob("*.wav")):
            parts = f.stem.split("__")
            if parts[0] == "neg":
                cases.extend((s, None, f.name, f) for s in screens)
            elif len(parts) >= 2 and parts[0] in screens:
                cases.append((parts[0], wire_id(parts[1]), f.name, f))

    print(f"モデル {vosk_engine.model_name()} / 画面 {len(screens)} / 音源 {len(cases)} 件")
    vosk_engine.load()
    started = time.monotonic()
    results = []       # (screen, want, name, [(words, ms)])
    first_ms: dict[str, int] = {}
    seg_cache: dict[Path, list] = {}
    for screen, want, name, path in cases:
        if path not in seg_cache:
            seg_cache[path] = utterances(path, rate)
        choices = choices_for(screen, vocab)
        decoded = []
        for seg in seg_cache[path]:
            words, ms, fixed = decode(seg, choices, screen in FALLBACK_SCREENS)
            first_ms.setdefault(screen, ms)
            decoded.append((words, ms, fixed))
        results.append((screen, want, name, choices, decoded))
    print(f"(計 {time.monotonic() - started:.1f} 秒)\n")

    rec_ms = [ms for *_, d in results for _, ms, _ in d]
    for floor in floors:
        print(f"== しきい値 {floor} ==")
        print(f"{'画面':<12}{'当たり':>10}{'取りこぼし':>10}{'取り違え':>8}{'誤爆':>12}")
        tot = {"hit": 0, "pos": 0, "miss": 0, "wrong": 0, "fa": 0, "neg": 0}
        misses = []
        for s in screens:
            c = {"hit": 0, "pos": 0, "miss": 0, "wrong": 0, "fa": 0, "neg": 0}
            for screen, want, name, choices, decoded in results:
                if screen != s:
                    continue
                got = [fixed if screen in FALLBACK_SCREENS else judge(w, choices, floor) for w, _, fixed in decoded]
                got = [g for g in got if g]
                if want is None:
                    c["neg"] += 1
                    if got:
                        c["fa"] += 1
                        misses.append(f"  誤爆   {s:<11} {name} → {got}" + (f"  {decoded[0][0]}" if args.show else ""))
                else:
                    c["pos"] += 1
                    if got and got[0] == want:
                        c["hit"] += 1
                    elif got:
                        c["wrong"] += 1
                        misses.append(f"  取違え {s:<11} {name} → {got} (正解 {want})" + (f"  {decoded[0][0] if decoded else ''}" if args.show else ""))
                    else:
                        c["miss"] += 1
                        if args.show:
                            misses.append(f"  取こぼ {s:<11} {name}  {decoded[0][0] if decoded else '(発話なし)'}")
            for k in tot:
                tot[k] += c[k]
            print(f"{s:<12}{c['hit']:>5}/{c['pos']:<4}{c['miss']:>10}{c['wrong']:>8}{c['fa']:>7}/{c['neg']}")
        print(f"{'計':<12}{tot['hit']:>5}/{tot['pos']:<4}{tot['miss']:>10}{tot['wrong']:>8}{tot['fa']:>7}/{tot['neg']}")
        for line in misses:
            print(line)
        print()
    print(f"認識時間 中央値 {percentile(rec_ms, .5)}ms / 95% {percentile(rec_ms, .95)}ms"
          f" / 画面ごとの初回 {', '.join(f'{k} {v}ms' for k, v in first_ms.items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
