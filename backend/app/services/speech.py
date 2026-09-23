"""クラウド音声認識(AmiVoice)への中継。

**鍵を端末に置かないための層。** 発売済みのキオスクすべてに APPKEY を配って回るのは
現実的でないうえ、端末が持ち出されたときに止められない。そこでキオスクは自社のこの
API へ音声を送り、ここが AmiVoice を呼ぶ。鍵はサーバの環境変数にだけ置く。発行・失効・
差し替えが中央で完結し、承認されていない端末からは呼べない(既存の端末トークン認証)。

**音声も認識結果も保存しない。** AmiVoice 側もログを残さないエンドポイントを使う。
ここでログに出すのは大きさと所要時間だけ(キオスク側 §11 と同じ扱い)。

ローカル(Raspberry Pi の Vosk)との使い分けは端末側が決める。ここは頼まれたら文字起こし
を返すだけで、失敗したら素直に失敗を返す(端末はローカルの結果へ落ちる)。

なぜクラウドを併用するのか: 予定に無い飛び込み来訪者の会社名は、候補が無いのでローカル
では取れない(実測で会社名 5/10、1GB モデルでも改善せず)。AmiVoice は同じ音源で 9/10。
詳細は kiosk_agent/VOICE_INPUT.md の 4-8。
"""
from __future__ import annotations

import logging
import time
import urllib.parse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

#: ログを残さない方のエンドポイント。単価は高い(158.4円/時間 対 99円/時間)が、
#: 受付の音声を預けない形にする。
ENDPOINT = "https://acp-api.amivoice.com/v1/nolog/recognize"

#: 単語登録に渡す語数の上限。多すぎると効果が薄れるうえ、リクエストが膨らむ。
MAX_WORDS = 500


class SpeechUnavailable(RuntimeError):
    """そもそも呼べない(鍵が無い・テナントが未許可)。端末は従来どおり動く。"""


class SpeechFailed(RuntimeError):
    """呼んだが失敗した。端末はローカルの認識結果へ落ちる。"""


def profile_words(words: list[str]) -> str:
    """AmiVoice の profileWords の書式にする。

    受け取るのは「表記 読み」の並び(例: "服部健一 はっとりけんいち")。読みが無いものは
    渡さない — 読みを推測してはいけないという既存の方針(VOICE_INPUT.md 2-4)をここでも
    守る。書式は「表記 読み」を | で連ねたもの。
    """
    entries: list[str] = []
    for raw in words[:MAX_WORDS]:
        parts = str(raw or "").split()
        if len(parts) < 2:
            continue
        entries.append(f"{parts[0]} {parts[1]}")
    return "|".join(entries)


async def transcribe(wav: bytes, words: list[str] | None = None) -> tuple[str, int]:
    """1 発話を文字起こしする。(テキスト, 所要ミリ秒)。

    wav は 16bit モノラルの WAV。音声はメモリ上だけで扱い、どこにも書かない。
    """
    if not settings.cloud_asr_enabled:
        raise SpeechUnavailable("AMIVOICE_APPKEY が設定されていません")

    d = f"grammarFileNames={settings.amivoice_engine}"
    joined = profile_words(words or [])
    if joined:
        d += " profileWords=" + urllib.parse.quote(joined, safe="")

    # 音声(a)は必ず最後に置く。後ろに置いたパラメータは無視される仕様で、順番を
    # 間違えると認証エラーになる。
    files = [
        ("u", (None, settings.amivoice_appkey)),
        ("d", (None, d)),
        ("a", ("audio.wav", wav, "audio/wav")),
    ]
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.amivoice_timeout_sec) as client:
            r = await client.post(ENDPOINT, files=files)
            r.raise_for_status()
            payload = r.json()
    except Exception as e:
        raise SpeechFailed(f"{type(e).__name__}") from e
    elapsed = int((time.monotonic() - started) * 1000)

    if payload.get("code"):
        # message は機器・設定の話で、認識結果は含まれない。
        raise SpeechFailed(str(payload.get("message") or payload.get("code")))
    text = str(payload.get("text") or "").strip()
    # 中身は出さない。大きさと時間だけ(§11)。
    logger.info("[voice] cloud asr: %d bytes -> %d chars in %dms", len(wav), len(text), elapsed)
    return text, elapsed
