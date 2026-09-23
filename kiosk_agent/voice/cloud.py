"""クラウド音声認識への中継(自社バックエンド経由)。

**鍵は端末に置かない。** 発売済みのキオスクすべてに APPKEY を配って回るのは現実的で
ないうえ、端末が持ち出されたときに止められない。キオスクは既に持っているデバイス
トークンで自社 API(`/kiosk/voice/transcribe`)を呼び、サーバが AmiVoice を呼ぶ。

使うかどうかは**サーバが決める**。サーバに鍵があり、かつテナントが許可しているときだけ
文字起こしが返る。そうでなければ 503 が返るので、しばらく問い合わせを止める。使えなくても
ローカル認識だけで受付は従来どおり動く。

**ローカルと並走させる。** クラウドの方が固有名詞に強い(実測: 会社名 5/10 → 9/10。
予定に無い飛び込み来訪者の会社名は候補が無いのでローカルでは取れない)。ただし通信が
要る。ローカルは先に終わるので、予算内にクラウドが返ればそちらを採り、返らなければ
ローカルの結果をそのまま使う = 待ち時間は増えない。

音声はメモリ上だけで扱い、ファイルには書かない(§11)。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

import httpx

from voice import capture, settings
from voice.types import AudioSegment

log = logging.getLogger(__name__)

#: 503(サーバが無効)を受けたら、この秒数は問い合わせない。毎回の無駄な往復を避ける。
_BACKOFF_SEC = 600.0
_disabled_until = 0.0
_lock = threading.Lock()
#: 並走用。低頻度なので 2 本あれば足りる(遅れている呼び出しが次を塞がない)。
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-cloud")


def _api_url() -> str:
    """自社 API の入口。本体の .env(REMOTE_API_URL)を systemd 経由で受け取っている。"""
    raw = str(settings.get("cloud.api_url") or "").strip()
    return (raw or os.environ.get("REMOTE_API_URL", "")).rstrip("/")


def _token() -> str:
    """端末トークン。本体が登録時に保存したものをそのまま使う。"""
    try:
        import state  # kiosk_agent 直下。サービスは WorkingDirectory から読む
        return state.get_device_token()
    except Exception:
        return ""


def enabled() -> bool:
    return bool(settings.get("cloud.enabled")) and bool(_api_url()) and bool(_token())


def available() -> tuple[bool, str]:
    """(使えるか, 理由)。画面と /voice/status 用。実際の可否はサーバが決める。"""
    if not settings.get("cloud.enabled"):
        return False, "設定で無効(cloud.enabled)"
    if not _api_url():
        return False, "REMOTE_API_URL が分かりません"
    if not _token():
        return False, "この端末はまだ登録されていません"
    with _lock:
        if time.monotonic() < _disabled_until:
            return False, "サーバ側が無効(しばらく問い合わせません)"
    return True, "中継あり(可否はサーバが決めます)"


def _disable_for_a_while() -> None:
    global _disabled_until
    with _lock:
        _disabled_until = time.monotonic() + _BACKOFF_SEC


def reset() -> None:
    """問い合わせ停止を解除する(テストと、設定を変えて入れ直したとき用)。"""
    global _disabled_until
    with _lock:
        _disabled_until = 0.0


def _post(wav: bytes, words: list[str], timeout: float) -> str:
    url = f"{_api_url()}/kiosk/voice/transcribe"
    files = [("audio", ("a.wav", wav, "audio/wav")),
             ("words", (None, "\n".join(words)))]
    r = httpx.post(url, files=files, headers={"X-Kiosk-Token": _token()}, timeout=timeout)
    if r.status_code == 503:
        # サーバに鍵が無い or テナントが許可していない。しばらく黙る。
        _disable_for_a_while()
        return ""
    r.raise_for_status()
    return str((r.json() or {}).get("text") or "").strip()


def start(seg: AudioSegment, words: list[str]) -> Future | None:
    """文字起こしを裏で取りに行く。使えないときは None。

    words は「表記 読み」の並び。担当者の読みを渡すと固有名詞が当たりやすくなる。
    """
    ok, _ = available()
    if not ok:
        return None
    wav = capture.to_wav(seg.pcm, seg.sample_rate)
    timeout = float(settings.get("cloud.timeout_sec"))

    def run() -> str:
        try:
            return _post(wav, words, timeout)
        except Exception as e:
            log.info("[voice] クラウド認識を使えませんでした: %s", type(e).__name__)
            return ""

    try:
        return _pool.submit(run)
    except Exception:
        return None


def finish(future: Future | None, budget_sec: float) -> str:
    """予算内で結果を受け取る。間に合わなければ空文字(ローカルの結果を使う)。"""
    if future is None or budget_sec <= 0:
        return ""
    try:
        return future.result(timeout=budget_sec)
    except Exception:
        # 間に合わなかった。呼び出し自体は裏で終わるに任せる(結果は捨てる)。
        return ""


def words_for(staff: list) -> list[str]:
    """名簿を「表記 読み」の並びにする。読みが無い人は渡さない(推測は禁止)。"""
    out: list[str] = []
    for s in staff:
        name = str(getattr(s, "name", "") or "").replace(" ", "")
        reading = next((r for r in getattr(s, "readings", lambda: ())() if r), "")
        if name and reading:
            out.append(f"{name} {reading}")
    return out
