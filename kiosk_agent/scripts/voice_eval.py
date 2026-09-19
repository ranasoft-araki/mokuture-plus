"""一文受付（発話1回で会社名・氏名・訪問先・用件を取る）の精度評価ベンチ。

**Windows で回すためのもの。** 精度は OS に依存しない（同じモデルは同じ文字列を出す）。
速度だけは実機（Raspberry Pi）と全く違うので、ここの時間は目安にしないこと。

    # 音源を作る（Windows の音声合成。初回だけ）
    .venv\\Scripts\\python scripts\\voice_eval.py --synth

    # 文字起こしだけ評価（LLM 不要。モデル比較用）
    .venv\\Scripts\\python scripts\\voice_eval.py --asr-only --models tiny,base,small

    # 端から端まで（要 llama-server）
    .venv\\Scripts\\python scripts\\voice_eval.py --models base

    # 文字起こしを飛ばして抽出だけ見る（正しい文字列を LLM に渡す = 抽出の上限性能）
    .venv\\Scripts\\python scripts\\voice_eval.py --perfect-asr

測るもの:
  ASR   … 参照文との文字誤り率(CER)、固有名詞（会社・氏名・担当者）が残っているか
  抽出  … 項目ごとの正解率
  生成  … **null であるべき項目に値を入れていないか**（作業指示 §8 の肝。最重要）

評価の値（氏名・会社名）は架空か利用者の自社名のみ。実在の個人情報は使わない。
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from voice import settings, whisper_cpp  # noqa: E402
from voice.types import AudioSegment  # noqa: E402

CASES_FILE = Path(__file__).parent / "voice_eval_cases.json"
WAV_DIR = AGENT_DIR / "voice_eval_audio"
MODELS = {
    "tiny": ("voice_models/ggml-tiny-q5_1.bin", "whisper-tiny-q5"),
    "base": ("voice_models/ggml-base-q5_1.bin", "whisper-base-q5"),
    "small": ("voice_models/ggml-small-q5_1.bin", "whisper-small-q5"),
}
FIELDS = ["visitor_company", "visitor_name", "host_name_spoken", "purpose", "has_appointment"]

SCHEMA = {
    "type": "object",
    "properties": {
        "visitor_company": {"type": ["string", "null"]},
        "visitor_name": {"type": ["string", "null"]},
        "host_name_spoken": {"type": ["string", "null"]},
        "host_employee_id": {"type": ["string", "null"]},
        "purpose": {"type": ["string", "null"]},
        "has_appointment": {"type": ["boolean", "null"]},
    },
    "required": ["visitor_company", "visitor_name", "host_name_spoken",
                 "host_employee_id", "purpose", "has_appointment"],
    "additionalProperties": False,
}

PROMPT = """あなたは受付発話から情報を抽出する処理です。

発話に存在しない情報を推測してはいけません。不明な項目は必ずnullにしてください。
担当者は候補一覧から選択してください。候補にない人物を生成してはいけません。
氏名や会社名は、発話に出てきた文字列をそのまま使ってください。正式名称に直したり、
法人格を足したり、漢字を当て直したりしてはいけません。

担当者候補:
{staff}

用件候補: {purposes}

発話: 「{utterance}」

