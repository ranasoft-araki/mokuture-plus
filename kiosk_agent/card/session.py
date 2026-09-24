"""読み取りセッションの状態管理。

1 回の「名刺をかざす → 確認 → 確定 or やり直し」をセッションとして持つ。
セッションはプロセスのメモリ上にだけ存在し、ディスクにも DB にも書かない。
確定・キャンセル・タイムアウトのいずれでも必ず破棄される（§12）。

セッションが保持するもの:
  - 直前フレームの四隅（静止判定に使う）
  - 条件を満たした連続フレーム数（自動撮影の閾値）
  - 直近の読み取り結果（確認画面に出す項目と補正後画像）

画像そのものはフレーム処理の間だけメモリに載り、処理が終われば参照を捨てる。
確認画面用の補正後画像だけは JPEG として結果に残るが、これもセッション破棄で消える。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from card import settings
from card.detect import detect_card
from card.pipeline import ReadResult
from card.quality import evaluate, message
from card.types import CaptureState, FrameMetrics, Quad


@dataclass
class Session:
    id: str
    created_at: float
    touched_at: float
    prev_quad: Quad | None = None
    # 直前のフレームで四隅を「何から」決めたか（"edge" = 紙の縁 / "text" = 文字）。
    # **これを持たないと、由来が切り替わっただけで動いたと判定されてしまう。**
    # 文字のかたまりの四隅は名刺の縁より内側なので、静止したままでも
    # 文字→縁 の切り替わりで四隅の平均移動量が 0.163（上限 0.030）まで跳ねる。
    # 実機ではここで静止カウントが毎回ゼロに戻り、撮影に進めなかった。
    prev_source: str | None = None
    steady_count: int = 0
    state: CaptureState = "no_card"
    frames: int = 0
    last_capture_at: float = 0.0
    result: ReadResult | None = None
    # 自動での撮り直しの回数。確認画面へ進んだ時点で数えるのをやめる。
    attempts: int = 0
    # 1 行も読めなかった撮影の回数。名刺がまだ写っていないフレームを撮っただけ
    # なので撮り直しとは別に数える（api.card_capture の説明を参照）。
    blank_attempts: int = 0
    # ボケていて OCR へ進めなかった回数。撮り直しの回数（attempts）とは別に数える。
    # 規定回数を超えたら弾くのをやめる（どうしても合焦しない端末で出口が
    # 無くならないようにする）。読めた撮影が 1 回あればゼロに戻す。
    blur_rejects: int = 0
    # 確認画面を表示中（＝これ以上자動撮影しない）。撮り直しで False に戻す。
    awaiting_confirm: bool = False
    # 確認画面で利用者が直した項目名（元の OCR 値と区別して持つ）
    edited: dict[str, str] = field(default_factory=dict)
    # 1 セッションのフレーム処理を直列化する。ブラウザは 1 枚ずつ待って送るが、
    # 取りこぼしや再送で同時に届くと、静止フレーム数の数え上げが壊れて
    # 意図しない自動撮影につながる。
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def touch(self) -> None:
        self.touched_at = time.monotonic()

    def clear_result(self) -> None:
        self.result = None
        self.edited.clear()
        self.awaiting_confirm = False

    def reset_tracking(self) -> None:
        self.prev_quad = None
        self.prev_source = None
        self.steady_count = 0
        self.state = "no_card"


class SessionStore:
    """セッションの入れ物。件数と寿命に上限を置く。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def _ttl(self) -> float:
        return float(settings.get("session.ttl_sec"))

    def start(self) -> Session:
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            limit = int(settings.get("session.max_sessions"))
            while len(self._sessions) >= max(1, limit):
                # いちばん古いものから捨てる（キオスクは同時に 1 人しか使わない）
                oldest = min(self._sessions.values(), key=lambda s: s.touched_at)
                self._sessions.pop(oldest.id, None)
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
            session = self._sessions.pop(sid, None)
        if session is not None:
            session.clear_result()
            return True
        return False

    def purge(self) -> int:
        now = time.monotonic()
        with self._lock:
            return self._purge_locked(now)

    def _purge_locked(self, now: float) -> int:
        ttl = self._ttl()
        # ttl=0 を「即座に破棄」として扱えるよう、境界は含める
        expired = [s for s in self._sessions.values() if now - s.touched_at >= ttl]
        for s in expired:
            self._sessions.pop(s.id, None)
            s.clear_result()
        return len(expired)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            for s in self._sessions.values():
                s.clear_result()
            self._sessions.clear()


