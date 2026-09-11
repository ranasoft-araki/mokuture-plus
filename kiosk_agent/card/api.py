"""名刺読み取りの HTTP API（キオスクのブラウザから叩く）。

    GET    /card/status                  利用可否・エンジン・しきい値
    POST   /card/session                 セッション開始
    POST   /card/frame?session_id=...    検出用フレーム（低解像度）を 1 枚送る
    POST   /card/capture?session_id=...  撮影フレーム（高解像度）を送り OCR・抽出
    POST   /card/session/{sid}/confirm   利用者が確認・修正した値を確定
    DELETE /card/session/{sid}           取り消し（セッションと画像を破棄）

画像は multipart ではなく本文そのまま（Content-Type: image/jpeg）で受ける。
受け取ったバイト列はメモリ上でだけ扱い、ファイルには書かない。

外部への通信は一切しない。既定ではループバック（キオスク端末自身のブラウザ）からの
リクエストだけを受け付ける（settings bind_loopback_only）。

ログに氏名・電話番号・メールアドレスを出さない。出すのは件数・状態・所要時間だけ。
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field as PydField

from card import dicts, session as session_mod, settings
from card.ocr import describe_all, get_engine
from card.ocr.base import OcrUnavailable
from card.pipeline import evaluate_acceptance, lines_payload, read_card
from card.preprocess import decode_image, limit_width
from card.quality import GUIDANCE
from card.types import FIELD_NAMES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/card", tags=["card"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")
_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp", "application/octet-stream")

# OCR は CPU を使い切るので同時に 1 件だけ。検出フレームは軽いので少しだけ並行を許す。
_ocr_gate = asyncio.Semaphore(1)
_frame_gate = asyncio.Semaphore(2)


# ── 入力の検証 ────────────────────────────────────────────────────────────────

def _require_enabled() -> None:
    if not bool(settings.get("enabled")):
        raise HTTPException(status_code=404, detail="card reader disabled")


def _require_local(request: Request) -> None:
    """既定ではループバックからのみ受け付ける（§12 のバインド要件に相当）。

    キオスク本体のエージェントは端末管理のため 0.0.0.0 で待ち受けている。名刺の
    画像と抽出結果が端末の外に出ないよう、この API だけ発信元を絞る。
    """
    if not bool(settings.get("bind_loopback_only")):
        return
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


async def _read_image(request: Request):
    """本文を画像として読み込む。サイズと形式を検証する。"""
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype and ctype not in _ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="unsupported media type")

    limit = int(settings.get("session.max_frame_bytes"))
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail="frame too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="bad content-length")

    body = await request.body()
    if len(body) > limit:
        raise HTTPException(status_code=413, detail="frame too large")
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    image = decode_image(body)
    if image is None:
        raise HTTPException(status_code=400, detail="undecodable image")
    return image


# ── 状態 ──────────────────────────────────────────────────────────────────────

@router.get("/status")
async def card_status(request: Request):
    """名刺読み取りが使えるかと、画面が必要とするしきい値を返す。

    キオスクは起動時にこれを見て、使えないときは導線そのものを出さない。
    """
    _require_local(request)
    enabled = bool(settings.get("enabled"))
    engine = get_engine()
    try:
        ok, detail = engine.available()
    except Exception as e:                      # モデル破損などで落ちないように
        ok, detail = False, type(e).__name__

    return {
        "available": enabled and ok,
        "enabled": enabled,
        "engine": engine.name,
        "detail": detail,
        "engines": describe_all(),
        "dictionaries": dicts.summary(),
        "config_notes": settings.notes(),
        "capture": {
            "detect_interval_ms": int(settings.get("camera.detect_interval_ms")),
            "detect_frame_max_width": int(settings.get("camera.detect_frame_max_width")),
            "capture_max_width": int(settings.get("camera.capture_max_width")),
            "stable_frames": int(settings.get("quality.stable_frames")),
        },
        "confidence": {
            "ok": float(settings.get("confidence.ok")),
            "warn": float(settings.get("confidence.warn")),
        },
        "guidance": {k: {"ja": v[0], "en": v[1]} for k, v in GUIDANCE.items()},
        "fields": list(FIELD_NAMES),
        "sessions": session_mod.store.count(),
    }


# ── セッション ────────────────────────────────────────────────────────────────

@router.post("/session")
async def card_session_start(request: Request):
    _require_enabled()
    _require_local(request)
    session = session_mod.store.start()
    log.info("[card] session started (active=%d)", session_mod.store.count())
    return {
        "session_id": session.id,
        "detect_interval_ms": int(settings.get("camera.detect_interval_ms")),
        "detect_frame_max_width": int(settings.get("camera.detect_frame_max_width")),
        "capture_max_width": int(settings.get("camera.capture_max_width")),
        "ttl_sec": int(settings.get("session.ttl_sec")),
    }


@router.delete("/session/{sid}")
async def card_session_drop(sid: str, request: Request):
    _require_local(request)
    if not _SESSION_ID_RE.match(sid or ""):
        raise HTTPException(status_code=400, detail="invalid session id")
    dropped = session_mod.store.drop(sid)
    log.info("[card] session dropped=%s (active=%d)", dropped, session_mod.store.count())
    return {"dropped": dropped}


# ── フレーム処理 ──────────────────────────────────────────────────────────────

@router.post("/frame")
async def card_frame(request: Request, session_id: str = ""):
    """検出用フレームを 1 枚処理して、案内文言と枠の位置を返す。"""
    _require_enabled()
    _require_local(request)
    session = _require_session(session_id)

    image = await _read_image(request)
    max_w = int(settings.get("camera.detect_frame_max_width"))
    image, _scale = limit_width(image, max_w)

    started = time.perf_counter()
    async with _frame_gate:
        payload = await asyncio.to_thread(session_mod.process_frame, session, image)
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return payload


@router.post("/capture")
async def card_capture(request: Request, session_id: str = "", force: int = 0):
    """撮影フレームを受け取り、OCR と項目抽出まで行う。

    検出はこの高解像度フレームでやり直す（検出ループの縮小フレームの四隅をそのまま
    拡大するより正確）。見つからなければ画像全体を名刺として扱う。

    force=1 は利用者が「撮影する」を押した場合。読み取れた内容に関わらず確認画面へ
    進む（自動撮影のときだけ、何も読めていなければ黙って撮り直す）。
    """
    _require_enabled()
    _require_local(request)
    session = _require_session(session_id)

    image = await _read_image(request)
    max_w = int(settings.get("camera.capture_max_width"))
    image, _scale = limit_width(image, max_w)

    started = time.perf_counter()
    try:
        async with _ocr_gate:
            result = await asyncio.wait_for(
                asyncio.to_thread(_read_with_detection, image),
                timeout=float(settings.get("ocr.timeout_sec")) + 10.0,
            )
    except OcrUnavailable as e:
        log.warning("[card] ocr unavailable: %s", e)
        raise HTTPException(status_code=503, detail="ocr unavailable")
    except asyncio.TimeoutError:
        log.warning("[card] ocr timed out")
        raise HTTPException(status_code=504, detail="ocr timeout")

    if result is None:
        raise HTTPException(status_code=422, detail="could not read card")

    accepted, reason = evaluate_acceptance(result.fields, result.overall)
    max_attempts = max(1, int(settings.get("accept.max_attempts")))
    session.attempts += 1
    attempt_no = session.attempts

    # 何も読めていなければ確認画面へ進まず、画面側が黙って撮り直す。
    # ただし撮り直しの上限に達したら、取れた分だけで確認画面へ進む
    # （利用者が手で入力できるようにする。無限に撮り直さない）。
    # 手動撮影(force=1)は利用者の明示的な操作なので、内容に関わらず進む。
    proceed = bool(accepted or force or attempt_no >= max_attempts)

    session.result = result
    session.edited.clear()
    session.reset_tracking()
    session.awaiting_confirm = proceed
    if proceed:
        session.attempts = 0
    session.touch()

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    log.info(
        "[card] capture done in %.0fms (variant=%s lines=%d filled=%d/%d "
        "accepted=%s reason=%s proceed=%s attempt=%d/%d)",
        elapsed, result.variant, len(result.lines),
        result.fields.filled_count(), len(FIELD_NAMES),
        accepted, reason, proceed, attempt_no, max_attempts,
    )
    payload = _result_payload(session, elapsed)
    payload.update({
        "accepted": accepted,
        "accept_reason": reason,
        "proceed": proceed,
        "attempt": attempt_no,
        "max_attempts": max_attempts,
        "retry_cooldown_sec": float(settings.get("accept.retry_cooldown_sec")),
    })
    return payload


def _read_with_detection(image):
    from card.detect import detect_card
    detection = detect_card(image)
    return read_card(image, detection.quad if detection else None)


def _result_payload(session: session_mod.Session, elapsed_ms: float) -> dict:
    result = session.result
    assert result is not None
    return {
        "session_id": session.id,
        "fields": result.fields.as_dict(),
        "ocr_confidence": result.overall,
        "variant": result.variant,
        "variants_tried": result.tried,
        "engine": result.engine,
        "rotation": result.rotation,
        "upscale": round(result.upscale, 2),
        "card_size": {"width": result.card_size[0], "height": result.card_size[1]},
        "card_image": (
            "data:image/jpeg;base64," + base64.b64encode(result.card_jpeg).decode("ascii")
            if result.card_jpeg else None
        ),
        "lines": lines_payload(result.lines),
        "timings_ms": {**result.timings_ms, "total": elapsed_ms},
        "confidence": {
            "ok": float(settings.get("confidence.ok")),
            "warn": float(settings.get("confidence.warn")),
        },
    }


@router.get("/session/{sid}/result")
async def card_result(sid: str, request: Request):
    """直前の読み取り結果をもう一度取得する（画面の再描画用）。"""
    _require_local(request)
    session = _require_session(sid)
    if session.result is None:
        raise HTTPException(status_code=404, detail="no result")
    return _result_payload(session, 0.0)


# ── 確定 ──────────────────────────────────────────────────────────────────────

class ConfirmBody(BaseModel):
    """確認画面で利用者が確定した値。

    送られてくるのは画面に出ていた項目だけ。ここに無い項目は OCR の値をそのまま使う。
    """
    values: dict[str, str] = PydField(default_factory=dict)


@router.post("/session/{sid}/confirm")
async def card_confirm(sid: str, body: ConfirmBody, request: Request):
    """利用者の確認を経た値を確定し、セッション（＝画像）を破棄する。

    返す JSON がそのまま受付フォームに入る。端末にもサーバにも保存しない。
    """
    _require_enabled()
    _require_local(request)
    session = _require_session(sid)
    if session.result is None:
        raise HTTPException(status_code=409, detail="nothing captured")

    original = session.result.fields
    values: dict[str, str] = {}
    edited: list[str] = []

    for name in FIELD_NAMES:
        ocr_value = (original.get(name).value or "").strip()
        if name in body.values:
            given = str(body.values[name]).strip()[:200]
            values[name] = given
            if given != ocr_value:
                edited.append(name)
        else:
            values[name] = ocr_value

    unknown = [k for k in body.values if k not in FIELD_NAMES]
    if unknown:
        raise HTTPException(status_code=400, detail="unknown field")

    payload = {
        **values,
        "ocr_confidence": session.result.overall,
        "confirmed_by_user": True,
        "edited_fields": edited,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    # 確定した時点で画像も抽出結果も捨てる。保存はしない（§12）。
    session_mod.store.drop(sid)
    log.info("[card] confirmed (edited=%d/%d fields, active=%d)",
             len(edited), len(FIELD_NAMES), session_mod.store.count())
    return payload


# ── 保守 ──────────────────────────────────────────────────────────────────────

async def purge_loop() -> None:
    """期限切れセッションを定期的に片付ける常駐タスク。"""
    while True:
        try:
            removed = session_mod.store.purge()
            if removed:
                log.info("[card] purged %d expired session(s)", removed)
        except Exception:
            log.exception("[card] purge failed")
        await asyncio.sleep(30)


def warmup_sync() -> None:
    """起動時にモデルを読み込んで初回の待ち時間を減らす（失敗しても無視）。"""
    try:
        if not bool(settings.get("enabled")):
            return
        engine = get_engine()
        ok, detail = engine.available()
        if not ok:
            log.info("[card] ocr not available: %s", detail)
            return
        started = time.perf_counter()
        engine.warmup()
        log.info("[card] ocr warmed up in %.0fms (engine=%s)",
                 (time.perf_counter() - started) * 1000, engine.name)
    except Exception as e:
        log.info("[card] warmup skipped: %s", type(e).__name__)
