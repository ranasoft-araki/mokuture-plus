"""声で操作する(画面操作のキーワード)の HTTP API。キオスクのブラウザから叩く。

    GET    /voice/status                    使えるか(マイク・Vosk・語彙を絞れるモデルか)
    POST   /voice/session                   セッション開始(音声モードに入ったとき)
    POST   /voice/session/{sid}/command     画面の選択肢のどれが言われたかを 1 回聞く(すぐ返る)
    GET    /voice/session/{sid}/state       進行状態(phase / 音量 / 判定)をポーリング
    POST   /voice/session/{sid}/cancel      聞き取りを取り消す(暗証番号の画面へ移った等)
    DELETE /voice/session/{sid}             破棄(音声と判定を捨てる)
    GET    /voice/metrics                   実証実験の集計
    GET    /voice/devices                   マイク一覧(設定手順用)

音声はここへは流れてこない。マイクを握るのはサービス側で、ブラウザが送るのは
「いまの画面で受け付ける言葉」だけ。判定は state のレスポンスでだけ返し、保存はしない。

外部へは一切通信しない。待ち受けも 127.0.0.1 に限定してあるが、念のため発信元が
ループバックであることをここでも確かめる(二重の網)。
"""
from __future__ import annotations

import ipaddress
import logging
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from voice import capture, metrics, session as session_mod, settings, vosk_engine
from voice.types import message

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


# ── 入力の検証 ────────────────────────────────────────────────────────────────

def _require_enabled() -> None:
    if not bool(settings.get("enabled")):
        raise HTTPException(status_code=404, detail="voice disabled")


def _require_local(request: Request) -> None:
    """ループバックからのみ受け付ける。"""
    host = request.client.host if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden")
    if not addr.is_loopback:
        raise HTTPException(status_code=403, detail="forbidden")


def _require_session(sid: str) -> session_mod.Session:
    if not sid or not _SESSION_ID_RE.match(sid):
        raise HTTPException(status_code=400, detail="invalid session id")
    session = session_mod.store.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


class CommandChoice(BaseModel):
    # id は画面が決める固定語彙(「visit」「back」)。実験ログにそのまま書くので、
    # 人の名前などが紛れ込まない形に限る。
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    # 受け付ける言い回し。1 つの読みには 1 つの表記だけ(同じ読みを並べると信頼度が
    # 割れて、どちらも当たらなくなる / voice/vosk_engine.py)。
    phrases: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]] = \
        Field(min_length=1, max_length=8)