store = SessionStore()


def process_frame(session: Session, bgr) -> dict:
    """検出用フレーム 1 枚を処理して、画面に返す状態を作る。

    自動撮影の判定はここで行うが、実際の撮影（高解像度フレームの取得）はブラウザ側の
    仕事。`should_capture` が真になったら、ブラウザが撮影して /card/capture へ送る。
    """
    with session.lock:
        return _process_frame_locked(session, bgr)


def _process_frame_locked(session: Session, bgr) -> dict:
    q = settings.get("quality")
    session.frames += 1

    detection = detect_card(bgr, session.prev_quad)
    state, metrics = evaluate(bgr, detection, session.prev_quad, session.prev_source)

    if state == "steady":
        session.steady_count += 1
    else:
        session.steady_count = 0

    session.prev_quad = detection.quad if detection else None
    session.prev_source = detection.source if detection else None
    session.state = state
    session.touch()

    need = int(q["stable_frames"])
    cooldown = float(q["capture_cooldown_sec"])
    elapsed = time.monotonic() - session.last_capture_at
    # 確認画面を出している間だけ撮影を止める。読み取りに失敗した結果が
    # 残っているときは、撮り直せるように止めない。
    should_capture = (
        session.steady_count >= need
        and elapsed > cooldown
        and not session.awaiting_confirm
    )
    if should_capture:
        session.last_capture_at = time.monotonic()
        session.steady_count = 0

    ja, en = message("capturing" if should_capture else state)
    h, w = bgr.shape[:2]
    return {
        "session_id": session.id,
        "state": "capturing" if should_capture else state,
        "message": ja,
        "message_en": en,
        "should_capture": should_capture,
        "steady": session.steady_count,
        "steady_needed": need,
        # 四隅は「送られてきたフレームの幅・高さに対する比」で返す。ブラウザ側の
        # 表示解像度が違っても、そのまま掛け算で枠を描ける。
        "quad": _quad_ratio(detection.quad, w, h) if detection else None,
        # 四隅を何から決めたか（"edge"=紙の縁 / "text"=文字のかたまり / None=検出なし）。
        # 画面のデバッグ表示がこれを出す。読み取れないときに「縁が出ていないのか、
        # 文字も拾えていないのか」が分かると、直すべき場所が一つに絞れる。
        "source": detection.source if detection else None,
        "metrics": _metrics_payload(metrics),
    }


def _quad_ratio(quad: Quad, w: int, h: int) -> list[list[float]]:
    return [[round(x / w, 4), round(y / h, 4)] for x, y in quad]


def _metrics_payload(m: FrameMetrics) -> dict:
    return {
        "focus": round(m.focus, 1),
        "brightness": round(m.brightness, 1),
        "glare": round(m.glare_ratio, 4),
        "area": round(m.area_ratio, 4),
        "fill": round(m.fill_ratio, 4),
        "aspect": round(m.aspect, 3),
        "text_regions": m.text_regions,
        "motion": round(m.motion, 4),
        # 以下は文字ベースの検出でだけ入る。大きさの判定がこの 2 つで決まるので、
        # 「近づけてください」が出続ける原因を画面から読めるようにしておく。
        "text_height": round(m.text_height, 1),
        "text_clipped": m.text_clipped,
    }
