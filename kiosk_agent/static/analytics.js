/*!
 * mokuture+ キオスク行動ログ（匿名）
 * 設計: リポジトリ直下の ANALYTICS.md
 *
 * 守ること（個人情報を保存しない）:
 *   - 入力値・氏名・会社名・担当者・QRトークン・名刺/カメラ画像・音声は **一切送らない**。
 *     `<input>` の value を読むコードはこのファイルに存在しない。
 *   - ソフトキーボードのキー（[data-pk]）と漢字変換候補（.kb-cand）はクリック記録の対象外。
 *     打鍵列から入力値が復元できてしまうため。
 *   - スタッフ専用の設定画面（kiosk_settings）は画面遷移すら記録しない。
 *   - 送れるのは VOCAB の固定語彙だけ。自由入力の metadata 欄は無い。
 *
 * 壊れても受付を止めない:
 *   - 公開 API はすべて try/catch で囲み、例外を呼び出し元へ投げない。
 *   - IndexedDB が使えなければメモリキューへフォールバックする。
 *   - 送信先はエージェント(localhost)。デバイストークンはブラウザに持たせない。
 *
 * Node からも読み込めるよう、副作用のない factory 形式にしてある（tests/analytics_harness.mjs）。
 */
(function (global) {
  "use strict";

  // ── 固定語彙（backend/app/services/analytics_vocab.py と一致させること） ──
  var VOCAB = {
    screens: [
      "idle", "welcome", "top", "reception", "locker_mode", "locker", "delivery",
      "calling", "result_ok", "result_phone", "result_decline", "complete",
      "feedback", "pending", "suspended", "card_capture",
    ],
    fields: [
      "visitor_name", "company", "department", "staff", "purpose",
      "locker_pin", "locker_select", "delivery_method", "qr_scan", "card_capture", "feedback",
    ],
    errors: [
      "required", "too_long", "invalid_format", "pin_mismatch", "pin_invalid",
      "no_locker_available", "locker_occupied", "locker_open_failed",
      "network_unreachable", "api_4xx", "api_5xx", "timeout",
      "camera_unavailable", "qr_unsupported", "card_unavailable", "card_not_detected",
      "agent_unreachable", "unknown",
    ],
    inputMethods: ["touch", "keyboard", "qr", "card", "voice", "smartphone", "auto"],
    entryMethods: ["touch", "qr", "card", "voice", "smartphone"],
    results: ["succeeded", "failed", "cancelled", "timeout", "skipped", "accepted", "phone", "declined"],
    survey: {
      clarity: ["very_clear", "clear", "neutral", "unclear", "very_unclear"],
      confidence: ["very_secure", "secure", "neutral", "slightly_anxious", "very_anxious"],
      assistance: ["none", "received"],
    },
    notifyChannels: ["slack", "push", "webhook", "chatwork", "email", "any"],
  };

  // go() の内部画面名 → 分析ログの screen_id
  var SCREEN_ALIAS = {
    lockerMode: "locker_mode",
    resultOk: "result_ok",
    resultPhone: "result_phone",
    resultDecline: "result_decline",
    "kiosk-settings": "kiosk_settings",
  };

  // クリック記録から除外するセレクタ。打鍵・変換候補から入力値が復元できてしまうため。
  var EXCLUDE_SELECTOR = "[data-pk],[data-noev],.kb-cand,#kb-cand-pop,input,textarea,select";
  var INTERACTIVE_SELECTOR = "button,[role=button],[data-ti],[data-press],[data-ev],a";

  var DB_NAME = "mokuture_analytics";
  var STORE = "outbox";
  var SESSION_KEY = "mk_an_session";
  var RESUME_KEY = "mk_an_resume";
  var MAX_QUEUE = 5000;
  var BACKOFF_BASE_MS = 2000;
  var BACKOFF_MAX_MS = 300000;

  function has(list, value) {
    return list.indexOf(value) !== -1;
  }

  function normalizeScreen(name) {
    if (!name) return null;
    var id = SCREEN_ALIAS[name] || name;
    if (id === "kiosk_settings") return null; // スタッフ専用画面は記録しない
    return has(VOCAB.screens, id) ? id : null;
  }

  // 例外・HTTP ステータスを固定のエラーコードへ丸める。**メッセージ本文は使わない**
  // （入力値やサーバの本文が紛れ込む経路を作らないため）。
  function codeForStatus(status) {
    if (!status) return "network_unreachable";
    if (status === 408) return "timeout";
    if (status >= 500) return "api_5xx";
    if (status >= 400) return "api_4xx";
    return "unknown";
  }

  function isIdentifier(value) {
    if (typeof value !== "string" || !value || value.length > 64) return false;
    return /^[A-Za-z0-9._:-]+$/.test(value);
  }

  function createAnalytics(deps) {
    deps = deps || {};
    var now = deps.now || function () { return Date.now(); };
    var uuid = deps.uuid || defaultUuid;
    var fetchFn = deps.fetch || (typeof fetch !== "undefined" ? fetch.bind(global) : null);
    var session = deps.sessionStore || memoryStore();
    var local = deps.localStore || memoryStore();
    var queue = deps.queue || createQueue(deps.indexedDB);
    var tzOffset = deps.tzOffset || function () { return -new Date().getTimezoneOffset(); };

    var cfg = {
      enabled: false,
      endpoint: "/device/analytics/events",
      appVersion: null,
      uiVersion: "default",
      flowVersion: "visitor-v1",
      idleTimeoutSec: 60,
      flushMs: 15000,
      maxBatch: 200,
    };

    var state = {
      sessionId: null,
      seq: 0,
      screenId: null,
      lastScreenId: null,
      screenEnteredAt: 0,
      inputStartedAt: {},
      errorAt: {},
      retryCount: {},
      notifiedAt: 0,
      ended: false,
    };

    var flushTimer = null;
    var backoffMs = 0;
    var flushing = false;

    // ── 内部: 1件送出 ──────────────────────────────────────────────────────
    function push(name, extra) {
      if (!cfg.enabled) return;
      if (!state.sessionId) return; // セッション開始前のイベントは捨てる（idle 中の描画など）
      var ev = {
        event_id: uuid(),
        session_id: state.sessionId,
        sequence_no: ++state.seq,
        client_occurred_at: new Date(now()).toISOString(),
        client_tz_offset_min: tzOffset(),
        event_source: "browser",
        app_version: cfg.appVersion || null,
        ui_version: cfg.uiVersion || null,
        flow_version: cfg.flowVersion || null,
        event_name: name,
        screen_id: null,
        previous_screen_id: null,
        element_id: null,
        field_id: null,
        input_method: null,
        result: null,
        error_code: null,
        screen_dwell_ms: null,
        duration_ms: null,
        retry_count: null,
        recovered: null,
        question_id: null,
        answer_code: null,
      };
      if (extra) {
        for (var k in extra) {
          if (Object.prototype.hasOwnProperty.call(ev, k) && extra[k] !== undefined) ev[k] = extra[k];
        }
      }
      if (ev.screen_id === null) ev.screen_id = state.screenId || state.lastScreenId;
      persistSession();
      queue.add(ev);
      scheduleFlush(0);
    }

    function persistSession() {
      try {
        var snapshot = JSON.stringify({
          id: state.sessionId,
          seq: state.seq,
          screen: state.screenId,
          at: now(),
        });
        session.setItem(SESSION_KEY, snapshot);
        local.setItem(RESUME_KEY, snapshot);
      } catch (e) { /* ストレージ不可でもログ自体は続ける */ }
    }

    function clearSession() {
      state.sessionId = null;
      state.seq = 0;
      state.screenId = null;
      state.inputStartedAt = {};
      state.errorAt = {};
      state.retryCount = {};
      state.notifiedAt = 0;
      try {
        session.removeItem(SESSION_KEY);
        local.removeItem(RESUME_KEY);
      } catch (e) { /* noop */ }
    }

    // ── 送信（指数バックオフ・順番維持） ──────────────────────────────────
    function scheduleFlush(delay) {
      if (!cfg.enabled || flushTimer !== null) return;
      var wait = delay === 0 ? 0 : (delay || backoffMs || cfg.flushMs);
      flushTimer = setTimeout(function () {
        flushTimer = null;
        flush();
      }, wait);
      if (flushTimer && typeof flushTimer.unref === "function") flushTimer.unref();
    }

    function flush() {
      if (!cfg.enabled || !fetchFn) return Promise.resolve(false);
      if (flushing) {
        // 送信中に積まれたぶんは、いまの送信が終わったころに拾いにいく
        scheduleFlush(cfg.flushMs);
        return Promise.resolve(false);
      }
      flushing = true;
      return queue
        .take(cfg.maxBatch)
        .then(function (batch) {
          if (!batch.length) {
            flushing = false;
            backoffMs = 0;
            return false;
          }
          return fetchFn(cfg.endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ events: batch }),
            keepalive: true,
          })
            .then(function (res) {
              if (!res || !res.ok) throw new Error("http");
              return res.json().catch(function () { return {}; });
            })
            .then(function (data) {
              // **エージェントがディスクへ書き終えた event_id だけ** をローカルから消す。
              var done = (data && data.accepted) || batch.map(function (e) { return e.event_id; });
              var rejected = ((data && data.rejected) || [])
                .map(function (r) { return r && r.id; })
                .filter(Boolean);
              return queue.remove(done.concat(rejected));
            })
            .then(function () {
              flushing = false;
              backoffMs = 0;
              scheduleFlush(0); // まだ残っていれば続けて送る
              return true;
            })
            .catch(function () {
              // 送れなかった＝ローカルに残したまま指数バックオフで再試行する
              flushing = false;
              backoffMs = Math.min(BACKOFF_MAX_MS, Math.max(BACKOFF_BASE_MS, backoffMs * 2 || BACKOFF_BASE_MS));
              backoffMs = Math.round(backoffMs * (1 + (Math.random() * 0.4 - 0.2)));
              scheduleFlush(backoffMs);
              return false;
            });
        })
        .catch(function () {
          flushing = false;
          return false;
        });
    }

    // ── 公開 API（すべて例外を投げない） ──────────────────────────────────
    function guard(fn) {
      return function () {
        try {
          return fn.apply(null, arguments);
        } catch (e) {
          return undefined;
        }
      };
    }

    var api = {
      VOCAB: VOCAB,

      init: guard(function (options) {
        options = options || {};
        for (var k in options) {
          if (Object.prototype.hasOwnProperty.call(cfg, k) && options[k] !== undefined) cfg[k] = options[k];
        }
        if (!cfg.enabled) return api;
        restore();
        scheduleFlush(cfg.flushMs);
        return api;
      }),

      /** 進行中セッションのID。受付送信の analytics_session_id に載せる（通知成否の紐付け用）。 */
      sessionId: guard(function () { return state.sessionId; }),
      isActive: guard(function () { return !!state.sessionId; }),

      /** 最初の操作でセッション開始。既に開始済みなら何もしない（多重開始しない）。 */
      startSession: guard(function (entryMethod) {
        if (!cfg.enabled || state.sessionId) return null;
        var method = has(VOCAB.entryMethods, entryMethod) ? entryMethod : "touch";
        state.sessionId = uuid();
        state.seq = 0;
        state.ended = false;
        push("session_started", { input_method: method });
        return state.sessionId;
      }),

      /** 終了。outcome: completed|cancelled|abandoned|timeout */
      endSession: guard(function (outcome) {
        if (!state.sessionId) return;
        var map = {
          completed: "session_completed",
          cancelled: "session_cancelled",
          abandoned: "session_abandoned",
          timeout: "session_timeout",
        };
        var name = map[outcome] || "session_abandoned";
        exitScreen();
        push(name);
        clearSession();
        flush();
      }),

      /** 画面表示。直前画面の滞在時間（screen_exited）も自動で出す。 */
      screenView: guard(function (screenName) {
        var id = normalizeScreen(screenName);
        if (!cfg.enabled || !state.sessionId) return;
        var previous = state.screenId;
        exitScreen();
        state.screenId = id;
        state.screenEnteredAt = now();
        if (id) push("screen_viewed", { screen_id: id, previous_screen_id: previous });
      }),

      action: guard(function (elementId, options) {
        options = options || {};
        var name = options.eventName || "action_selected";
        push(name, {
          element_id: isIdentifier(elementId) ? elementId : null,
          input_method: has(VOCAB.inputMethods, options.inputMethod) ? options.inputMethod : "touch",
          result: has(VOCAB.results, options.result) ? options.result : null,
        });
      }),

      back: guard(function (elementId) {
        api.action(elementId, { eventName: "back_selected" });
      }),
      help: guard(function (elementId) {
        api.action(elementId, { eventName: "help_opened" });
      }),
      retry: guard(function (elementId) {
        api.action(elementId, { eventName: "retry_selected" });
      }),
      assistance: guard(function (elementId) {
        api.action(elementId, { eventName: "assistance_requested" });
      }),
      /** 押せない場所のタップ。**座標は記録しない**（画面IDのみ）。 */
      deadTap: guard(function () {
        push("noninteractive_area_tapped");
      }),

      inputStarted: guard(function (fieldId, inputMethod) {
        if (!has(VOCAB.fields, fieldId)) return;
        if (state.inputStartedAt[fieldId]) return; // 同じ項目の連続フォーカスは1回だけ
        state.inputStartedAt[fieldId] = now();
        push("input_started", {
          field_id: fieldId,
          input_method: has(VOCAB.inputMethods, inputMethod) ? inputMethod : "touch",
        });
      }),

      /** 入力完了。**入力値・文字数は一切見ない**（「終わった」事実と所要時間だけ）。 */
      inputCompleted: guard(function (fieldId, inputMethod) {
        if (!has(VOCAB.fields, fieldId)) return;
        var startedAt = state.inputStartedAt[fieldId];
        delete state.inputStartedAt[fieldId];
        push("input_completed", {
          field_id: fieldId,
          input_method: has(VOCAB.inputMethods, inputMethod) ? inputMethod : "touch",
          duration_ms: startedAt ? now() - startedAt : null,
        });
      }),

      validationError: guard(function (fieldId, errorCode) {
        if (!has(VOCAB.fields, fieldId)) return;
        var code = has(VOCAB.errors, errorCode) ? errorCode : "unknown";
        state.retryCount[fieldId] = (state.retryCount[fieldId] || 0) + 1;
        state.errorAt[fieldId] = { at: now(), code: code };
        push("validation_error", {
          field_id: fieldId,
          error_code: code,
          result: "failed",
          retry_count: state.retryCount[fieldId],
        });
      }),

      /** エラーを出していた項目が通った。エラー→解消までの時間も残す。 */
      errorRecovered: guard(function (fieldId) {
        var previous = state.errorAt[fieldId];
        if (!previous) return;
        delete state.errorAt[fieldId];
        push("error_recovered", {
          field_id: fieldId,
          error_code: previous.code,
          recovered: true,
          result: "succeeded",
          retry_count: state.retryCount[fieldId] || null,
          duration_ms: now() - previous.at,
        });
      }),

      /** API/通信エラー。**本文・URL・スタックトレースは送らない**（コードだけ）。 */
      apiError: guard(function (statusOrCode, options) {
        options = options || {};
        var code = typeof statusOrCode === "number" ? codeForStatus(statusOrCode) : statusOrCode;
        if (!has(VOCAB.errors, code)) code = "unknown";
        var name = code === "network_unreachable" || code === "agent_unreachable" ? "network_error" : "api_error";
        push(name, {
          error_code: code,
          field_id: has(VOCAB.fields, options.fieldId) ? options.fieldId : null,
          result: "failed",
          duration_ms: options.durationMs || null,
          retry_count: options.retryCount || null,
        });
      }),

      unexpectedError: guard(function (errorCode) {
        push("unexpected_error", {
          error_code: has(VOCAB.errors, errorCode) ? errorCode : "unknown",
          result: "failed",
        });
      }),

      /** 受付/配達呼び出しを送った瞬間。ここからスタッフ応答までを計る。 */
      notificationRequested: guard(function () {
        state.notifiedAt = now();
        push("notification_requested");
      }),

      /** 待機画面のポーリングでスタッフ応答が確定した瞬間。担当者名は送らない。 */
      staffResponded: guard(function (resultState) {
        push("staff_responded", {
          result: has(VOCAB.results, resultState) ? resultState : null,
          duration_ms: state.notifiedAt ? now() - state.notifiedAt : null,
        });
      }),

      feedbackViewed: guard(function (questionId) {
        if (!VOCAB.survey[questionId]) return;
        push("feedback_viewed", { question_id: questionId, screen_id: "feedback" });
      }),
      feedbackSubmitted: guard(function (questionId, answerCode) {
        var answers = VOCAB.survey[questionId];
        if (!answers || !has(answers, answerCode)) return;
        push("feedback_submitted", {
          question_id: questionId,
          answer_code: answerCode,
          screen_id: "feedback",
          result: "succeeded",
        });
      }),
      feedbackSkipped: guard(function (questionId) {
        if (!VOCAB.survey[questionId]) return;
        push("feedback_skipped", { question_id: questionId, screen_id: "feedback", result: "skipped" });
      }),
      feedbackTimeout: guard(function (questionId) {
        if (!VOCAB.survey[questionId]) return;
        push("feedback_timeout", { question_id: questionId, screen_id: "feedback", result: "timeout" });
      }),

      /**
       * 画面コンテナへクリック委譲を張る。element_id の解決順は data-ev → 要素の id。
       * ソフトキーボード・変換候補・入力欄は除外する（入力値の復元を防ぐ）。
       */
      bindAutoTracking: guard(function (root) {
        if (!root || !root.addEventListener) return;
        root.addEventListener(
          "click",
          function (e) {
            try {
              if (!cfg.enabled || !state.sessionId) return;
              var target = e.target;
              if (!target || !target.closest) return;
              if (target.closest(EXCLUDE_SELECTOR)) return; // 入力系は記録しない
              var el = target.closest(INTERACTIVE_SELECTOR);
              if (!el) {
                api.deadTap();
                return;
              }
              var id = el.getAttribute("data-ev") || el.id || "unlabeled";
              api.action(isIdentifier(id) ? id : "unlabeled", {});
            } catch (err) { /* ログ処理で操作を止めない */ }
          },
          true
        );
      }),

      flush: guard(function () { return flush(); }),

      /** ページ離脱時。**session_abandoned は出さない**（リロードと区別できないため）。 */
      onPageHide: guard(function () {
        exitScreen();
        persistSession();
        if (!fetchFn) return;
        queue.take(cfg.maxBatch).then(function (batch) {
          if (!batch.length) return;
          try {
            if (global.navigator && global.navigator.sendBeacon) {
              var blob = new Blob([JSON.stringify({ events: batch })], { type: "application/json" });
              if (global.navigator.sendBeacon(cfg.endpoint, blob)) {
                queue.remove(batch.map(function (e) { return e.event_id; }));
                return;
              }
            }
          } catch (e) { /* 失敗したらローカルに残す＝次回起動で再送される */ }
          flush();
        });
      }),

      _state: state,
      _config: cfg,
      _queue: queue,
    };

    /** 現在画面の滞在時間を確定して screen_exited を出す。二重送出はしない。 */
    function exitScreen() {
      if (!state.screenId || !state.sessionId) return;
      var dwell = Math.max(0, now() - state.screenEnteredAt);
      var screenId = state.screenId;
      state.screenId = null;       // 再入しても二重に出さない
      state.lastScreenId = screenId;
      push("screen_exited", { screen_id: screenId, screen_dwell_ms: dwell });
    }

    /**
     * 再読込後のセッション復元。
     * - 無操作タイムアウト内なら同じセッションを継続する（sequence_no も引き継ぐ）。
     * - 古すぎる場合は前セッションを `session_abandoned` で畳んでから捨てる
     *   （異常終了・端末再起動の後始末。サーバ側スイーパーの保険でもある）。
     */
    function restore() {
      var raw = null;
      try {
        raw = session.getItem(SESSION_KEY) || local.getItem(RESUME_KEY);
      } catch (e) { return; }
      if (!raw) return;
      var saved;
      try { saved = JSON.parse(raw); } catch (e) { return; }
      if (!saved || !saved.id) return;
      var ageMs = now() - (saved.at || 0);
      state.sessionId = saved.id;
      state.seq = saved.seq || 0;
      state.screenId = normalizeScreen(saved.screen);
      state.screenEnteredAt = now();
      if (ageMs > cfg.idleTimeoutSec * 1000) {
        push("session_abandoned");
        clearSession();
      }
    }

    return api;
  }

  // ── 既定の依存（ブラウザ） ────────────────────────────────────────────────
  function defaultUuid() {
    try {
      if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
    } catch (e) { /* fallthrough */ }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function memoryStore() {
    var map = {};
    return {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null; },
      setItem: function (k, v) { map[k] = String(v); },
      removeItem: function (k) { delete map[k]; },
    };
  }

  /**
   * 送信待ちキュー。IndexedDB が使えればそちらへ（再読込・端末再起動をまたいで残る）。
   * 使えない環境ではメモリへフォールバックする（送れなければ失われるが受付は止めない）。
   * 順番は追加順(_ord)で必ず維持する。
   */
  function createQueue(idbFactory) {
    var idb = idbFactory || (typeof indexedDB !== "undefined" ? indexedDB : null);
    var memory = [];
    var ord = 0;
    var dbPromise = null;

    function openDb() {
      if (!idb) return Promise.resolve(null);
      if (dbPromise) return dbPromise;
      dbPromise = new Promise(function (resolve) {
        var req;
        try { req = idb.open(DB_NAME, 1); } catch (e) { return resolve(null); }
        req.onupgradeneeded = function () {
          var db = req.result;
          if (!db.objectStoreNames.contains(STORE)) {
            var store = db.createObjectStore(STORE, { keyPath: "event_id" });
            store.createIndex("ord", "_ord");
          }
        };
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { resolve(null); };
      });
      return dbPromise;
    }

    function add(ev) {
      // 追加順を必ず保つ並び順キー。再読込で ord が 0 に戻っても、壁時計を上位桁に
      // 置くので古い行より前に来ない（FIFO 再送が崩れない）。
      ev._ord = Date.now() * 1000 + (++ord % 1000);
      memory.push(ev);
      if (memory.length > MAX_QUEUE) memory.splice(0, memory.length - MAX_QUEUE);
      openDb().then(function (db) {
        if (!db) return;
        try {
          var tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).put(ev);
        } catch (e) { /* メモリ側には入っているので継続 */ }
      });
    }

    function take(limit) {
      return openDb().then(function (db) {
        if (!db) return memory.slice(0, limit).map(strip);
        return new Promise(function (resolve) {
          var out = [];
          try {
            var tx = db.transaction(STORE, "readonly");
            var cursorReq = tx.objectStore(STORE).index("ord").openCursor();
            cursorReq.onsuccess = function () {
              var cursor = cursorReq.result;
              if (!cursor || out.length >= limit) return resolve(out.map(strip));
              out.push(cursor.value);
              cursor.continue();
            };
            cursorReq.onerror = function () { resolve(memory.slice(0, limit).map(strip)); };
          } catch (e) {
            resolve(memory.slice(0, limit).map(strip));
          }
        });
      });
    }

    function remove(ids) {
      var set = {};
      (ids || []).forEach(function (id) { set[id] = true; });
      memory = memory.filter(function (e) { return !set[e.event_id]; });
      return openDb().then(function (db) {
        if (!db) return;
        try {
          var tx = db.transaction(STORE, "readwrite");
          var store = tx.objectStore(STORE);
          (ids || []).forEach(function (id) { store.delete(id); });
        } catch (e) { /* noop */ }
      });
    }

    function strip(ev) {
      var out = {};
      for (var k in ev) {
        if (k !== "_ord" && Object.prototype.hasOwnProperty.call(ev, k)) out[k] = ev[k];
      }
      return out;
    }

    return { add: add, take: take, remove: remove, _memory: function () { return memory; } };
  }

  global.MKAnalyticsFactory = createAnalytics;
  global.MKAnalyticsVocab = VOCAB;
  global.MKAnalytics = createAnalytics({});
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { createAnalytics: createAnalytics, VOCAB: VOCAB, normalizeScreen: normalizeScreen };
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