class CommandBody(BaseModel):
    # 実験ログの画面名(kiosk.html の CURRENT_SCREEN)。
    screen: str = Field(default="unknown", pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")
    choices: list[CommandChoice] = Field(min_length=1, max_length=24)
    # 話し始めを待つ長さ。省略時は command.window_sec。
    window_sec: float | None = Field(default=None, ge=1.0, le=30.0)
    # 番号で選ぶ画面(ロッカー)。語彙を絞って外れたら通常の認識で聞き直す。
    fallback: bool = False
    # この1回の聞き取りの言語。表示言語(タッチ切替)に追従するだけで、発話での
    # 自動判定はしない。省略時は日本語(旧バージョンのキオスク画面との互換)。
    lang: str = Field(default="ja", pattern=r"^(ja|en)$")


def command_available(lang: str = "ja") -> tuple[bool, str]:
    """声で操作できるか。語彙を絞れる Vosk のモデルが要る。"""
    if not bool(settings.get("command.enabled")):
        return False, "command.enabled が false"
    ok, detail = vosk_engine.available(lang)
    if not ok:
        return False, detail
    if not vosk_engine.grammar_supported(lang):
        return False, "このモデルは語彙を絞れません(graph/Gr.fst が無い)"
    return True, ""


# ── 状態 ──────────────────────────────────────────────────────────────────────

@router.get("/status")
async def voice_status(request: Request):
    """声で操作できるかを返す。

    キオスクは起動時にこれを見て、使えないときは「声で操作する」を描画しない。
    """
    _require_local(request)
    enabled = bool(settings.get("enabled"))
    mic_ok, mic_detail = capture.available()
    command_ok, command_detail = command_available("ja")
    # 言語ごとの可否(新しいキー)。英語モデルが未導入の端末でも落ちない
    # (vosk_engine.available が「無い」を返すだけ)。古いキオスク画面はこのキーを
    # 読まないので、下の既存キー(日本語の可否)は変えずそのまま返す。
    languages = {}
    for lang in vosk_engine.LANGS:
        lang_ok, lang_detail = command_available(lang)
        languages[lang] = {
            "available": enabled and mic_ok and lang_ok,
            "detail": lang_detail,
            "engine": vosk_engine.describe(lang),
        }
    return {
        "available": enabled and mic_ok and command_ok,
        "enabled": enabled,
        "microphone": {"available": mic_ok, "detail": mic_detail},
        "engine": vosk_engine.describe("ja"),
        "languages": languages,
        "features": {
            # false の端末では画面に「声で操作する」を出さない。
            "command": enabled and mic_ok and command_ok,
        },
        "command": {
            "available": command_ok,
            "detail": command_detail,
            "window_sec": float(settings.get("command.window_sec")),
            # 画面を開いたら自動で音声モードに入るか(押さなくても聞き取る)。
            "auto_start": bool(settings.get("command.auto_start")),
        },
        "timing": {
            # 画面のポーリング間隔の目安。録音中の音量バーをなめらかに描くため。
            "poll_interval_ms": 120,
        },
        "config_notes": settings.notes(),
    }


@router.get("/devices")
async def voice_devices(request: Request):
    """マイクの一覧(`arecord -L`)。設定手順で使う。個人情報は含まない。"""
    _require_local(request)
    return {"current": settings.get("audio.device"), "devices": capture.list_devices()}


# ── セッション ────────────────────────────────────────────────────────────────

@router.post("/session")
async def voice_session_start(request: Request):
    _require_local(request)
    _require_enabled()
    session = session_mod.store.start()
    log.info("[voice] session started (active=%d)", session_mod.store.count())
    return {"session_id": session.id}


@router.post("/session/{sid}/command")
async def voice_command(sid: str, body: CommandBody, request: Request):
    """画面の選択肢のどれが言われたかを 1 回だけ聞く。すぐ返るので state をポーリングする。

    結果は state の `command`(matched / confidence / reason)。**認識した言葉そのものは
    返さない。** 話しかけられずに窓が閉じたら phase=error・error_code=no_speech で、
    画面は黙って開け直してよい。

    同じセッションで前の画面の聞き取りが走っていたら、畳んでから開け直す。
    """
    _require_local(request)
    _require_enabled()
    session = _require_session(sid)
    ok, detail = command_available(body.lang)
    if not ok:
        raise HTTPException(status_code=409, detail=f"command unavailable: {detail}")
    choices = [(c.id, list(c.phrases)) for c in body.choices]
    try:
        # 前の聞き取りを畳むのを待つことがある(最大 2 秒)ので、イベントループを塞がない。
        await run_in_threadpool(session.listen_command, choices, screen=body.screen,
                                window_sec=body.window_sec, fallback=body.fallback, lang=body.lang)
    except session_mod.Busy:
        raise HTTPException(status_code=409, detail="already listening")
    return session.state()


@router.get("/session/{sid}/state")
async def voice_state(sid: str, request: Request):
    _require_local(request)
    session = _require_session(sid)
    state = session.state()
    code = state.get("error_code")
    if code:
        ja, en = message(code)
        state["message"] = ja
        state["message_en"] = en
    return state


@router.post("/session/{sid}/cancel")
async def voice_cancel(sid: str, request: Request):
    """聞き取りを取り消す。録音中の音声を捨てる。"""
    _require_local(request)
    session = _require_session(sid)
    session.cancel()
    session.clear_result()
    return session.state()


@router.delete("/session/{sid}", status_code=204)
async def voice_session_drop(sid: str, request: Request):
    """破棄。音声も判定も捨てる。"""
    _require_local(request)
    if not sid or not _SESSION_ID_RE.match(sid):
        raise HTTPException(status_code=400, detail="invalid session id")
    dropped = session_mod.store.drop(sid)
    log.info("[voice] session dropped=%s (active=%d)", dropped, session_mod.store.count())
    return None


# ── 実験の集計 ────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def voice_metrics(request: Request):
    """件数・割合・時間だけで、個票も本文も含まない。"""
    _require_local(request)
    return metrics.summary()
