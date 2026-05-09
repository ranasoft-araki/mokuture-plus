"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type ReceptionLog } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";
import { AdminShell, MkCard } from "@/components/AdminShell";
import { ConfirmModal } from "@/components/ConfirmModal";

type DateFilter = "today" | "week" | "month" | "all";
type AgingLevel = "fresh" | "warn" | "alert" | "urgent";

function getAgingLevel(log: ReceptionLog): AgingLevel {
  if (log.state !== "received") return "fresh";
  const elapsedMin = (Date.now() - new Date(log.created_at).getTime()) / 60000;
  if (elapsedMin >= 30) return "urgent";
  if (elapsedMin >= 15) return "alert";
  if (elapsedMin >= 5)  return "warn";
  return "fresh";
}

const AGING_BORDER: Record<AgingLevel, string> = {
  fresh:  "none",
  warn:   "4px solid #f59e0b",
  alert:  "4px solid #f97316",
  urgent: "4px solid #ef4444",
};

const SELECT_STYLE: React.CSSProperties = {
  height: 34,
  border: "1px solid #d8d3c7",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  background: "#fffefb",
  color: "#2d2a24",
};

async function downloadCsv(token: string) {
  const blob = await api.exportReceptionCsv(token);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `reception_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadContactsCsv(token: string) {
  const blob = await api.exportContactsCsv(token);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `contacts_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const DATE_LABELS: Record<DateFilter, string> = {
  today:  "今日",
  week:   "今週",
  month:  "今月",
  all:    "過去30日",
};

const PAGE_SIZE = 10;

const STATUS_LABEL: Record<string, string> = {
  received: "受付済み",
  notified: "通知済み",
  completed: "完了",
  cancelled: "キャンセル",
};

const STATUS_COLOR: Record<string, string> = {
  received: "#f59e0b",
  notified: "#3b82f6",
  completed: "#10b981",
  cancelled: "#9ca3af",
};

const METHOD_LABEL: Record<string, string> = {
  form: "フォーム入力",
  qr: "QR読取",
};

function translateMethod(method: string | null | undefined): string {
  if (!method) return "—";
  return METHOD_LABEL[method] ?? method;
}

function ReceptionDetailModal({ log, token, onClose, onNotesUpdate }: { log: ReceptionLog; token: string; onClose: () => void; onNotesUpdate: (id: string, notes: string | null) => void }) {
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesText, setNotesText] = useState(log.staff_notes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [visitorHistory, setVisitorHistory] = useState<{ count: number; first_visit: string | null; last_visit: string | null } | null>(null);

  useEffect(() => {
    setNotesText(log.staff_notes ?? "");
    setEditingNotes(false);
  }, [log.id, log.staff_notes]);

  useEffect(() => {
    setVisitorHistory(null);
    api.getVisitorHistory(token, log.visitor_name)
      .then((data) => setVisitorHistory(data))
      .catch(() => {});
  }, [log.id, log.visitor_name, token]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const d = new Date(log.created_at);
  const dateStr = d.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" });
  const timeStr = d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const statusColor = STATUS_COLOR[log.state] ?? "#9ca3af";
  const statusLabel = STATUS_LABEL[log.state] ?? log.state;

  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    fontWeight: 600,
    color: "#a8a198",
    letterSpacing: "0.4px",
    textTransform: "uppercase",
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = {
    fontSize: 14,
    color: "#1d1a15",
  };

  const handleSaveNotes = () => {
    setSavingNotes(true);
    const newNotes = notesText.trim() === "" ? "" : notesText;
    api.updateReceptionLog(token, log.id, { staff_notes: newNotes })
      .then(() => {
        onNotesUpdate(log.id, newNotes === "" ? null : newNotes);
        setEditingNotes(false);
      })
      .catch(() => {})
      .finally(() => setSavingNotes(false));
  };

  const handleClearNotes = () => {
    setNotesText("");
    setSavingNotes(true);
    api.updateReceptionLog(token, log.id, { staff_notes: "" })
      .then(() => {
        onNotesUpdate(log.id, null);
        setEditingNotes(false);
      })
      .catch(() => {})
      .finally(() => setSavingNotes(false));
  };

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fffefb", borderRadius: 16, padding: 32, width: 480, maxWidth: "90vw", boxShadow: "0 20px 60px rgba(0,0,0,0.15)", position: "relative" }}
      >
        <button
          onClick={onClose}
          style={{ position: "absolute", top: 16, right: 16, background: "none", border: "none", cursor: "pointer", color: "#a8a198", fontSize: 18, lineHeight: 1, padding: 4 }}
        >
          ✕
        </button>
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase", marginBottom: 6 }}>受付詳細</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#1d1a15" }}>{log.visitor_name}</div>
          <div style={{ fontSize: 13, color: "#6b6559", marginTop: 4 }}>{dateStr} {timeStr}</div>
          {visitorHistory !== null && visitorHistory.count > 1 && (
            <div style={{ marginTop: 10, display: "inline-flex", flexDirection: "column", background: "#fdf6e3", border: "1px solid #e8d5a3", borderRadius: 8, padding: "7px 12px" }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#c8a96e" }}>
                🔁 {visitorHistory.count}回目の来訪
              </span>
              {visitorHistory.first_visit && (
                <span style={{ fontSize: 11, color: "#9a8660", marginTop: 2 }}>
                  初回来訪: {new Date(visitorHistory.first_visit).toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}
                </span>
              )}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <span style={{ display: "inline-block", padding: "3px 10px", borderRadius: 999, background: `${statusColor}22`, color: statusColor, fontSize: 12, fontWeight: 600 }}>
              {statusLabel}
            </span>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 20 }}>
          <div>
            <div style={labelStyle}>訪問者名</div>
            <div style={valueStyle}>{log.visitor_name}</div>
          </div>
          <div>
            <div style={labelStyle}>会社名</div>
            <div style={valueStyle}>{log.company || "—"}</div>
          </div>
          <div>
            <div style={labelStyle}>担当者</div>
            <div style={valueStyle}>{log.staff || "—"}</div>
          </div>
          <div>
            <div style={labelStyle}>目的</div>
            <div style={valueStyle}>{log.purpose || "—"}</div>
          </div>
          <div>
            <div style={labelStyle}>受付方法</div>
            <div style={valueStyle}>{translateMethod(log.method)}</div>
          </div>
          <div>
            <div style={labelStyle}>ステータス</div>
            <div style={valueStyle}>{statusLabel}</div>
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <div style={labelStyle}>受付日時</div>
            <div style={valueStyle}>{dateStr} {timeStr}</div>
          </div>
        </div>
        <div style={{ marginTop: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase" }}>スタッフメモ</div>
            <button
              onClick={() => setEditingNotes((v) => !v)}
              style={{ background: "none", border: "1px solid #d8d3c7", borderRadius: 6, padding: "3px 10px", fontSize: 11.5, color: "#6b6559", cursor: "pointer" }}
            >
              {editingNotes ? "閉じる" : "メモを追加/編集"}
            </button>
          </div>
          {log.staff_notes && !editingNotes && (
            <div style={{ background: "#fef9c3", border: "1px solid #fef08a", borderRadius: 6, padding: "10px 12px", fontSize: 13, color: "#854d0e", marginTop: 12, whiteSpace: "pre-wrap" }}>
              {log.staff_notes}
            </div>
          )}
          {editingNotes && (
            <div>
              <textarea
                value={notesText}
                onChange={(e) => setNotesText(e.target.value)}
                style={{ width: "100%", padding: 8, border: "1px solid #d8d3c7", borderRadius: 6, fontSize: 13, fontFamily: "inherit", resize: "vertical", minHeight: 60, background: "#fffefb", marginTop: 8, boxSizing: "border-box" }}
              />
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button
                  onClick={handleSaveNotes}
                  disabled={savingNotes}
                  style={{ background: "#1d1a15", color: "#fffefb", border: "none", borderRadius: 6, padding: "6px 16px", fontSize: 12, fontWeight: 600, cursor: savingNotes ? "not-allowed" : "pointer", opacity: savingNotes ? 0.7 : 1 }}
                >
                  保存
                </button>
                <button
                  onClick={handleClearNotes}
                  disabled={savingNotes}
                  style={{ background: "none", border: "1px solid #d8d3c7", borderRadius: 6, padding: "6px 16px", fontSize: 12, color: "#6b6559", cursor: savingNotes ? "not-allowed" : "pointer", opacity: savingNotes ? 0.7 : 1 }}
                >
                  クリア
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusSelect({ log, token, onUpdate }: { log: ReceptionLog; token: string; onUpdate: (id: string, state: string) => void }) {
  const [updating, setUpdating] = useState(false);
  const state = log.state ?? "received";
  const bg = STATUS_COLOR[state] ?? "#9ca3af";

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    e.stopPropagation();
    const newState = e.target.value;
    setUpdating(true);
    api.updateReceptionLog(token, log.id, { state: newState })
      .then(() => onUpdate(log.id, newState))
      .catch(() => {})
      .finally(() => setUpdating(false));
  };

  return (
    <select
      value={state}
      onChange={handleChange}
      onClick={(e) => e.stopPropagation()}
      disabled={updating}
      style={{ backgroundColor: bg, color: "#ffffff", border: "none", borderRadius: 12, padding: "3px 10px", fontSize: 12, fontWeight: 600, cursor: "pointer", appearance: "none", opacity: updating ? 0.6 : 1 }}
    >
      <option value="received">受付済み</option>
      <option value="notified">通知済み</option>
      <option value="completed">完了</option>
      <option value="cancelled">キャンセル</option>
    </select>
  );
}

export default function ReceptionLogsPage() {
  const router = useRouter();
  const [logs, setLogs] = useState<ReceptionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [dateFilter, setDateFilter] = useState<DateFilter>("today");
  const [page, setPage] = useState(1);
  const [selectedLog, setSelectedLog] = useState<ReceptionLog | null>(null);
  const [token, setToken] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [modal, setModal] = useState<{ msg: string; confirmLabel?: string; action: () => Promise<void> } | null>(null);
  const [methodFilter, setMethodFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");

  useEffect(() => {
    const t = getAccessToken();
    if (!t) { router.push("/login"); return; }
    setToken(t);
    api.listReception(t)
      .then((data) => { setLogs(data); setLastRefreshed(new Date()); })
      .catch(() => { clearTokens(); router.push("/login"); })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!autoRefresh || !token) return;
    const id = setInterval(() => {
      api.listReception(token)
        .then((data) => { setLogs(data); setLastRefreshed(new Date()); })
        .catch(() => {});
    }, 30000);
    return () => clearInterval(id);
  }, [autoRefresh, token]);

  const handleStateUpdate = (id: string, state: string) => {
    setLogs((prev) => prev.map((l) => l.id === id ? { ...l, state } : l));
  };

  const handleNotesUpdate = (id: string, staff_notes: string | null) => {
    setLogs((prev) => prev.map((l) => l.id === id ? { ...l, staff_notes } : l));
    setSelectedLog((prev) => prev && prev.id === id ? { ...prev, staff_notes } : prev);
  };

  const handleDeleteSingle = (e: React.MouseEvent, logId: string) => {
    e.stopPropagation();
    setModal({
      msg: "この受付ログを削除しますか？",
      action: async () => {
        await api.deleteReceptionLog(token, logId);
        setLogs((prev) => prev.filter((l) => l.id !== logId));
        setSelectedIds((prev) => { const s = new Set(prev); s.delete(logId); return s; });
      },
    });
  };

  const handleBulkDelete = () => {
    setModal({
      msg: `${selectedIds.size}件の受付ログを削除しますか？`,
      action: async () => {
        setBulkDeleting(true);
        try {
          const { deleted } = await api.bulkDeleteReceptionLogs(token, [...selectedIds]);
          if (deleted > 0) setLogs((prev) => prev.filter((l) => !selectedIds.has(l.id)));
          setSelectedIds(new Set());
        } finally {
          setBulkDeleting(false);
        }
      },
    });
  };

  const handleBulkStateUpdate = (newState: string) => {
    const label = newState === "notified" ? "通知済み" : "完了";
    setModal({
      msg: `${selectedIds.size}件を${label}に変更しますか？`,
      confirmLabel: "変更する",
      action: async () => {
        setBulkDeleting(true);
        const ids = [...selectedIds];
        await Promise.all(ids.map(id =>
          api.updateReceptionLog(token, id, { state: newState }).catch(() => {})
        ));
        setLogs(prev => prev.map(l => selectedIds.has(l.id) ? { ...l, state: newState } : l));
        setSelectedIds(new Set());
        setBulkDeleting(false);
      },
    });
  };

  const filtered = useMemo(() => {
    const now = new Date();
    const startOf = (offset: number) => {
      const d = new Date(now);
      d.setDate(d.getDate() - offset);
      d.setHours(0, 0, 0, 0);
      return d;
    };
    const cutoff: Record<DateFilter, Date> = {
      today:  startOf(0),
      week:   startOf(7),
      month:  startOf(30),
      all:    startOf(30),
    };
    let list = logs.filter((r) => new Date(r.created_at) >= cutoff[dateFilter]);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((r) =>
        r.visitor_name.toLowerCase().includes(q) ||
        (r.company ?? "").toLowerCase().includes(q)
      );
    }
    if (methodFilter) list = list.filter(r => r.method === methodFilter);
    if (stateFilter) list = list.filter(r => r.state === stateFilter);
    return list;
  }, [logs, dateFilter, search, methodFilter, stateFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const waitingCount = useMemo(() => {
    return logs.filter((l) => {
      if (l.state !== "received") return false;
      const elapsedMin = (Date.now() - new Date(l.created_at).getTime()) / 60000;
      return elapsedMin >= 15;
    }).length;
  }, [logs]);

  const receptionUnread = useMemo(() => {
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    return logs.filter((l) => l.state === "received" && new Date(l.created_at) >= todayStart).length;
  }, [logs]);

  const allPageSelected = paginated.length > 0 && paginated.every((r) => selectedIds.has(r.id));
  const somePageSelected = paginated.some((r) => selectedIds.has(r.id));

  const toggleSelectAll = () => {
    if (allPageSelected) {
      setSelectedIds((prev) => {
        const s = new Set(prev);
        paginated.forEach((r) => s.delete(r.id));
        return s;
      });
    } else {
      setSelectedIds((prev) => {
        const s = new Set(prev);
        paginated.forEach((r) => s.add(r.id));
        return s;
      });
    }
  };

  const toggleSelectRow = (id: string) => {
    setSelectedIds((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return s;
    });
  };

  return (
    <>
    {modal && (
      <ConfirmModal
        message={modal.msg}
        confirmLabel={modal.confirmLabel}
        onConfirm={async () => { const action = modal.action; setModal(null); await action(); }}
        onCancel={() => setModal(null)}
      />
    )}
    <AdminShell
      active="reception"
      title="受付ログ"
      breadcrumb="ホーム / 受付ログ"
      subtitle={`過去30日 · 合計 ${logs.length} 件`}
      receptionUnread={receptionUnread}
      actions={
        waitingCount >= 3 ? (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            background: "#fffbeb", border: "1px solid #fcd34d",
            borderRadius: 999, padding: "4px 12px",
            fontSize: 12, fontWeight: 700, color: "#92400e",
          }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#f59e0b", display: "inline-block", animation: "mk-pulse 2s ease-in-out infinite" }} />
            {waitingCount}件対応待ち
          </span>
        ) : undefined
      }
    >
      <style>{`@keyframes mk-pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
      {selectedLog && (
        <ReceptionDetailModal log={selectedLog} token={token} onClose={() => setSelectedLog(null)} onNotesUpdate={handleNotesUpdate} />
      )}

      <div style={{ display: "flex", gap: 10, marginBottom: 18, alignItems: "center", flexWrap: "wrap", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, width: 280 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            placeholder="来訪者名・会社名で検索"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
          />
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["today", "week", "month", "all"] as DateFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => { setDateFilter(f); setPage(1); }}
              style={{
                padding: "6px 12px", fontSize: 11.5,
                background: dateFilter === f ? "#1d1a15" : "#fffefb",
                color: dateFilter === f ? "#fffefb" : "#6b6559",
                border: `1px solid ${dateFilter === f ? "#1d1a15" : "#d8d3c7"}`,
                borderRadius: 999, cursor: "pointer",
              }}
            >
              {DATE_LABELS[f]}
            </button>
          ))}
        </div>
        <select
          value={methodFilter}
          onChange={(e) => { setMethodFilter(e.target.value); setPage(1); }}
          style={SELECT_STYLE}
        >
          <option value="">受付経路: 全て</option>
          <option value="form">フォーム</option>
          <option value="qr">QR</option>
          <option value="phone">電話</option>
          <option value="other">その他</option>
        </select>
        <select
          value={stateFilter}
          onChange={(e) => { setStateFilter(e.target.value); setPage(1); }}
          style={SELECT_STYLE}
        >
          <option value="">ステータス: 全て</option>
          <option value="received">受付済み</option>
          <option value="notified">通知済み</option>
          <option value="completed">完了</option>
          <option value="cancelled">キャンセル</option>
        </select>
        <button
          onClick={() => {
            const token = getAccessToken();
            if (token) downloadCsv(token).catch(() => {});
          }}
          style={{
            padding: "6px 14px", fontSize: 11.5,
            background: "#fffefb", color: "#6b6559",
            border: "1px solid #d8d3c7", borderRadius: 999, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 5,
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          CSV出力
        </button>
        <button
          onClick={() => {
            const token = getAccessToken();
            if (token) downloadContactsCsv(token).catch(() => {});
          }}
          style={{
            padding: "6px 14px", fontSize: 11.5,
            background: "#fffefb", color: "#6b6559",
            border: "1px solid #d8d3c7", borderRadius: 999, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 5,
          }}
        >
          👤 連絡先CSV
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => setAutoRefresh((v) => !v)}
            style={{
              border: `1px solid ${autoRefresh ? "#86efac" : "#efece5"}`,
              borderRadius: 20,
              padding: "4px 12px",
              fontSize: 12,
              cursor: "pointer",
              background: autoRefresh ? "#f0fdf4" : "#f9f8f6",
              color: autoRefresh ? "#16a34a" : "#a8a198",
            }}
          >
            自動更新 {autoRefresh ? "ON" : "OFF"}
          </button>
          {autoRefresh && (
            <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#a8a198" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#16a34a", display: "inline-block", animation: "mk-pulse 2s ease-in-out infinite" }} />
              30秒ごとに更新
            </span>
          )}
          {lastRefreshed && (
            <span style={{ fontSize: 11, color: "#a8a198" }}>最終更新: {lastRefreshed.toLocaleTimeString("ja-JP")}</span>
          )}
        </div>
      </div>

      <MkCard padding="0">
        {loading ? (
          <div style={{ padding: "48px 20px", textAlign: "center", color: "#a8a198" }}>読み込み中…</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: "48px 20px", textAlign: "center", color: "#a8a198" }}>受付記録がありません</div>
        ) : (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#f4f1ea", fontSize: 10.5, color: "#a8a198", textAlign: "left", letterSpacing: "0.3px" }}>
                  <th style={{ padding: "11px 14px", fontWeight: 600 }}>
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      ref={(el) => { if (el) el.indeterminate = !allPageSelected && somePageSelected; }}
                      onChange={toggleSelectAll}
                      onClick={(e) => e.stopPropagation()}
                      style={{ width: 16, height: 16, cursor: "pointer", accentColor: "#2d6a4f" }}
                    />
                  </th>
                  {["日付", "時刻", "来訪者", "会社", "用件", "受付経路", "担当", "状態", ""].map((h) => (
                    <th key={h} style={{ padding: "11px 14px", fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody style={{ fontSize: 12.5 }}>
                {paginated.map((r, i) => {
                  const d = new Date(r.created_at);
                  const isSelected = selectedIds.has(r.id);
                  const agingLevel = getAgingLevel(r);
                  return (
                    <RowWithHover
                      key={r.id}
                      borderTop={i > 0}
                      selected={isSelected}
                      onClick={() => setSelectedLog(r)}
                      agingLevel={agingLevel}
                    >
                      <td style={{ padding: "12px 14px" }} onClick={(e) => { e.stopPropagation(); toggleSelectRow(r.id); }}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectRow(r.id)}
                          onClick={(e) => e.stopPropagation()}
                          style={{ width: 16, height: 16, cursor: "pointer", accentColor: "#2d6a4f" }}
                        />
                      </td>
                      <td style={{ padding: "12px 14px", color: "#6b6559", fontFamily: "monospace", fontSize: 11.5 }}>
                        {d.toLocaleDateString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit" })}
                      </td>
                      <td style={{ padding: "12px 14px", color: "#6b6559", fontFamily: "monospace", fontSize: 11.5 }}>
                        {d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}
                      </td>
                      <td style={{ padding: "12px 14px", color: "#1d1a15", fontWeight: 500 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          {r.visitor_name}
                          {r.staff_notes && <span style={{ fontSize: 10, fontWeight: 600, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a", borderRadius: 4, padding: "1px 6px" }}>メモあり</span>}
                          {agingLevel === "alert" && (
                            <span style={{ fontSize: 10, fontWeight: 600, background: "#fff7ed", color: "#c2410c", border: "1px solid #fed7aa", borderRadius: 4, padding: "1px 6px" }}>15分以上待機中</span>
                          )}
                          {agingLevel === "urgent" && (
                            <span style={{ fontSize: 10, fontWeight: 700, background: "#fef2f2", color: "#b91c1c", border: "1px solid #fecaca", borderRadius: 4, padding: "1px 6px" }}>30分以上待機中⚠</span>
                          )}
                        </span>
                      </td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.company || "—"}</td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.purpose || "—"}</td>
                      <td style={{ padding: "12px 14px" }}>
                        <span style={{ fontSize: 10.5, color: "#6b6559", background: "#f4f1ea", padding: "2px 8px", borderRadius: 3, border: "1px solid #efece5" }}>
                          {r.method || "フォーム"}
                        </span>
                      </td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.staff || "—"}</td>
                      <td style={{ padding: "12px 14px" }}>
                        <StatusSelect log={r} token={token} onUpdate={handleStateUpdate} />
                      </td>
                      <td style={{ padding: "12px 14px", display: "flex", alignItems: "center", gap: 4 }}>
                        <button
                          onClick={(e) => handleDeleteSingle(e, r.id)}
                          style={{ background: "transparent", border: "none", cursor: "pointer", color: "#dc2626", padding: "4px 8px", borderRadius: 4, fontSize: 12 }}
                        >
                          🗑
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setSelectedLog(r); }}
                          style={{ background: "none", border: "none", color: "#a8a198", cursor: "pointer", padding: 2 }}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/>
                          </svg>
                        </button>
                      </td>
                    </RowWithHover>
                  );
                })}
              </tbody>
            </table>

            <div style={{ padding: "14px 20px", display: "flex", alignItems: "center", borderTop: "1px solid #efece5", fontSize: 11.5 }}>
              <span style={{ color: "#a8a198" }}>{paginated.length} / {filtered.length} 件</span>
              <span style={{ flex: 1 }} />
              <div style={{ display: "flex", gap: 4 }}>
                {["←", ...Array.from({ length: Math.min(totalPages, 5) }, (_, i) => String(i + 1)), "→"].map((p, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      if (p === "←" && page > 1) setPage(page - 1);
                      if (p === "→" && page < totalPages) setPage(page + 1);
                      if (!isNaN(Number(p))) setPage(Number(p));
                    }}
                    style={{
                      minWidth: 28, height: 28, border: "1px solid #d8d3c7", borderRadius: 5,
                      background: p === String(page) ? "#1d1a15" : "#fffefb",
                      color: p === String(page) ? "#fffefb" : "#2d2a24",
                      fontSize: 11.5, cursor: "pointer",
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </MkCard>

      {selectedIds.size > 0 && (
        <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#1d1a15", color: "#f4f0e8", padding: "16px 24px", display: "flex", alignItems: "center", gap: 16, zIndex: 100 }}>
          <span style={{ fontSize: 13 }}>{selectedIds.size}件を選択中</span>
          <button
            onClick={() => handleBulkStateUpdate("notified")}
            disabled={bulkDeleting}
            style={{ background: "#3b82f6", color: "#ffffff", border: "none", borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: bulkDeleting ? "not-allowed" : "pointer", opacity: bulkDeleting ? 0.7 : 1 }}
          >
            ✓ 通知済みに変更
          </button>
          <button
            onClick={() => handleBulkStateUpdate("completed")}
            disabled={bulkDeleting}
            style={{ background: "#10b981", color: "#ffffff", border: "none", borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: bulkDeleting ? "not-allowed" : "pointer", opacity: bulkDeleting ? 0.7 : 1 }}
          >
            ✓ 完了に変更
          </button>
          <button
            onClick={handleBulkDelete}
            disabled={bulkDeleting}
            style={{ background: "#dc2626", color: "#ffffff", border: "none", borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: bulkDeleting ? "not-allowed" : "pointer", opacity: bulkDeleting ? 0.7 : 1 }}
          >
            削除
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            style={{ background: "transparent", color: "#a8a198", border: "1px solid #3d3a34", borderRadius: 6, padding: "8px 18px", fontSize: 13, cursor: "pointer" }}
          >
            選択解除
          </button>
        </div>
      )}
    </AdminShell>
    </>
  );
}

function RowWithHover({ children, borderTop, selected, onClick, agingLevel = "fresh" }: { children: React.ReactNode; borderTop: boolean; selected: boolean; onClick: () => void; agingLevel?: AgingLevel }) {
  const [hovered, setHovered] = useState(false);
  return (
    <tr
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        borderTop: borderTop ? "1px solid #efece5" : "none",
        background: selected ? "#f0fdf4" : hovered ? "#faf8f4" : "transparent",
        cursor: "pointer",
        borderLeft: AGING_BORDER[agingLevel],
        animation: agingLevel === "urgent" ? "mk-pulse 1.5s ease-in-out infinite" : undefined,
      }}
    >
      {children}
    </tr>
  );
}