JSONだけを出力してください。"""


# ── 音源の用意 ────────────────────────────────────────────────────────────────

def synth(cases: list[dict]) -> None:
    """Windows の音声合成でテスト音源を作る。

    合成音声は人の声より認識しにくいので、ここで出る精度は**下限**と考えること。
    実機では人が話すので、これより良くなるのが普通。
    """
    if platform.system() != "Windows":
        print("--synth は Windows 専用です（他の環境では録音した WAV を voice_eval_audio/ に置いてください）")
        sys.exit(2)
    WAV_DIR.mkdir(exist_ok=True)
    lines = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$jp = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ja-JP' } | Select-Object -First 1",
        "if ($jp) { $s.SelectVoice($jp.VoiceInfo.Name) }",
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)",
    ]
    for c in cases:
        wav = WAV_DIR / f"{c['id']}.wav"
        lines.append(f'$s.SetOutputToWaveFile("{wav}", $fmt)')
        lines.append(f"$s.Speak(@'\n{c['utterance']}\n'@)")
    lines.append("$s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "\n".join(lines)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print("音声合成に失敗:", (r.stderr or "")[:300])
        sys.exit(1)
    print(f"{len(cases)} 件の音源を作りました: {WAV_DIR}")


# ── 文字起こし ────────────────────────────────────────────────────────────────

def transcribe(wav: Path, model_key: str) -> tuple[str, int]:
    rel, name = MODELS[model_key]
    cfg = settings.cfg()
    cfg["whisper"]["model_path"] = rel
    cfg["whisper"]["model_name"] = name
    # 評価は実時間の制約が無いので、本番用のタイムアウト(10秒)では測れない
    # 組み合わせ(small を遅い機械で回す等)が出る。ここだけ大きく取る。
    cfg["whisper"]["timeout_sec"] = 300.0
    ok, detail = whisper_cpp.available()
    if not ok:
        print(f"whisper を使えません({model_key}): {detail}")
        sys.exit(1)
    import wave

    with wave.open(str(wav), "rb") as w:
        pcm = w.readframes(w.getnframes())
        rate = w.getframerate()
    seg = AudioSegment(pcm=pcm, sample_rate=rate, total_ms=int(len(pcm) / 2 / rate * 1000),
                       speech_ms=int(len(pcm) / 2 / rate * 1000), stop_reason="manual",
                       peak_db=0.0, noise_floor_db=-60.0)
    try:
        tr = whisper_cpp.transcribe(seg)
        return tr.text, tr.recognition_ms
    finally:
        seg.clear()


def cer(reference: str, hypothesis: str) -> float:
    """文字誤り率。0 が完全一致。句読点と空白は無視する。"""
    drop = "。、,.「」 　\n"
    a = [c for c in reference if c not in drop]
    b = [c for c in hypothesis if c not in drop]
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[len(b)] / len(a)


# ── 抽出 ──────────────────────────────────────────────────────────────────────

def extract(utterance: str, staff: list[dict], purposes: list[str], url: str) -> tuple[dict | None, int, str]:
    prompt = (PROMPT
              .replace("{staff}", json.dumps(staff, ensure_ascii=False))
              .replace("{purposes}", json.dumps(purposes, ensure_ascii=False))
              .replace("{utterance}", utterance))
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 120,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "reception", "schema": SCHEMA, "strict": True}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        return None, int((time.monotonic() - t0) * 1000), f"接続できません: {e}"
    ms = int((time.monotonic() - t0) * 1000)
    raw = data["choices"][0]["message"]["content"]
    try:
        return json.loads(raw), ms, ""
    except ValueError:
        return None, ms, "JSON として読めない"


def grounded(value, source: str, staff: list[dict]) -> bool:
    """作業指示 §8: 発話または担当者候補に根拠があること。"""
    if value is None or isinstance(value, bool):
        return True
    v = str(value).strip()
    if not v:
        return True
    if v in source:
        return True
    return any(v == s["name"] or v in s["name"] or v == s.get("name_kana") for s in staff)


# ── 採点 ──────────────────────────────────────────────────────────────────────

def score_case(case: dict, got: dict, source: str, staff: list[dict]) -> dict:
    """1 件ぶんの採点。

    固有名詞は文字起こしで崩れるので「完全一致」だけでは実態が見えない。
    - hit       期待値と一致（期待が null なら null であること）
    - invented  **null であるべきなのに値が入った** = 生成。重大
    - ungrounded 発話にも候補にも無い文字列を出した = 生成。重大
    """
    out = {"hit": {}, "invented": [], "ungrounded": []}
    for f in FIELDS:
        want = case["expect"].get(f)
        have = got.get(f)
        if want is None:
            out["hit"][f] = have is None
            if have is not None:
                out["invented"].append(f)
        else:
            if isinstance(want, bool):
                out["hit"][f] = have == want
            else:
                out["hit"][f] = bool(have) and (str(want) in str(have) or str(have) in str(want))
        if not grounded(have, source, staff):
            out["ungrounded"].append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synth", action="store_true", help="テスト音源を作って終わる")
    ap.add_argument("--models", default="base", help="比較する whisper モデル (tiny,base,small)")
    ap.add_argument("--asr-only", action="store_true", help="文字起こしだけ評価する（LLM 不要）")
    ap.add_argument("--perfect-asr", action="store_true",
                    help="文字起こしを飛ばし、正しい発話文を LLM に渡す（抽出の上限性能）")
    ap.add_argument("--llm-url", default="http://127.0.0.1:8182/v1/chat/completions")
    ap.add_argument("--show-text", action="store_true", help="文字起こし結果と抽出結果を出す")
    args = ap.parse_args()

    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases, staff, purposes = data["cases"], data["staff_master"], data["purposes"]

    if args.synth:
        synth(cases)
        return 0

    keys = [k.strip() for k in args.models.split(",") if k.strip()]
    for k in keys:
        if k not in MODELS:
            print(f"不明なモデル: {k}（使えるのは {', '.join(MODELS)}）")
            return 2

    for model_key in ([""] if args.perfect_asr else keys):
        title = "文字起こし無し（発話文をそのまま）" if args.perfect_asr else f"whisper {model_key}"
        print(f"\n{'=' * 72}\n== {title}\n{'=' * 72}")
        cers, asr_ms, llm_ms = [], [], []
        hits = {f: 0 for f in FIELDS}
        invented_total, ungrounded_total, parse_fail = 0, 0, 0

        for c in cases:
            if args.perfect_asr:
                text, ms = c["utterance"], 0
            else:
                wav = WAV_DIR / f"{c['id']}.wav"
                if not wav.exists():
                    print(f"音源がありません: {wav.name}（先に --synth）")
                    return 1
                text, ms = transcribe(wav, model_key)
            asr_ms.append(ms)
            e = cer(c["utterance"], text)
            cers.append(e)

            line = f"[{c['label']:<12}] CER {e:.2f}"
            if args.show_text:
                line += f"\n    認識: {text.strip()}"
            if args.asr_only:
                print(line)
                continue

            got, lms, err = extract(text, staff, purposes, args.llm_url)
            llm_ms.append(lms)
            if got is None:
                parse_fail += 1
                print(line + f"\n    抽出: 失敗 ({err})")
                continue
            s = score_case(c, got, text, staff)
            for f in FIELDS:
                hits[f] += int(s["hit"][f])
            invented_total += len(s["invented"])
            ungrounded_total += len(s["ungrounded"])
            mark = "".join("o" if s["hit"][f] else "x" for f in FIELDS)
            line += f" | 抽出 {mark} ({lms}ms)"
            if s["invented"]:
                line += f" ⚠生成:{','.join(s['invented'])}"
            if s["ungrounded"]:
                line += f" ⚠根拠なし:{','.join(s['ungrounded'])}"
            if args.show_text:
                line += "\n    抽出: " + json.dumps(got, ensure_ascii=False)
            print(line)

        n = len(cases)
        print(f"\n-- まとめ ({n} 件) --")
        print(f"  CER 平均          : {sum(cers) / n:.3f}")
        print(f"  文字起こし時間    : 中央値 {sorted(asr_ms)[n // 2]}ms")
        if not args.asr_only:
            print(f"  LLM 時間          : 中央値 {sorted(llm_ms)[len(llm_ms) // 2]}ms" if llm_ms else "")
            print("  項目別の正解率    : " + "  ".join(f"{f.replace('visitor_', '').replace('_spoken', '')}={hits[f]}/{n}" for f in FIELDS))
            print(f"  ⚠ 生成した項目数  : {invented_total}   （0 でなければ不合格）")
            print(f"  ⚠ 根拠なし項目数  : {ungrounded_total}   （0 でなければ不合格）")
            print(f"  JSON 解析失敗     : {parse_fail}")
    print("\n注意: ここの処理時間は Windows の値です。Raspberry Pi の目安にはなりません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
