"""分析ログの固定語彙（ホワイトリスト）。

**ここに無い値は受け付けない。** 自由入力の項目を作らないことで、
入力値・氏名・担当者名などが分析ログへ紛れ込む経路を構造的に塞ぐ。

キオスク側の同じ語彙は `kiosk_agent/static/analytics.js` の `VOCAB` にある。
**片方だけ増やすとイベントが 1 件単位で reject されるので、必ず両方に足すこと。**
（reject されても受付操作は止まらない＝ログが1件落ちるだけ）
"""

EVENT_SOURCES = {"browser", "backend", "device_agent"}

# ── セッション ───────────────────────────────────────────────────────────────
SESSION_EVENTS = {
    "session_started",
    "session_completed",
    "session_cancelled",
    "session_abandoned",
    "session_timeout",
    "session_app_error",
    "session_device_restarted",
}

# 終了イベント → reception_sessions.outcome
OUTCOME_BY_EVENT = {
    "session_completed": "completed",
    "session_cancelled": "cancelled",
    "session_abandoned": "abandoned",
    "session_timeout": "timeout",
    "session_app_error": "app_error",
    "session_device_restarted": "device_restarted",
}
OUTCOMES = set(OUTCOME_BY_EVENT.values())
# 離脱扱い（離脱率の分子）
ABANDON_OUTCOMES = {"abandoned", "timeout"}

SCREEN_EVENTS = {"screen_viewed", "screen_exited"}

ACTION_EVENTS = {
    "action_selected",
    "back_selected",
    "help_opened",
    "retry_selected",
    "assistance_requested",
    "noninteractive_area_tapped",
}

INPUT_EVENTS = {"input_started", "input_completed"}

ERROR_EVENTS = {
    "validation_error",
    "error_recovered",
    "api_error",
    "network_error",
    "unexpected_error",
}
# エラー率の分子に数えるもの（error_recovered は「回復」なので数えない）
ERROR_COUNTED = {"validation_error", "api_error", "network_error", "unexpected_error"}

NOTIFY_EVENTS = {
    "notification_requested",
    "notification_succeeded",
    "notification_failed",
    "notification_retried",
    "staff_responded",
}

FEEDBACK_EVENTS = {
    "feedback_viewed",
    "feedback_submitted",
    "feedback_skipped",
    "feedback_timeout",
}

EVENT_NAMES = (
    SESSION_EVENTS
    | SCREEN_EVENTS
    | ACTION_EVENTS
    | INPUT_EVENTS
    | ERROR_EVENTS
    | NOTIFY_EVENTS
    | FEEDBACK_EVENTS
)

# ── 画面 ─────────────────────────────────────────────────────────────────────
# kiosk.html の go() 内部名を snake_case に正規化したもの。
# kiosk_settings(スタッフ専用・Wi-Fiパスワード等を含む)は意図的に含めない＝記録しない。
SCREEN_IDS = {
    "idle",
    "welcome",
    "top",
    "reception",
    "locker_mode",
    "locker",
    "delivery",
    "calling",
    "result_ok",
    "result_phone",
    "result_decline",
    "complete",
    "feedback",
    "pending",
    "suspended",
    "card_capture",
}

# ── 入力項目 ─────────────────────────────────────────────────────────────────
FIELD_IDS = {
    "visitor_name",
    "company",
    "department",
    "staff",
    "purpose",
    "locker_pin",
    "locker_select",
    "delivery_method",
    "qr_scan",
    "card_capture",
    "feedback",
}

# ── エラーコード ─────────────────────────────────────────────────────────────
ERROR_CODES = {
    "required",
    "too_long",
    "invalid_format",
    "pin_mismatch",
    "pin_invalid",
    "no_locker_available",
    "locker_occupied",
    "locker_open_failed",
    "network_unreachable",
    "api_4xx",
    "api_5xx",
    "timeout",
    "camera_unavailable",
    "qr_unsupported",
    "card_unavailable",
    "card_not_detected",
    "agent_unreachable",
    "unknown",
}

INPUT_METHODS = {"touch", "keyboard", "qr", "card", "voice", "smartphone", "auto"}
ENTRY_METHODS = {"touch", "qr", "card", "voice", "smartphone"}

RESULTS = {
    "succeeded",
    "failed",
    "cancelled",
    "timeout",
    "skipped",
    "accepted",
    "phone",
    "declined",
}

# ── アンケート ───────────────────────────────────────────────────────────────
# question_id -> 許可する answer_code
SURVEY_ANSWERS = {
    "clarity": {"very_clear", "clear", "neutral", "unclear", "very_unclear"},
    "confidence": {"very_secure", "secure", "neutral", "slightly_anxious", "very_anxious"},
    "assistance": {"none", "received"},
}
QUESTION_IDS = set(SURVEY_ANSWERS)
# reception_sessions のどの列へ格納するか
SURVEY_COLUMN = {
    "clarity": "answer_clarity",
    "confidence": "answer_confidence",
    "assistance": "answer_assistance",
}

# ── 通知経路（element_id に入れる固定語） ───────────────────────────────────
NOTIFY_CHANNELS = {"slack", "push", "webhook", "chatwork", "email", "any"}

# ── 端末イベント ─────────────────────────────────────────────────────────────
DEVICE_EVENT_NAMES = {
    "device_boot",
    "device_shutdown",
    "device_restart",
    "agent_started",
    "agent_stopped",
    "browser_started",
    "app_started",
    "page_reloaded",
    "app_crashed",
    "online",
    "offline",
    "network_recovered",
    "log_dropped",
}
# 端末再起動とみなすイベント（未終了セッションの outcome 判定に使う）
DEVICE_RESTART_EVENTS = {"device_boot", "device_restart", "agent_started"}

DEVICE_DETAIL_CODES = {
    "systemd_stop",
    "clean_shutdown",
    "unclean_shutdown",
    "heartbeat_stale",
    "upload_failed",
    "upload_recovered",
    "spool_overflow",
    "browser_overflow",
    "unknown",
}


def is_error_event(event_name: str) -> bool:
    return event_name in ERROR_COUNTED
