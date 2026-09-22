"""音声入力セッション(1 人の来訪者の一連の入力)。

1 セッション = 「音声で入力」を押してから、受付フォームへ戻るまで。その中で項目
(会社名 → お名前 → 担当者)ごとに録音と認識を繰り返す。

状態はプロセスのメモリ上にだけ持つ。ディスクにも DB にも書かない。確定・キャンセル・
タイムアウトのいずれでも必ず破棄される(§11)。破棄のとき PCM と認識テキストの参照を
明示的に捨てる。

録音と認識は 1 本のワーカースレッドで進め、画面は `/voice/session/{id}/state` を
ポーリングして「聞き取り中 / 認識しています」と音量バーを描く。処理中に画面が
止まって見えないようにするため(§5)、状態は録音中も 20ms ごとに更新される。
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field as dc_field

from voice import (capture, engines, extract, metrics, quality, settings, textnorm,
                   vad, vosk_engine, whisper_cpp)
from voice.types import Phase, Recognition

log = logging.getLogger(__name__)

# 認識は CPU を使い切るので同時に 1 件だけ(Pi 5 の 4 コアを食い合わせない)。
_recognition_gate = threading.Semaphore(1)


class Busy(RuntimeError):
    """すでに録音・認識が走っている。"""


@dataclass
class Session:
    id: str
    created_at: float
    touched_at: float
    phase: Phase = "idle"
    field: str | None = None
    # 画面の音量バー(0.0〜1.0)と実測 dBFS。
    level: float = 0.0
    db: float = -100.0
    # 項目ごとの再入力回数(§12 の「項目別の再入力率」)。
    retry_count: dict[str, int] = dc_field(default_factory=dict)
    result: Recognition | None = None
    error_code: str | None = None
    # 「音声をやめてタッチへ」が押されたか。集計にだけ使う。
    fell_back: bool = False

    # 一文の名乗り(field="reception")で使う。誰がいるかは画面から渡してもらう。
    _staff_names: list[str] = dc_field(default_factory=list)
    _purposes: list[str] = dc_field(default_factory=list)

    _worker: threading.Thread | None = None
    _cancel: threading.Event = dc_field(default_factory=threading.Event)
    _stop: threading.Event = dc_field(default_factory=threading.Event)
    _lock: threading.Lock = dc_field(default_factory=threading.Lock)

    def touch(self) -> None:
        self.touched_at = time.monotonic()

    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # ── 画面へ返す状態 ────────────────────────────────────────────────────
    def state(self) -> dict:
        r = self.result
        return {
            "session_id": self.id,
            "phase": self.phase,
            "field": self.field,
            "level": round(self.level, 3),
            "db": round(self.db, 1),
            "retry_count": self.retry_count.get(self.field or "", 0),
            "error_code": self.error_code,
            "result": _result_payload(r) if r is not None else None,
        }

    # ── 操作 ──────────────────────────────────────────────────────────────
    def listen(self, field_name: str, *, staff: list[str] | None = None,
               purposes: list[str] | None = None) -> None:
        """1 項目ぶんの録音と認識を始める。すぐ返り、進行は state() で見る。

        staff / purposes は field="reception"(一文の名乗り)でだけ使う。**誰がいるか**
        の出どころは管理画面の社員マスターで、画面がそれを持っているので渡してもらう。
        音声サービス側は読み仮名だけを端末ローカルから補う。
        """
        with self._lock:
            if self.busy():
                raise Busy("録音中です")
            self._cancel.clear()
            self._stop.clear()
            self.field = field_name
            self.phase = "arming"
            self.level = 0.0
            self.db = -100.0
            self.error_code = None
            self.result = None
            self.touch()
            self._staff_names = list(staff or [])
            self._purposes = list(purposes or [])
            self._worker = threading.Thread(
                target=self._run, args=(field_name,), name=f"voice-{field_name}", daemon=True,
            )
            self._worker.start()

    def stop(self) -> None:
        """「入力を終了」。そこまでを発話として確定する。"""
        self._stop.set()
        self.touch()

    def cancel(self) -> None:
        """「キャンセル」。録音も認識も捨てる。"""
        self._cancel.set()
        self._stop.set()
        self.touch()

    def note_retry(self) -> int:
        """同じ項目をもう一度話す。再入力率の分母になる。"""
        f = self.field or ""
        self.retry_count[f] = self.retry_count.get(f, 0) + 1
        self.touch()
        return self.retry_count[f]

    def clear_result(self) -> None:
        """認識テキストを捨てる。破棄・やり直しのたびに呼ぶ(§11)。"""
        self.result = None
        self.error_code = None

    # ── 本体 ──────────────────────────────────────────────────────────────
    def _host_pass(self, seg, engine_name: str) -> tuple[str, list[str]]:
        """担当者の語彙だけで decode し直す(2 パス目)。(文字起こし, 信頼できた語)。

        Vosk のときだけ。whisper には語彙を絞る仕組みが無い。担当者一覧が空の端末
        (社員マスター未設定)では何もしない。
        """
        if engine_name != vosk_engine.ENGINE_NAME or not self._staff_names:
            return "", []
        if not settings.get("vosk.grammar"):
            return "", []
        started = time.monotonic()
        try:
            text, sure = vosk_engine.transcribe_vocabulary(seg, self._staff_names)
        except Exception as e:
            log.info("[voice] 担当者パスを飛ばしました: %s", type(e).__name__)
            return "", []
        log.info("[voice] 担当者パス %dms (候補 %d)",
                 int((time.monotonic() - started) * 1000), len(sure))
        return text, sure

    def _run(self, field_name: str) -> None:
        fcfg = settings.field_cfg(field_name)
        max_sec = float(fcfg.get("max_record_sec") or settings.get("vad.max_record_sec"))
        quiet_sec = fcfg.get("silence_sec")
        # 項目ごとにエンジンが違う。一文の名乗りは Vosk の方が読みを当てる
        # (voice/engines.py に比較表)。
        engine = engines.pick(field_name)
        engine_name = engine.ENGINE_NAME
        model = engine.model_name()
        seg = None

        try:
            try:
                stream = capture.open_stream()
            except capture.CaptureUnavailable as e:
                self._fail("mic_unavailable", engine_name, model, 0, 0, 0, str(e))
                return
            except capture.CaptureFailed as e:
                self._fail("mic_error", engine_name, model, 0, 0, 0, str(e))
                return

            self.phase = "listening"
            try:
                seg = vad.record_utterance(
                    stream,
                    max_record_sec=max_sec,
                    silence_sec=float(quiet_sec) if quiet_sec else None,
                    on_level=self._on_level,
                    should_cancel=self._cancel.is_set,
                    should_stop=self._stop.is_set,
                    on_speech_start=self._on_speech_start,
                )
            except capture.CaptureFailed as e:
                self._fail("mic_error", engine_name, model, 0, 0, 0, str(e))
                return
            finally:
                stream.close()
                self.level = 0.0

            # ここが「発話終了」。ここから結果表示までが §3-1 の計測対象。
            speech_end = time.monotonic()

            if self._cancel.is_set():
                self.phase = "cancelled"
                metrics.record({
                    "sessionId": self.id, "screenId": metrics.SCREEN_IDS.get(field_name, field_name),
                    "model": model, "engine": engine_name, "result": "cancel",
                    "audioDurationMs": seg.total_ms, "recognitionDurationMs": 0,
                    "retryCount": self.retry_count.get(field_name, 0), "errorCode": None,
                })
                return

            if seg.stop_reason == "no_speech" or seg.speech_ms <= 0:
                self._fail("no_speech", engine_name, model, seg.total_ms, 0,
                           int((time.monotonic() - speech_end) * 1000), stop_reason=seg.stop_reason)
                return

            self.phase = "recognizing"
            with _recognition_gate:
                if self._cancel.is_set():
                    self.phase = "cancelled"
                    return
                try:
                    tr = engine.transcribe(seg)
                except whisper_cpp.EngineTimeout:
                    self._fail("timeout", engine_name, model, seg.total_ms, 0,
                               int((time.monotonic() - speech_end) * 1000), stop_reason=seg.stop_reason)
                    return
                except (whisper_cpp.EngineUnavailable, vosk_engine.EngineUnavailable) as e:
                    self._fail("engine_unavailable", engine_name, model, seg.total_ms, 0,
                               int((time.monotonic() - speech_end) * 1000), str(e), seg.stop_reason)
                    return
                except Exception as e:
                    log.warning("[voice] 認識に失敗: %s", type(e).__name__)
                    self._fail("internal", engine_name, model, seg.total_ms, 0,
                               int((time.monotonic() - speech_end) * 1000), stop_reason=seg.stop_reason)
                    return

            normalized = textnorm.normalize(field_name, tr.text)
            extracted = None
            if field_name == "reception":
                # 2 パス目。担当者の語彙だけで decode し直す(一般語の言語モデルは
                # 固有名詞に弱く、「服部」が「酉」「都立」に化ける)。**失敗しても
                # 1 パス目の結果は使える**ので、ここで握りつぶす。
                grammar_text, host_tokens = self._host_pass(seg, engine_name)
                # ここに LLM は使わない(voice/extract.py の冒頭に理由)。規則と
                # 名簿の読み合わせだけなので、実測で 1 ミリ秒未満で終わる。
                try:
                    extracted = extract.extract(
                        tr.text, extract.build_staff(self._staff_names), self._purposes,
                        grammar_text=grammar_text, host_tokens=host_tokens,
                    ).as_dict()
                except Exception as e:
                    # 抽出に失敗しても文字起こしは出す。画面で打ち直せる。
                    log.warning("[voice] 項目の取り出しに失敗: %s", type(e).__name__)
            verdict = quality.judge(seg, tr, normalized)
            verdict.signals["stop_reason"] = seg.stop_reason
            total_ms = int((time.monotonic() - speech_end) * 1000)

            self.result = Recognition(
                extracted=extracted,
                field=field_name,
                text=normalized,
                raw_text=textnorm.normalize_common(tr.text),
                accepted=verdict.accepted,
                tone=verdict.tone,
                error_code=verdict.code,
                engine=tr.engine,
                model_name=tr.model_name,
                audio_ms=seg.total_ms,
                recognition_ms=tr.recognition_ms,
                total_ms=total_ms,
                stop_reason=seg.stop_reason,
                signals=verdict.signals,
            )
            self.error_code = verdict.code
            self.phase = "done"

            metrics.record({
                "sessionId": self.id,
                "screenId": metrics.SCREEN_IDS.get(field_name, field_name),
                "model": tr.model_name,
                "engine": tr.engine,
                "audioDurationMs": seg.total_ms,
                "recognitionDurationMs": tr.recognition_ms,
                "totalMs": total_ms,
                "result": "success" if verdict.accepted else "error",
                "accepted": verdict.accepted,
                "retryCount": self.retry_count.get(field_name, 0),
                "errorCode": verdict.code,
                "stopReason": seg.stop_reason,
            })
            log.info("[voice] %s: %s (%dms / 音声 %dms / %s)",
                     field_name, "ok" if verdict.accepted else verdict.code,
                     tr.recognition_ms, seg.total_ms, tr.model_name)
        except Exception:
            log.exception("[voice] セッションワーカーが落ちました")
            self.phase = "error"
            self.error_code = "internal"
        finally:
            # 音声はここで必ず捨てる(§11)。
            if seg is not None:
                seg.clear()
            self.touch()

    def _on_level(self, level: float, db: float) -> None:
        self.level = level
        self.db = db

    def _on_speech_start(self) -> None:
        self.phase = "speaking"
        self.touch()

    def _fail(self, code: str, engine: str, model: str, audio_ms: int,
              rec_ms: int, total_ms: int, detail: str = "", stop_reason=None) -> None:
        self.phase = "error"
        self.error_code = code
        self.result = None
        if detail:
            # detail は機器・設定のメッセージのみ。認識結果は入らない。
            log.info("[voice] %s: %s", code, detail)
        metrics.record({
            "sessionId": self.id,
            "screenId": metrics.SCREEN_IDS.get(self.field or "", self.field or "unknown"),
            "model": model,
            "engine": engine,
            "audioDurationMs": audio_ms,
            "recognitionDurationMs": rec_ms,
            "totalMs": total_ms,
            "result": "error",
            "accepted": False,
            "retryCount": self.retry_count.get(self.field or "", 0),
            "errorCode": code,
            "stopReason": stop_reason,
        })


def _result_payload(r: Recognition) -> dict:
    return {
        "field": r.field,
        "text": r.text,
        "raw_text": r.raw_text,
        "accepted": r.accepted,
        "tone": r.tone,
        "error_code": r.error_code,
        "engine": r.engine,
        "model": r.model_name,
        "audio_ms": r.audio_ms,
        "recognition_ms": r.recognition_ms,
        "total_ms": r.total_ms,
        "stop_reason": r.stop_reason,
        "signals": r.signals,
        "candidates": r.candidates,
        "extracted": r.extracted,
    }


class SessionStore:
    """セッションの入れ物。件数と寿命に上限を置く(名刺読み取りと同じ作法)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def _ttl(self) -> float:
        return float(settings.get("session.ttl_sec"))

    def start(self) -> Session:
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            limit = max(1, int(settings.get("session.max_sessions")))
            while len(self._sessions) >= limit:
                oldest = min(self._sessions.values(), key=lambda s: s.touched_at)
                self._drop_locked(oldest.id)
            sid = secrets.token_urlsafe(16)
            session = Session(id=sid, created_at=now, touched_at=now)
            self._sessions[sid] = session
            return session

    def get(self, sid: str) -> Session | None:
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            session = self._sessions.get(sid)
            if session is not None:
                session.touched_at = now
            return session

    def drop(self, sid: str) -> bool:
        with self._lock:
            return self._drop_locked(sid)

    def _drop_locked(self, sid: str) -> bool:
        session = self._sessions.pop(sid, None)
        if session is None:
            return False
        session.cancel()
        session.clear_result()
        return True

    def purge(self) -> int:
        now = time.monotonic()
        with self._lock:
            return self._purge_locked(now)

    def _purge_locked(self, now: float) -> int:
        ttl = self._ttl()
        expired = [s for s in self._sessions.values()
                   if now - s.touched_at >= ttl and not s.busy()]
        for s in expired:
            self._sessions.pop(s.id, None)
            s.cancel()
            s.clear_result()
        return len(expired)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            for s in list(self._sessions.values()):
                s.cancel()
                s.clear_result()
            self._sessions.clear()


store = SessionStore()
