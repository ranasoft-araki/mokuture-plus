"""声で操作するセッション(1 人の来訪者の音声モード)。

1 セッション = 下部帯の「声で操作する」を押してから、待機画面へ戻るまで。その間、画面が
選択を待っているあいだは「その画面の言葉を 1 回聞く」を繰り返す(listen_command)。

状態はプロセスのメモリ上にだけ持つ。ディスクにも DB にも書かない。取り消し・破棄・
TTL のいずれでも音声を捨てる。

録音と認識は 1 本のワーカースレッドで進め、画面は `/voice/session/{id}/state` を
ポーリングして「聞き取り中」と音量を描く。状態は録音中も 20ms ごとに更新される。
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field as dc_field

from voice import capture, metrics, settings, vad, vosk_engine
from voice.types import CommandMatch, Phase

log = logging.getLogger(__name__)

# 認識は CPU を使うので同時に 1 件だけ(Pi の 4 コアを食い合わせない)。
_recognition_gate = threading.Semaphore(1)


class Busy(RuntimeError):
    """前の聞き取りが終わっていない。"""


@dataclass
class Session:
    id: str
    created_at: float
    touched_at: float
    phase: Phase = "idle"
    # 画面の音量バー(0.0〜1.0)と実測 dBFS。
    level: float = 0.0
    db: float = -100.0
    error_code: str | None = None
    # 直近の判定(どの選択肢か)。
    command: CommandMatch | None = None

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
        return {
            "session_id": self.id,
            "phase": self.phase,
            "level": round(self.level, 3),
            "db": round(self.db, 1),
            "error_code": self.error_code,
            "command": _command_payload(self.command) if self.command is not None else None,
        }

    # ── 操作 ──────────────────────────────────────────────────────────────
    def listen_command(self, choices: list[tuple[str, list[str]]], *, screen: str,
                       window_sec: float | None = None, fallback: bool = False) -> None:
        """画面の選択肢のどれが言われたかを 1 回だけ聞く。すぐ返り、進行は state() で見る。

        画面が切り替わったら、前の画面の語彙で聞いている途中でも**畳んでから**開け直す
        (前の語彙のまま当たると、いま見えていない画面の操作が走る)。
        fallback=True は番号で選ぶ画面(ロッカー)。vosk_engine.recognize_command を参照。
        """
        with self._lock:
            worker = self._worker if self.busy() else None
            if worker is not None:
                self._cancel.set()
                self._stop.set()
        if worker is not None:
            # 録音ループは 20ms ごとに取り消しを見る。認識中でも 1 語なら数百 ms で終わる。
            worker.join(timeout=2.0)
        with self._lock:
            if self.busy():
                raise Busy("前の聞き取りが終わっていません")
            self._cancel.clear()
            self._stop.clear()
            self.phase = "arming"
            self.level = 0.0
            self.db = -100.0
            self.error_code = None
            self.command = None
            self.touch()
            self._worker = threading.Thread(
                target=self._run_command, args=(list(choices), screen, window_sec, fallback),
                name="voice-command", daemon=True,
            )
            self._worker.start()

    def cancel(self) -> None:
        """取り消す。録音も認識も捨てる。"""
        self._cancel.set()
        self._stop.set()
        self.touch()

    def clear_result(self) -> None:
        """判定を捨てる。破棄のたびに呼ぶ。"""
        self.command = None
        self.error_code = None

    # ── 本体 ──────────────────────────────────────────────────────────────
    def _run_command(self, choices: list[tuple[str, list[str]]], screen: str,
                     window_sec: float | None, fallback: bool) -> None:
        """キーワード 1 回ぶん。録って、画面の語彙だけで decode し、選択肢を決める。

        **話しかけられなかった窓は記録しない。** 画面が選択を待っている間は窓を開け
        直し続けるので、no_speech を数えると実験ログが「誰も話していない」で埋まる。
        """
        ccfg = settings.get("command") or {}
        model = vosk_engine.model_name()
        screen_id = f"command-{screen}"
        seg = None
        try:
            try:
                stream = capture.open_stream()
            except capture.CaptureUnavailable as e:
                self._fail("mic_unavailable", screen_id, model, str(e))
                return
            except capture.CaptureFailed as e:
                self._fail("mic_error", screen_id, model, str(e))
                return

            self.phase = "listening"
            try:
                seg = vad.record_utterance(
                    stream,
                    max_record_sec=float(ccfg.get("max_record_sec") or 3.0),
                    silence_sec=float(ccfg.get("silence_sec") or 0.7),
                    start_timeout_sec=float(window_sec or ccfg.get("window_sec") or 8.0),
                    on_level=self._on_level,
                    should_cancel=self._cancel.is_set,
                    should_stop=self._stop.is_set,
                    on_speech_start=self._on_speech_start,
                )
            except capture.CaptureFailed as e:
                self._fail("mic_error", screen_id, model, str(e))
                return
            finally:
                stream.close()
                self.level = 0.0

            speech_end = time.monotonic()
            if self._cancel.is_set():
                self.phase = "cancelled"
                return
            if seg.stop_reason == "no_speech" or seg.speech_ms <= 0:
                self.phase = "error"
                self.error_code = "no_speech"
                return

            self.phase = "recognizing"
            with _recognition_gate:
                if self._cancel.is_set():
                    self.phase = "cancelled"
                    return
                try:
                    match = vosk_engine.recognize_command(seg, choices, fallback=fallback)
                except vosk_engine.EngineUnavailable as e:
                    self._fail("engine_unavailable", screen_id, model, str(e))
                    return
                except Exception as e:
                    log.warning("[voice] キーワードの認識に失敗: %s", type(e).__name__)
                    self._fail("internal", screen_id, model)
                    return
            if self._cancel.is_set():
                # 認識中に画面が切り替わった。前の画面の語彙の結果は使わない。
                self.phase = "cancelled"
                return

            total_ms = int((time.monotonic() - speech_end) * 1000)
            # 認識した語は画面へ返さない(どの選択肢か・信頼度だけ)。
            match.words = []
            self.command = match
            self.error_code = match.reason
            self.phase = "done"
            metrics.record({
                "sessionId": self.id,
                "screenId": screen_id,
                "model": model,
                "engine": vosk_engine.ENGINE_NAME,
                "audioDurationMs": seg.total_ms,
                "recognitionDurationMs": match.recognition_ms,
                "totalMs": total_ms,
                "result": "success" if match.matched else "error",
                "accepted": match.matched is not None,
                "choiceId": match.matched,
                "errorCode": match.reason,
                "stopReason": seg.stop_reason,
            })
            # 選択肢の id は画面が決めた固定語彙(「visit」「back」)なので出してよい。
            log.info("[voice] command %s: %s (%dms / 音声 %dms)", screen,
                     match.matched or match.reason, match.recognition_ms, seg.total_ms)
        except Exception:
            log.exception("[voice] キーワードのワーカーが落ちました")
            self.phase = "error"
            self.error_code = "internal"
        finally:
            # 音声はここで必ず捨てる。
            if seg is not None:
                seg.clear()
            self.touch()

    def _on_level(self, level: float, db: float) -> None:
        self.level = level
        self.db = db

    def _on_speech_start(self) -> None:
        self.phase = "speaking"
        self.touch()

    def _fail(self, code: str, screen_id: str, model: str, detail: str = "") -> None:
        self.phase = "error"
        self.error_code = code
        self.command = None
        if detail:
            # detail は機器・設定のメッセージのみ。認識結果は入らない。
            log.info("[voice] %s: %s", code, detail)
        metrics.record({
            "sessionId": self.id,
            "screenId": screen_id,
            "model": model,
            "engine": vosk_engine.ENGINE_NAME,
            "result": "error",
            "accepted": False,
            "errorCode": code,
        })


def _command_payload(c: CommandMatch) -> dict:
    # 認識した語(words)は入れない。画面が要るのは「どれが選ばれたか」だけ。
    return {
        "matched": c.matched,
        "confidence": c.confidence,
        "reason": c.reason,
        "recognition_ms": c.recognition_ms,
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
