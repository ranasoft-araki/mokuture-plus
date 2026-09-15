"use client";

/**
 * 実証実験ログ（運営のみ）。
 *
 * ANALYTICS.md §13 の「最低限の確認手段」— 匿名セッション一覧・1セッションの時系列表示・
 * 日付/拠点(テナント)/端末/完了状態での絞り込み・CSV/JSON 出力・主要指標・端末稼働率。
 *
 * **個人情報は表示しない**（API がそもそも返さない）。分析画面の作り込みより、
 * 後から集計できるデータ構造が正しいことの確認を目的にしている。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  AnalyticsEvent,
  AnalyticsFilters,
  AnalyticsSession,
  AnalyticsSummary,
  AnalyticsUptimeItem,
  OperatorTenant,
} from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle } from "@/components/AdminShell";

const LIMIT = 100;

const OUTCOME_LABEL: Record<string, string> = {
  completed: "完了",
  cancelled: "キャンセル",
  abandoned: "離脱",
  timeout: "タイムアウト",
  app_error: "アプリ異常終了",
  device_restarted: "端末再起動",
  open: "進行中",
};

const OUTCOME_COLOR: Record<string, string> = {
  completed: "#10b981",
  cancelled: "#9ca3af",
  abandoned: "#f59e0b",
  timeout: "#f59e0b",
  app_error: "#ef4444",
  device_restarted: "#ef4444",
};

const ENTRY_LABEL: Record<string, string> = {
  touch: "タッチ",
  qr: "QR",
  card: "名刺",
  voice: "音声",
  smartphone: "スマホ",
};

const SCREEN_LABEL: Record<string, string> = {
  idle: "待機",
  welcome: "ようこそ(QR)",
  top: "受付メニュー",
  reception: "受付フォーム",
  locker_mode: "ロッカー入口",
  locker: "ロッカー",
  delivery: "配達",
  calling: "お待ちください",
  result_ok: "受付(参ります)",
  result_phone: "電話案内",
  result_decline: "お断り",
  complete: "歓迎(マップ)",
  feedback: "アンケート",
  pending: "承認待ち",
  suspended: "停止中",
  card_capture: "名刺読み取り",
};

const inputStyle: React.CSSProperties = {
  height: 34,
  border: "1px solid #efece5",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  outline: "none",
  background: "#faf8f4",
  color: "#1d1a15",
};

const btnStyle: React.CSSProperties = {
  height: 34,
  padding: "0 14px",
  border: "1px solid #d8d3c7",
  borderRadius: 6,
  background: "#fffefb",
  color: "#1d1a15",
  fontSize: 12.5,
  cursor: "pointer",
};

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${Math.round(value)}ms`;
  const sec = value / 1000;
  if (sec < 90) return `${sec.toFixed(1)}秒`;
  return `${Math.floor(sec / 60)}分${Math.round(sec % 60)}秒`;
}

function jst(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", hour12: false });
}

function jstTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour12: false }) + `.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

function OutcomePill({ outcome }: { outcome: string | null }) {
  const key = outcome ?? "open";
  const color = OUTCOME_COLOR[key] ?? "#9ca3af";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 9px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        color,
        background: `${color}1f`,
        whiteSpace: "nowrap",
      }}
    >
      {OUTCOME_LABEL[key] ?? key}
    </span>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ flex: "1 1 150px", minWidth: 150 }}>
      <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "#1d1a15", marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function OperatorAnalyticsPage() {
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [filters, setFilters] = useState<AnalyticsFilters>({});
  const [sessions, setSessions] = useState<AnalyticsSession[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [uptime, setUptime] = useState<AnalyticsUptimeItem[]>([]);
  const [selected, setSelected] = useState<AnalyticsSession | null>(null);
  const [events, setEvents] = useState<AnalyticsEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const token = typeof window === "undefined" ? null : getAccessToken();

  useEffect(() => {
    if (!token) return;
    api
      .listOperatorTenants(token, { limit: 200 })
      .then((r) => setTenants(r.items ?? []))
      .catch(() => {});
  }, [token]);

  // 取得だけを行う（setState はしない）。エフェクトからもボタンからも同じ経路で使う。
  const fetchAll = useCallback(
    async (nextOffset: number) => {
      if (!token) return null;
      const [list, sum, up] = await Promise.all([
        api.listAnalyticsSessions(token, { ...filters, offset: nextOffset, limit: LIMIT }),
        api.getAnalyticsSummary(token, filters),
        api.getAnalyticsUptime(token, {
          tenant_id: filters.tenant_id,
          device_id: filters.device_id,
          date_from: filters.date_from,
          date_to: filters.date_to,
        }),
      ]);
      return { list, sum, up, nextOffset };
    },
    [token, filters],
  );

  // setState 群はそれ自体が安定なので依存は空でよい（依存配列を正しく保つため useCallback にする）。
  const apply = useCallback((data: NonNullable<Awaited<ReturnType<typeof fetchAll>>>) => {
    setSessions(data.list.items);
    setTotal(data.list.total);
    setOffset(data.nextOffset);
    setSummary(data.sum);
    setUptime(data.up.items);
  }, []);

  // 初回とフィルタ変更時。**setState は必ず await のあと**に置く（描画中の連鎖更新を避ける）。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await fetchAll(0);
        if (!alive || !data) return;
        apply(data);
        setError("");
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "読み込みに失敗しました");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [fetchAll, apply]);

  // ページ送り・再読込ボタン（イベントハンドラなので同期 setState で問題ない）。
  const load = useCallback(
    async (nextOffset = 0) => {
      setLoading(true);
      setError("");
      try {
        const data = await fetchAll(nextOffset);
        if (data) apply(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "読み込みに失敗しました");
      } finally {
        setLoading(false);
      }
    },
    [fetchAll, apply],
  );

  const openSession = useCallback(
    async (session: AnalyticsSession) => {
      if (!token) return;
      setSelected(session);
      setEvents([]);
      try {
        const detail = await api.getAnalyticsSession(token, session.id);
        setSelected(detail.session);
        setEvents(detail.events);
      } catch (e) {
        setError(e instanceof Error ? e.message : "セッションの取得に失敗しました");
      }
    },
    [token],
  );

  const download = useCallback(
    async (kind: "sessions" | "events", fmt: "csv" | "json") => {
      if (!token) return;
      try {
        const { blob, filename } = await api.downloadAnalyticsExport(token, { ...filters, kind, fmt });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        setError(e instanceof Error ? e.message : "エクスポートに失敗しました");
      }
    },
    [token, filters],
  );

  const setFilter = (key: keyof AnalyticsFilters, value: string) => {
    setLoading(true);   // 読み直しはエフェクト側が走り、完了時に false に戻る
    setFilters((f) => ({ ...f, [key]: value || undefined }));
  };

  const assist = summary?.self_reported_unassisted;

  const screenDwell = useMemo(() => {
    // 選択中セッションの画面別滞在時間（時系列パネルの補助表示）
    const rows: { screen: string; dwell: number }[] = [];
    for (const ev of events) {
      if (ev.event_name === "screen_exited" && ev.screen_id && ev.screen_dwell_ms != null) {
        rows.push({ screen: ev.screen_id, dwell: ev.screen_dwell_ms });
      }
    }
    return rows;
  }, [events]);

  return (
    <div style={{ padding: "18px 22px 40px", maxWidth: 1500, margin: "0 auto" }}>
      <MkSectionTitle
        title="実証実験ログ"
        subtitle="匿名セッションの行動履歴と端末稼働実績（個人情報は保存していません）"
      />

      {/* ─ 絞り込み ─ */}
      <MkCard style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <select style={{ ...inputStyle, cursor: "pointer" }} value={filters.tenant_id ?? ""} onChange={(e) => setFilter("tenant_id", e.target.value)}>
            <option value="">拠点（全テナント）</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <input style={inputStyle} placeholder="端末ID" value={filters.device_id ?? ""} onChange={(e) => setFilter("device_id", e.target.value)} />
          <select style={{ ...inputStyle, cursor: "pointer" }} value={filters.outcome ?? ""} onChange={(e) => setFilter("outcome", e.target.value)}>
            <option value="">完了状態（すべて）</option>
            {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select style={{ ...inputStyle, cursor: "pointer" }} value={filters.entry_method ?? ""} onChange={(e) => setFilter("entry_method", e.target.value)}>
            <option value="">入力方法（すべて）</option>
            {Object.entries(ENTRY_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <input style={inputStyle} type="date" value={filters.date_from ?? ""} onChange={(e) => setFilter("date_from", e.target.value)} />
          <span style={{ color: "#a8a198", fontSize: 12 }}>〜</span>
          <input style={inputStyle} type="date" value={filters.date_to ?? ""} onChange={(e) => setFilter("date_to", e.target.value)} />
          <button style={btnStyle} onClick={() => load(0)} disabled={loading}>{loading ? "読込中…" : "再読込"}</button>
          <div style={{ flex: 1 }} />
          <button style={btnStyle} onClick={() => download("sessions", "csv")}>セッションCSV</button>
          <button style={btnStyle} onClick={() => download("events", "csv")}>イベントCSV</button>
          <button style={btnStyle} onClick={() => download("events", "json")}>イベントJSON</button>
        </div>
        {error && <div style={{ marginTop: 10, fontSize: 12, color: "#b91c1c" }}>{error}</div>}
      </MkCard>

      {/* ─ 主要指標 ─ */}
      {summary && (
        <MkCard style={{ marginBottom: 14 }}>
          <MkSectionTitle title="主要指標" subtitle="受付完了時間は中央値・90パーセンタイルも併記" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
            <Metric label="受付開始" value={String(summary.sessions_started)} sub="セッション数" />
            <Metric label="受付完了率" value={pct(summary.completion_rate)} sub={`完了 ${summary.completed} 件`} />
            <Metric label="離脱率" value={pct(summary.abandon_rate)} sub="離脱＋タイムアウト" />
            <Metric label="エラー発生率" value={pct(summary.error_rate)} />
            <Metric label="エラー回復率" value={pct(summary.error_recovery_rate)} sub="エラー後に完了" />
            <Metric label="受付完了時間(中央値)" value={ms(summary.duration_ms.median)} sub={`平均 ${ms(summary.duration_ms.avg)} / 90% ${ms(summary.duration_ms.p90)}`} />
            <Metric label="担当者応答(中央値)" value={ms(summary.staff_response_ms.median)} sub={`90% ${ms(summary.staff_response_ms.p90)}`} />
            <Metric
              label="自己申告による非介助率"
              value={pct(assist?.rate)}
              sub={`回答 ${assist?.answered ?? 0} 件 / 回答率 ${pct(assist?.response_rate)}`}
            />
          </div>

          <div style={{ marginTop: 18, display: "flex", flexWrap: "wrap", gap: 22 }}>
            <div style={{ flex: "1 1 340px" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", marginBottom: 6 }}>入力方法別</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "#a8a198", textAlign: "left" }}>
                    <th style={{ padding: "4px 6px" }}>入力方法</th>
                    <th style={{ padding: "4px 6px" }}>開始</th>
                    <th style={{ padding: "4px 6px" }}>完了率</th>
                    <th style={{ padding: "4px 6px" }}>所要(中央値)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.by_entry_method).map(([k, v]) => (
                    <tr key={k} style={{ borderTop: "1px solid #efece5" }}>
                      <td style={{ padding: "5px 6px" }}>{ENTRY_LABEL[k] ?? k}</td>
                      <td style={{ padding: "5px 6px" }}>{v.started}</td>
                      <td style={{ padding: "5px 6px" }}>{pct(v.completion_rate)}</td>
                      <td style={{ padding: "5px 6px" }}>{ms(v.duration_median)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ flex: "1 1 340px" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", marginBottom: 6 }}>アンケート回答（任意回答・未回答は unknown）</div>
              {Object.entries(summary.survey).map(([qid, q]) => (
                <div key={qid} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 11.5, color: "#6b6559" }}>
                    {qid} — 回答 {q.answered} 件 / 回答率 {pct(q.response_rate)}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#1d1a15" }}>
                    {Object.entries(q.counts).map(([code, n]) => `${code}: ${n}`).join(" · ") || "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </MkCard>
      )}

      {/* ─ 端末稼働率 ─ */}
      <MkCard style={{ marginBottom: 14 }}>
        <MkSectionTitle
          title="端末稼働実績"
          subtitle="分母は端末の電源が入っていた時間（ハートビート実測）。電源OFF中は分母から外れます"
        />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ color: "#a8a198", textAlign: "left" }}>
                <th style={{ padding: "5px 8px" }}>端末</th>
                <th style={{ padding: "5px 8px" }}>拠点</th>
                <th style={{ padding: "5px 8px" }}>稼働率</th>
                <th style={{ padding: "5px 8px" }}>電源ON</th>
                <th style={{ padding: "5px 8px" }}>通信障害</th>
                <th style={{ padding: "5px 8px" }}>再起動</th>
                <th style={{ padding: "5px 8px" }}>CPU平均</th>
                <th style={{ padding: "5px 8px" }}>最高温度</th>
                <th style={{ padding: "5px 8px" }}>空き容量(最小)</th>
              </tr>
            </thead>
            <tbody>
              {uptime.length === 0 && (
                <tr><td colSpan={9} style={{ padding: 14, color: "#a8a198" }}>メトリクスがまだ届いていません</td></tr>
              )}
              {uptime.map((u) => (
                <tr key={u.device_id} style={{ borderTop: "1px solid #efece5" }}>
                  <td style={{ padding: "6px 8px" }}>{u.device_name ?? u.device_id}</td>
                  <td style={{ padding: "6px 8px" }}>{u.tenant_name ?? "—"}</td>
                  <td style={{ padding: "6px 8px", fontWeight: 700 }}>{pct(u.uptime_rate)}</td>
                  <td style={{ padding: "6px 8px" }}>{(u.powered_sec / 3600).toFixed(1)}h</td>
                  <td style={{ padding: "6px 8px" }}>{(u.offline_sec / 60).toFixed(0)}分</td>
                  <td style={{ padding: "6px 8px" }}>{u.restart_count}</td>
                  <td style={{ padding: "6px 8px" }}>{u.cpu_percent_avg ?? "—"}</td>
                  <td style={{ padding: "6px 8px" }}>{u.cpu_temp_max ?? "—"}</td>
                  <td style={{ padding: "6px 8px" }}>{u.disk_free_mb_min ? `${(u.disk_free_mb_min / 1024).toFixed(1)}GB` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MkCard>

      {/* ─ セッション一覧 ─ */}
      <MkCard>
        <MkSectionTitle title={`匿名セッション（${total} 件）`} subtitle="行をクリックすると1回の受付を時系列で表示します" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ color: "#a8a198", textAlign: "left" }}>
                <th style={{ padding: "5px 8px" }}>開始(JST)</th>
                <th style={{ padding: "5px 8px" }}>結果</th>
                <th style={{ padding: "5px 8px" }}>所要</th>
                <th style={{ padding: "5px 8px" }}>入口</th>
                <th style={{ padding: "5px 8px" }}>最終画面</th>
                <th style={{ padding: "5px 8px" }}>画面</th>
                <th style={{ padding: "5px 8px" }}>戻る</th>
                <th style={{ padding: "5px 8px" }}>エラー</th>
                <th style={{ padding: "5px 8px" }}>応答</th>
                <th style={{ padding: "5px 8px" }}>拠点 / 端末</th>
                <th style={{ padding: "5px 8px" }}>版数</th>
              </tr>
            </thead>
            <tbody>
              {sessions.length === 0 && !loading && (
                <tr><td colSpan={11} style={{ padding: 14, color: "#a8a198" }}>該当するセッションがありません</td></tr>
              )}
              {sessions.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => openSession(s)}
                  style={{ borderTop: "1px solid #efece5", cursor: "pointer", background: selected?.id === s.id ? "#f4f1ea" : undefined }}
                >
                  <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>{jst(s.started_at)}</td>
                  <td style={{ padding: "6px 8px" }}><OutcomePill outcome={s.outcome} /></td>
                  <td style={{ padding: "6px 8px" }}>{ms(s.duration_ms)}</td>
                  <td style={{ padding: "6px 8px" }}>{s.entry_method ? ENTRY_LABEL[s.entry_method] ?? s.entry_method : "—"}</td>
                  <td style={{ padding: "6px 8px" }}>{s.last_screen_id ? SCREEN_LABEL[s.last_screen_id] ?? s.last_screen_id : "—"}</td>
                  <td style={{ padding: "6px 8px" }}>{s.screen_count}</td>
                  <td style={{ padding: "6px 8px" }}>{s.back_count}</td>
                  <td style={{ padding: "6px 8px", color: s.error_count ? "#b91c1c" : undefined }}>{s.error_count}</td>
                  <td style={{ padding: "6px 8px" }}>{s.staff_response ?? "—"}{s.staff_response_ms != null ? ` (${ms(s.staff_response_ms)})` : ""}</td>
                  <td style={{ padding: "6px 8px" }}>{s.tenant_name ?? "—"} / {s.device_name ?? "—"}</td>
                  <td style={{ padding: "6px 8px", color: "#a8a198" }}>{s.app_version ?? "—"} / {s.ui_version ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
          <button style={btnStyle} disabled={offset === 0} onClick={() => load(Math.max(0, offset - LIMIT))}>前へ</button>
          <span style={{ fontSize: 12, color: "#a8a198" }}>{offset + 1}–{Math.min(offset + LIMIT, total)} / {total}</span>
          <button style={btnStyle} disabled={offset + LIMIT >= total} onClick={() => load(offset + LIMIT)}>次へ</button>
        </div>
      </MkCard>

      {/* ─ 1セッションの時系列 ─ */}
      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(20,18,14,0.45)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: "#fffefb", borderRadius: 12, width: "min(1100px, 96vw)", maxHeight: "90vh", overflow: "auto", padding: 22 }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#1d1a15" }}>匿名セッションの時系列</div>
                <div style={{ fontSize: 11, color: "#a8a198", marginTop: 3, fontFamily: "ui-monospace, monospace" }}>{selected.id}</div>
              </div>
              <button style={btnStyle} onClick={() => setSelected(null)}>閉じる</button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 18, margin: "16px 0" }}>
              <Metric label="結果" value={OUTCOME_LABEL[selected.outcome ?? "open"] ?? "—"} />
              <Metric label="所要時間" value={ms(selected.duration_ms)} sub={`${jst(selected.started_at)} 〜`} />
              <Metric label="入口" value={selected.entry_method ? ENTRY_LABEL[selected.entry_method] ?? selected.entry_method : "—"} />
              <Metric label="画面数 / 戻る" value={`${selected.screen_count} / ${selected.back_count}`} />
              <Metric label="エラー" value={String(selected.error_count)} />
              <Metric
                label="アンケート"
                value={[selected.answer_clarity, selected.answer_confidence, selected.answer_assistance].filter(Boolean).length + " 問回答"}
                sub={`支援: ${selected.answer_assistance ?? "unknown"}`}
              />
            </div>

            {screenDwell.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>画面別の滞在時間</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {screenDwell.map((row, i) => (
                    <span key={i} style={{ fontSize: 11.5, padding: "3px 9px", borderRadius: 6, background: "#f4f1ea", color: "#1d1a15" }}>
                      {SCREEN_LABEL[row.screen] ?? row.screen}: {ms(row.dwell)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
              <thead>
                <tr style={{ color: "#a8a198", textAlign: "left" }}>
                  <th style={{ padding: "4px 6px" }}>#</th>
                  <th style={{ padding: "4px 6px" }}>端末時刻(JST)</th>
                  <th style={{ padding: "4px 6px" }}>発生元</th>
                  <th style={{ padding: "4px 6px" }}>イベント</th>
                  <th style={{ padding: "4px 6px" }}>画面</th>
                  <th style={{ padding: "4px 6px" }}>要素/項目</th>
                  <th style={{ padding: "4px 6px" }}>結果</th>
                  <th style={{ padding: "4px 6px" }}>エラー</th>
                  <th style={{ padding: "4px 6px" }}>滞在/所要</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.event_id} style={{ borderTop: "1px solid #efece5" }}>
                    <td style={{ padding: "4px 6px", color: "#a8a198" }}>{ev.sequence_no}</td>
                    <td style={{ padding: "4px 6px", whiteSpace: "nowrap", fontFamily: "ui-monospace, monospace" }}>{jstTime(ev.client_occurred_at)}</td>
                    <td style={{ padding: "4px 6px", color: "#a8a198" }}>{ev.event_source}</td>
                    <td style={{ padding: "4px 6px", fontWeight: 600 }}>{ev.event_name}</td>
                    <td style={{ padding: "4px 6px" }}>{ev.screen_id ? SCREEN_LABEL[ev.screen_id] ?? ev.screen_id : "—"}</td>
                    <td style={{ padding: "4px 6px", fontFamily: "ui-monospace, monospace" }}>{ev.element_id ?? ev.field_id ?? ev.question_id ?? "—"}</td>
                    <td style={{ padding: "4px 6px" }}>{ev.answer_code ?? ev.result ?? "—"}</td>
                    <td style={{ padding: "4px 6px", color: ev.error_code ? "#b91c1c" : undefined }}>{ev.error_code ?? "—"}</td>
                    <td style={{ padding: "4px 6px" }}>{ms(ev.screen_dwell_ms ?? ev.duration_ms)}</td>
                  </tr>
                ))}
                {events.length === 0 && (
                  <tr><td colSpan={9} style={{ padding: 14, color: "#a8a198" }}>読み込み中…</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
