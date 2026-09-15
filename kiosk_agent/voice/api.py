"""音声入力の HTTP API(キオスクのブラウザから叩く)。

    GET    /voice/status                    利用可否・エンジン・モデル・項目の文言
    POST   /voice/session                   セッション開始
    POST   /voice/session/{sid}/listen      1 項目ぶんの録音と認識を開始(すぐ返る)
    GET    /voice/session/{sid}/state       進行状態(phase / 音量 / 結果)をポーリング
    POST   /voice/session/{sid}/stop        「入力を終了」= そこまでを発話として確定
    POST   /voice/session/{sid}/cancel      「キャンセル」= 録音も認識も捨てる
    POST   /voice/session/{sid}/retry       「もう一度話す」= 再入力回数を数える
    POST   /voice/session/{sid}/event       確定・タッチへ切替の匿名イベント(§12)
    DELETE /voice/session/{sid}             破棄(音声と認識結果を捨てる)
    GET    /voice/metrics                   実証実験の集計(§12)
    GET    /voice/devices                   マイク一覧(設定手順用)

音声はここへは流れてこない。マイクを握るのはサービス側で(§10)、ブラウザが送るのは
「どの項目を録るか」だけ。認識結果は state のレスポンスでだけ返し、保存はしない。

外部へは一切通信しない。待ち受けも 127.0.0.1 に限定してあるが、念のため発信元が
ループバックであることをここでも確かめる(二重の網)。

ログに氏名・会社名・担当者名・認識結果を出さない。出すのは項目名・状態・所要時間だけ。
"""
from __future__ import annotations

import ipaddress
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from voice import capture, metrics, session as session_mod, settings, whisper_cpp
from voice.types import FIELDS, message

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")


# ── 入力の検証 ────────────────────────────────────────────────────────────────

def _require_enabled() -> None:
    if not bool(settings.get("enabled")):
        raise HTTPException(status_code=404, detail="voice input disabled")


def _require_local(request: Request) -> None:
    """ループバックからのみ受け付ける(§10・§13)。"""
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


class ListenBody(BaseModel):
    field: str = Field(default="company")


class EventBody(BaseModel):
    # confirm = この内容で進む / fallback_touch = 音声をやめて通常操作へ
    result: str
    edited: bool = False
    field: str | None = None


# ── 状態 ──────────────────────────────────────────────────────────────────────

@router.get("/status")
async def voice_status(request: Request):
    """音声入力が使えるかと、画面が必要とする文言・しきい値を返す。

    キオスクは起動時にこれを見て、使えないときは「音声で入力」を描画しない。
    """
    _require_local(request)
    enabled = bool(settings.get("enabled"))
    mic_ok, mic_detail = capture.available()
    engine = whisper_cpp.describe()

    fields = {}
    for name in FIELDS:
        f = settings.field_cfg(name)
        fields[name] = {
            "prompt_ja": f.get("prompt_ja", ""),
            "prompt_en": f.get("prompt_en", ""),
            "example_ja": f.get("example_ja", ""),
            "max_record_sec": float(f.get("max_record_sec") or settings.get("vad.max_record_sec")),
            "engine": f.get("engine", "whisper"),
        }

    return {
        "available": enabled and mic_ok and engine["available"],
        "enabled": enabled,
        "microphone": {"available": mic_ok, "detail": mic_detail},
        "engines": {"whisper": engine},
        # 第3・4段階(Vosk・担当者照合)はまだ。画面が導線を出さないよう false を返す。
        "features": {
            "company": True,
            "person_name": True,
            "staff": False,
            "command": False,
        },
        "fields": fields,
        "timing": {
            "start_timeout_sec": float(settings.get("vad.start_timeout_sec")),
            "silence_sec": float(settings.get("vad.silence_sec")),
            "max_record_sec": float(settings.get("vad.max_record_sec")),
            "recognition_timeout_sec": float(settings.get("whisper.timeout_sec")),
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


@router.post("/session/{sid}/listen")
async def voice_listen(sid: str, body: ListenBody, request: Request):
    """1 項目ぶんの録音を始める。すぐ返るので、画面は state をポーリングする。

    呼ぶ前に、端末の音声案内と受付開始音の再生を終えていること(§9)。案内を
    鳴らしながらマイクを開くと、自分の案内を認識してしまう。
    """
    _require_local(request)
    _require_enabled()
    session = _require_session(sid)
    if body.field not in FIELDS:
        raise HTTPException(status_code=400, detail="unknown field")
    if not settings.field_cfg(body.field):
        raise HTTPException(status_code=400, detail="field not configured")
    try:
        session.listen(body.field)
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


@router.post("/session/{sid}/stop")
async def voice_stop(sid: str, request: Request):
    """「入力を終了」。無音を待たずにそこまでを発話として確定する。"""
    _require_local(request)
    session = _require_session(sid)
    session.stop()
    return session.state()


@router.post("/session/{sid}/cancel")
async def voice_cancel(sid: str, request: Request):
    """「キャンセル」。録音中の音声を捨てる。"""
    _require_local(request)
    session = _require_session(sid)
    session.cancel()
    session.clear_result()
    return session.state()


@router.post("/session/{sid}/retry")
async def voice_retry(sid: str, request: Request):
    """「もう一度話す」。前の結果を捨て、再入力回数を 1 増やす(§12)。"""
    _require_local(request)
    session = _require_session(sid)
    session.clear_result()
    count = session.note_retry()
    return {"session_id": session.id, "retry_count": count}


@router.post("/session/{sid}/event")
async def voice_event(sid: str, body: EventBody, request: Request):
    """画面側でしか分からない結果を匿名で記録する(§12)。

    - confirm        …… 利用者が「この内容で進む」を押した(edited=直したかどうか)
    - fallback_touch …… 音声をやめて通常のタッチ入力へ戻った

    **直した中身は送らない・受け取らない。** 送られてきても metrics 側が捨てる。
    """
    _require_local(request)
    session = _require_session(sid)
    if body.result not in ("confirm", "fallback_touch"):
        raise HTTPException(status_code=400, detail="unknown event")
    if body.result == "fallback_touch":
        session.fell_back = True
    field_name = body.field or session.field or ""
    metrics.record({
        "sessionId": session.id,
        "screenId": metrics.SCREEN_IDS.get(field_name, field_name or "unknown"),
        "result": body.result,
        "edited": bool(body.edited),
        "model": whisper_cpp.model_name(),
        "retryCount": session.retry_count.get(field_name, 0),
        "errorCode": None,
    })
    return {"ok": True}


@router.delete("/session/{sid}", status_code=204)
async def voice_session_drop(sid: str, request: Request):
    """破棄。音声も認識結果も捨てる(§11)。"""
    _require_local(request)
    if not sid or not _SESSION_ID_RE.match(sid):
        raise HTTPException(status_code=400, detail="invalid session id")
    dropped = session_mod.store.drop(sid)
    log.info("[voice] session dropped=%s (active=%d)", dropped, session_mod.store.count())
    return None


# ── 実験の集計 ────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def voice_metrics(request: Request):
    """§12 の指標。件数・割合・時間だけで、個票も本文も含まない。"""
    _require_local(request)
    return metrics.summary()
