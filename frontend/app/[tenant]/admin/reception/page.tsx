"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type ReceptionLog } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";

type DateFilter = "today" | "week" | "month" | "all";

const DATE_LABELS: Record<DateFilter, string> = { today: "今日", week: "今週", month: "今月", all: "過去30日" };

export default function ReceptionLogsPage() {
  const router = useRouter();
  const [logs, setLogs] = useState<ReceptionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [dateFilter, setDateFilter] = useState<DateFilter>("today");

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    api.listReception(token)
      .then(setLogs)
      .catch(() => { clearTokens(); router.push("/login"); })
      .finally(() => setLoading(false));
  }, [router]);

  const filtered = useMemo(() => {
    const now = new Date();
    const startOf = (offset: number) => {
      const d = new Date(now);
      d.setDate(d.getDate() - offset);
      d.setHours(0, 0, 0, 0);
      return d;
    };
    const cutoff: Record<DateFilter, Date> = {
      today: startOf(0),
      week:  startOf(7),
      month: startOf(30),
      all:   startOf(30),
    };

    let list = logs.filter((r) => new Date(r.created_at) >= cutoff[dateFilter]);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((r) =>
        r.visitor_name.toLowerCase().includes(q) ||
        (r.company ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [logs, dateFilter, search]);

  return (
    <AdminShell
      active="reception"
      title="受付ログ"
      breadcrumb="ホーム / 受付ログ"
      subtitle={`過去30日 · 合計 ${logs.length} 件`}
      actions={
        <MkBtn variant="ghost" size="sm">CSV エクスポート</MkBtn>
      }
    >
      {/* Filter row */}
      <div style={{ display: "flex", gap: 10, marginBottom: 18, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, width: 280 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="来訪者名・会社名で検索"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: '"Noto Sans JP", system-ui, sans-serif', height: "100%" }}
          />
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["today", "week", "month", "all"] as DateFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setDateFilter(f)}
              style={{
                padding: "6px 12px", fontSize: 11.5,
                background: dateFilter === f ? "#1d1a15" : "#fffefb",
                color: dateFilter === f ? "#fffefb" : "#6b6559",
                border: `1px solid ${dateFilter === f ? "#1d1a15" : "#d8d3c7"}`,
                borderRadius: 999, cursor: "pointer",
                fontFamily: '"Noto Sans JP", system-ui, sans-serif',
              }}
            >
              {DATE_LABELS[f]}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", fontSize: 11.5, color: "#a8a198" }}>
          {filtered.length} / {logs.length} 件
        </div>
      </div>

      <MkCard padding="0">
        {loading ? (
          <div style={{ padding: "48px 20px", textAlign: "center", color: "#a8a198" }}>読み込み中…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: "48px 20px", textAlign: "center", color: "#a8a198" }}>受付記録がありません</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
            <thead>
              <tr style={{ background: "#f4f1ea", fontSize: 10.5, color: "#a8a198", textAlign: "left", letterSpacing: "0.3px" }}>
                {["日付", "時刻", "来訪者", "会社", "用件", "受付経路", "担当", "状態"].map((h) => (
                  <th key={h} style={{ padding: "11px 14px", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody style={{ fontSize: 12.5 }}>
              {filtered.map((r, i) => {
                const d = new Date(r.created_at);
                return (
                  <tr key={r.id} style={{ borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                    <td style={{ padding: "12px 14px", color: "#6b6559", fontFamily: "monospace", fontSize: 11.5 }}>
                      {d.toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" })}
                    </td>
                    <td style={{ padding: "12px 14px", color: "#6b6559", fontFamily: "monospace", fontSize: 11.5 }}>
                      {d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td style={{ padding: "12px 14px", color: "#1d1a15", fontWeight: 500 }}>{r.visitor_name}</td>
                    <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.company || "—"}</td>
                    <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.purpose || "—"}</td>
                    <td style={{ padding: "12px 14px" }}>
                      <span style={{ fontSize: 10.5, color: "#6b6559", background: "#f4f1ea", padding: "2px 8px", borderRadius: 3, border: "1px solid #efece5", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
                        {r.method || "フォーム"}
                      </span>
                    </td>
                    <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.staff || "—"}</td>
                    <td style={{ padding: "12px 14px" }}>
                      <MkPill tone={r.state === "received" ? "live" : "neutral"}>
                        {r.state === "received" ? "確認済" : r.state}
                      </MkPill>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </MkCard>
    </AdminShell>
  );
}
