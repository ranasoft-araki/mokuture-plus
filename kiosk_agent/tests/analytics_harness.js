/*
 * キオスク画面の行動ロガー（static/analytics.js）を Node で検証するハーネス。
 *
 * ブラウザ無しで確かめられる範囲（ANALYTICS.md §15）:
 *   1. 操作が順番どおり（sequence_no が 1 から連番）
 *   2. 画面ごとの滞在時間が記録される
 *   3. 戻る操作が経路に残る
 *   4. 入力エラーと修正完了が同じセッションで結び付く
 *   5. 入力値がログへ乗らない（ホワイトリスト外のキーが存在しない）
 *   7. 通信断中のイベントが端末内（キュー）に残る
 *   8. 通信復旧後に順番を維持して再送される
 *  10. ページ再読込後もセッションが継続される
 *  11. 無操作タイムアウトでセッションが終了する
 *
 * 失敗したら非ゼロ終了する（tests/test_analytics_js.py が実行する）。
 */
"use strict";

const path = require("path");
const { createAnalytics, VOCAB, normalizeScreen } = require(path.join(__dirname, "..", "static", "analytics.js"));

let failures = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}${detail ? " — " + detail : ""}`);
  }
}
function eq(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  check(name, a === e, `expected ${e}, got ${a}`);
}

// 進行中の送信（endSession が内部で走らせる flush など）が決着するまで待つ。
// 送信中に重ねて flush() を呼ぶと即 false が返る設計なので、テストでは一旦落ち着かせる。
const settle = () => new Promise((r) => setTimeout(r, 0));

function memStore() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  };
}

// ホワイトリスト。analytics.js の push() が作るイベントのキーはこれで全部。
const ALLOWED_KEYS = [
  "event_id", "session_id", "sequence_no", "client_occurred_at", "client_tz_offset_min",
  "event_source", "app_version", "ui_version", "flow_version", "event_name",
  "screen_id", "previous_screen_id", "element_id", "field_id", "input_method",
  "result", "error_code", "screen_dwell_ms", "duration_ms", "retry_count",
  "recovered", "question_id", "answer_code",
];

function makeTransport() {
  const state = { mode: "fail", sent: [] };
  function fetchFn(url, opts) {
    const body = JSON.parse(opts.body);
    if (state.mode === "fail") return Promise.reject(new Error("offline"));
    state.sent.push({ url, events: body.events });
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ accepted: body.events.map((e) => e.event_id), rejected: [] }),
    });
  }
  return { state, fetchFn };
}

function makeLogger(transport, stores, clock) {
  let counter = 0;
  return createAnalytics({
    now: () => clock.t,
    uuid: () => `evt-${++counter}`,
    fetch: transport.fetchFn,
    sessionStore: stores.session,
    localStore: stores.local,
    tzOffset: () => 540,
  });
}

async function main() {
  console.log("analytics.js harness");

  // ── 1〜5, 7, 8: 1回の受付を通す ─────────────────────────────────────────
  const transport = makeTransport();
  const stores = { session: memStore(), local: memStore() };
  const clock = { t: 1_700_000_000_000 };
  const an = makeLogger(transport, stores, clock);
  an.init({ enabled: true, appVersion: "1.0.3", uiVersion: "default", idleTimeoutSec: 60, flushMs: 5000 });

  an.startSession("touch");
  an.screenView("welcome");
  clock.t += 4200;
  an.screenView("top");
  clock.t += 1500;
  an.action("top-reception");
  an.screenView("reception");
  clock.t += 500;
  an.inputStarted("visitor_name", "keyboard");
  clock.t += 3000;
  an.validationError("visitor_name", "required");
  clock.t += 5000;
  an.errorRecovered("visitor_name");
  an.inputCompleted("visitor_name", "keyboard");
  an.back("rec-back");
  an.screenView("top");
  clock.t += 800;
  an.deadTap();
  an.screenView("reception");
  an.notificationRequested();
  clock.t += 200;
  an.screenView("calling");
  clock.t += 9000;
  an.staffResponded("accepted");
  an.screenView("result_ok");
  an.feedbackViewed("clarity");
  an.feedbackSubmitted("clarity", "very_clear");
  an.feedbackSkipped("assistance");
  an.endSession("completed");

  // 通信断のあいだは端末内（キュー）に残る
  await settle();
  await an.flush();
  await settle();
  const pendingWhileOffline = await an._queue.take(500);
  check("通信断中はキューに残る", pendingWhileOffline.length > 0, `${pendingWhileOffline.length} 件`);
  eq("通信断中は1件も送られていない", transport.state.sent.length, 0);

  // 復旧 → 順番を維持して再送
  transport.state.mode = "ok";
  await an.flush();
  await settle();
  const sentEvents = transport.state.sent.flatMap((b) => b.events);
  eq("復旧後に全件送られる", sentEvents.length, pendingWhileOffline.length);
  eq("再送後のキューは空", (await an._queue.take(500)).length, 0);

  const seqs = sentEvents.map((e) => e.sequence_no);
  eq("sequence_no は 1 からの連番", seqs, seqs.map((_, i) => i + 1));

  const names = sentEvents.map((e) => e.event_name);
  eq("最初は session_started", names[0], "session_started");
  eq("最後は session_completed", names[names.length - 1], "session_completed");
  check("戻る操作が残る", names.includes("back_selected"));
  check("押せない場所のタップが残る", names.includes("noninteractive_area_tapped"));

  // 画面滞在時間
  const exits = sentEvents.filter((e) => e.event_name === "screen_exited");
  const welcomeExit = exits.find((e) => e.screen_id === "welcome");
  eq("welcome の滞在時間", welcomeExit && welcomeExit.screen_dwell_ms, 4200);
  const path1 = sentEvents.filter((e) => e.event_name === "screen_viewed").map((e) => e.screen_id);
  eq("画面の経路", path1, ["welcome", "top", "reception", "top", "reception", "calling", "result_ok"]);

  // 入力エラー → 修正完了が同じセッションで結び付く
  const verr = sentEvents.find((e) => e.event_name === "validation_error");
  const rec = sentEvents.find((e) => e.event_name === "error_recovered");
  check("エラーと回復が同じセッション", verr.session_id === rec.session_id && verr.field_id === rec.field_id);
  eq("回復までの時間", rec.duration_ms, 5000);
  eq("再試行回数", verr.retry_count, 1);

  // スタッフ応答（通知送信からの経過）
  const responded = sentEvents.find((e) => e.event_name === "staff_responded");
  eq("応答までの時間", responded.duration_ms, 9200);
  eq("応答の内容", responded.result, "accepted");

  // アンケート
  const submitted = sentEvents.find((e) => e.event_name === "feedback_submitted");
  eq("アンケート回答", [submitted.question_id, submitted.answer_code], ["clarity", "very_clear"]);

  // ── 5. 入力値が乗らない ────────────────────────────────────────────────
  const extraKeys = new Set();
  for (const ev of sentEvents) {
    for (const k of Object.keys(ev)) if (!ALLOWED_KEYS.includes(k)) extraKeys.add(k);
  }
  eq("ホワイトリスト外のキーが無い", [...extraKeys], []);

  const serialized = JSON.stringify(sentEvents);
  check("日本語（＝入力値・ラベル）が混ざっていない", !/[぀-ヿ一-龯]/.test(serialized), serialized.slice(0, 200));

  // 表示文字列を element_id に渡しても落ちる
  const an2 = makeLogger(transport, { session: memStore(), local: memStore() }, clock);
  an2.init({ enabled: true, flushMs: 5000 });
  an2.startSession("touch");
  an2.action("ご訪問");
  const dropped = (await an2._queue.take(10)).find((e) => e.event_name === "action_selected");
  eq("表示文字列の element_id は保存しない", dropped.element_id, null);

  // 未知の語彙は送らない
  an2.validationError("secret_field", "required");
  an2.feedbackSubmitted("clarity", "great");
  const after = await an2._queue.take(50);
  check("未知の field_id は記録しない", !after.some((e) => e.field_id === "secret_field"));
  check("未知の answer_code は記録しない", !after.some((e) => e.answer_code === "great"));

  // ── 10. 再読込後にセッションが継続する ────────────────────────────────
  const stores2 = { session: memStore(), local: memStore() };
  const clock2 = { t: 1_800_000_000_000 };
  const a1 = makeLogger(transport, stores2, clock2);
  a1.init({ enabled: true, idleTimeoutSec: 60, flushMs: 5000 });
  const sid = a1.startSession("touch");
  a1.screenView("top");
  a1.action("top-reception");

  clock2.t += 5000; // 再読込（無操作タイムアウト内）
  const a2 = makeLogger(transport, stores2, clock2);
  a2.init({ enabled: true, idleTimeoutSec: 60, flushMs: 5000 });
  eq("再読込後も同じセッション", a2.sessionId(), sid);
  a2.screenView("reception");
  // 再読込前の 3 件（session_started / screen_exited / screen_viewed / action_selected のうち
  // 送信済みのぶん）はキューから消えているので、「続きの番号か」で確認する。
  const resumed = await a2._queue.take(500);
  const resumedSeq = resumed.filter((e) => e.session_id === sid).map((e) => e.sequence_no);
  eq("sequence_no が続きから振られる", resumedSeq, [4, 5]);

  // ── 11. 放置されたセッションは畳まれる ────────────────────────────────
  clock2.t += 10 * 60 * 1000; // 無操作タイムアウトを大きく超える
  const a3 = makeLogger(transport, stores2, clock2);
  a3.init({ enabled: true, idleTimeoutSec: 60, flushMs: 5000 });
  eq("古いセッションは復元しない", a3.isActive(), false);
  const abandoned = (await a3._queue.take(500)).filter((e) => e.event_name === "session_abandoned");
  eq("離脱として畳まれる", abandoned.length, 1);
  eq("畳まれたのは前のセッション", abandoned[0].session_id, sid);

  // ── 画面名の正規化 ────────────────────────────────────────────────────
  eq("lockerMode → locker_mode", normalizeScreen("lockerMode"), "locker_mode");
  eq("resultOk → result_ok", normalizeScreen("resultOk"), "result_ok");
  eq("設定画面は記録しない", normalizeScreen("kiosk-settings"), null);
  eq("未知の画面は記録しない", normalizeScreen("secret"), null);
  check("語彙に kiosk_settings が無い", !VOCAB.screens.includes("kiosk_settings"));

  // ── 無効時は何も送らない（?mock=1 のプレビュー） ──────────────────────
  const off = makeLogger(transport, { session: memStore(), local: memStore() }, clock);
  off.init({ enabled: false });
  off.startSession("touch");
  off.action("top-reception");
  eq("無効時はキューに積まない", (await off._queue.take(10)).length, 0);

  console.log(failures === 0 ? "\nall ok" : `\n${failures} failure(s)`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error("harness crashed:", e);
  process.exit(2);
});
