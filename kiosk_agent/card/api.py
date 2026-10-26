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

from card import dicts, dump, session as session_mod, settings
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
    # フレーム保存が有効なら画面からも分かるようにする（入れっぱなしを防ぐ）。
    dump_dir = dump.target_dir()
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
        "debug_dump_dir": str(dump_dir) if dump_dir else None,
        "capture": {
            "detect_interval_ms": int(settings.get("camera.detect_interval_ms")),
            "detect_frame_max_width": int(settings.get("camera.detect_frame_max_width")),
            "capture_max_width": int(settings.get("camera.capture_max_width")),
            "stable_frames": int(settings.get("quality.stable_frames")),
        },
        "confidence": {
            "fill_min": float(settings.get("confidence.fill_min")),
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
            # ボケ続きで出口が無くならないよう、規定回数を超えたら弾かずに読む。
            allow_blurry = session.blur_rejects >= max(1, int(settings.get("accept.max_attempts")))
            detection, result, focus = await asyncio.wait_for(
                asyncio.to_thread(_detect_and_read, image, bool(force) or allow_blurry),
                timeout=float(settings.get("ocr.timeout_sec")) + 10.0,
            )
    except OcrUnavailable as e:
        log.warning("[card] ocr unavailable: %s", e)
        raise HTTPException(status_code=503, detail="ocr unavailable")
    except asyncio.TimeoutError:
        log.warning("[card] ocr timed out")
        raise HTTPException(status_code=504, detail="ocr timeout")

    if result is None and focus is not None:
        # ボケていて読まなかった。撮り直しの回数には数えない（利用者は何も
        # 間違えていない）。ブラウザは proceed=False を見て黙って撮り直す。
        session.blur_rejects += 1
        session.touch()
        log.info("[card] capture skipped: blurry card (focus=%.0f, %d 回目)",
                 focus, session.blur_rejects)
        return {
            "proceed": False,
            "accepted": False,
            "accept_reason": "blurry capture",
            "attempt": session.attempts,
            "max_attempts": max(1, int(settings.get("accept.max_attempts"))),
            "retry_cooldown_sec": float(settings.get("accept.retry_cooldown_sec")),
        }
    session.blur_rejects = 0
    if result is None:
        raise HTTPException(status_code=422, detail="could not read card")

    accepted, reason = evaluate_acceptance(result.fields, result.overall)
    max_attempts = max(1, int(settings.get("accept.max_attempts")))
    # 1 行も読めていない撮影は「名刺がまだ写っていないフレームを撮っただけ」。
    # 利用者が名刺を出す前でも、背景の文字（天井の斑点・棚・扉枠）で自動撮影が
    # 走ることがある。これを撮り直しの回数に数えると、本命の 1 枚が来る前に
    # 上限へ達し、読めていない結果のまま確認画面へ進んでしまう。
    blank = not result.lines
    if blank:
        session.blank_attempts += 1
    else:
        session.attempts += 1
    attempt_no = session.attempts

    # 何も読めていなければ確認画面へ進まず、画面側が黙って撮り直す。
    # ただし撮り直しの上限に達したら、取れた分だけで確認画面へ進む
    # （利用者が手で入力できるようにする。無限に撮り直さない）。
    # 1 行も読めない撮影が続く場合も、その 2 倍で同じように逃がす。名刺が写って
    # いないだけのことが多いが、どうしても読めない名刺のときに出口が無くなる。
    # 手動撮影(force=1)は利用者の明示的な操作なので、内容に関わらず進む。
    stuck = session.blank_attempts >= max_attempts * 2
    proceed = bool(accepted or force or stuck
                   or (not blank and attempt_no >= max_attempts))

    session.result = result
    session.edited.clear()
    session.reset_tracking()
    session.awaiting_confirm = proceed
    if proceed:
        session.attempts = 0
        session.blank_attempts = 0
    session.touch()

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    log.info(
        "[card] capture done in %.0fms (variant=%s lines=%d filled=%d/%d "
        "accepted=%s reason=%s proceed=%s attempt=%d/%d)",
        elapsed, result.variant, len(result.lines),
        result.fields.filled_count(), len(FIELD_NAMES),
        accepted, reason, proceed, attempt_no, max_attempts,
    )
    # 実機調整用（既定は無効）。**読み取りが終わってから**書き出す＝保存の失敗や
    # 遅れが読み取りに影響しない。
    dump.save_capture(image, detection, result, {
        "accepted": accepted, "accept_reason": reason, "proceed": proceed,
        "attempt": attempt_no, "max_attempts": max_attempts, "forced": bool(force),
    })

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


def _capture_focus(image, detection) -> float | None:
    """**検出できた名刺の中**のピント。名刺が見つからなければ None。

    画像全体ではなく名刺の中で測る。全体だと、名刺の無い絵（空の机・無地の壁）が
    「模様が少ない」だけでボケ扱いになり、撮り直しの行き止まりを作ってしまう。
    測り方が `quality.focus_min`（検出ループの縮小フレーム）と揃うよう、ここでも
    検出フレームと同じ幅へ落としてから測る。
    """
    if detection is None:
        return None
    import cv2
    from card.quality import region_metrics
    w = int(settings.get("camera.detect_frame_max_width"))
    h, iw = image.shape[:2]
    quad = detection.quad
    if iw > w:
        r = w / float(iw)
        image = cv2.resize(image, (w, max(2, int(h * r))), interpolation=cv2.INTER_AREA)
        quad = tuple((x * r, y * r) for x, y in quad)
    return float(region_metrics(image, quad)[0])


def _detect_and_read(image, allow_blurry: bool):
    """検出 → ピント確認 → OCR。ボケていれば OCR へ進まず (detection, None, focus)。

    OCR は 1 枚 4.5〜5.8 秒かかる。検出用フレームで合焦と判定しても、ブラウザが
    実際に撮るのは別の瞬間の別フレームなので、ボケた 1 枚が回ってくることがある。
    読む前に弾いて撮り直すほうが速い。検出は OCR と同じスレッドで 1 回だけ行い、
    その四隅をそのまま読み取りへ渡す（二度検出しない）。
    """
    from card.detect import detect_card
    detection = detect_card(image)
    focus = _capture_focus(image, detection)
    if (not allow_blurry and focus is not None
            and focus < float(settings.get("quality.capture_focus_min"))):
        return detection, None, focus
    return detection, read_card(image, detection.quad if detection else None), focus


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
            "fill_min": float(settings.get("confidence.fill_min")),
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

    # 項目ごとの確からしさも返す。**これが無いと受け取り側は「確定した値」と
    # 「大きい文字だったので氏名かもしれない、という推測」を区別できない。**
    # 氏名の抽出は、裏付け（姓辞書・メールとの一致・役職の隣）が 1 つも無いと
    # 0.45〜0.55 程度の値を返す設計で、これは confidence.warn(0.60) に届かない
    # ＝「要入力」として赤く出す前提だった。確認画面を廃止した経路では、
    # 受け取り側がこの帯を自分で見て扱いを変える必要がある。
    # 利用者が直した項目は「本人が入れた値」なので最高扱いにする。
    conf = {}
    for name in FIELD_NAMES:
        conf[name] = 1.0 if name in edited else round(original.get(name).confidence, 3)
    payload = {
        **values,
        "field_confidence": conf,
        # 氏名が決めきれなかったときの候補（value が空でもここには入る）
        "name_candidates": list(original.get("person_name").candidates or []),
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
