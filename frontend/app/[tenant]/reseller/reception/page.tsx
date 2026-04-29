"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, ResellerReceptionItem, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle } from "@/components/AdminShell";

const LIMIT = 100;

const inputStyle: React.CSSProperties = {
  height: 34,
  border: "1px solid #efece5",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  outline: "none",
  background: "#fffefb",
  color: "#1d1a15",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
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

function StatusPill({ state }: { state: string | null }) {
  const s = state ?? "";
  let bg = "rgba(168,161,152,0.15)";
  let color = "#a8a198";
  let label = s || "—";

  if (s === "received") { bg = "rgba(234,179,8,0.15)"; color = "#b45309"; label = "受付済"; }
  else if (s === "notified") { bg = "rgba(59,130,246,0.15)"; color = "#1d4ed8"; label = "通知済"; }
  else if (s === "completed") { bg = "rgba(74,124,78,0.15)"; color = "#4a7c4e"; label = "完了"; }
  else if (s === "cancelled") { bg = "rgba(168,161,152,0.15)"; color = "#a8a198"; label = "キャンセル"; }

  return (
    <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 999, background: bg, color, fontSize: 11, fontWeight: 600 }}>
      {label}
    </span>
  );
}

function ResellerReceptionDetailModal({ log, token, onClose, onNotesUpdate }: { log: ResellerReceptionItem; token: string; onClose: () => void; onNotesUpdate: (id: string, notes: string | null) => void }) {
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesText, setNotesText] = useState(log.staff_notes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);

  useEffect(() => {
    setNotesText(log.staff_notes ?? "");
    setEditingNotes(false);
  }, [log.id, log.staff_notes]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const d = new Date(log.created_at);
  const dateStr = d.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" });
  const timeStr = d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const statusColor = STATUS_COLOR[log.state ?? ""] ?? "#9ca3af";
  const statusLabel = STATUS_LABEL[log.state ?? ""] ?? (log.state ?? "—");

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
          <div style={{ marginTop: 10 }}>
            <span style={{ display: "inline-block", padding: "3px 10px", borderRadius: 999, background: `${statusColor}22`, color: statusColor, fontSize: 12, fontWeight: 600, border: `1px solid #c8a96e` }}>
              {statusLabel}
            </span>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 20 }}>
          <div>
            <div style={labelStyle}>テナント名</div>
            <div style={valueStyle}>{log.tenant_name}</div>
          </div>
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

function RowWithHover({ children, onClick, selected }: { children: React.ReactNode; onClick: () => void; selected?: boolean }) {
  const [hovered, setHovered] = useState(false);
  return (
    <tr
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ borderBottom: "1px solid #f4f1ea", background: selected ? "#fef9ec" : hovered ? "#faf8f4" : "transparent", cursor: "pointer" }}
    >
      {children}
    </tr>
  );
}

export default function ResellerReceptionPage() {
  const token = getAccessToken() ?? "";
  const [logs, setLogs] = useState<ResellerReceptionItem[]>([]);
  const [customers, setCustomers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [selectedLog, setSelectedLog] = useState<ResellerReceptionItem | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const [filterTenant, setFilterTenant] = useState("");
  const [filterQ, setFilterQ] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [methodFilter, setMethodFilter] = useState("");

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetAndFetch = (overrides: Record<string, string | undefined> = {}) => {
    setOffset(0);
    setLoading(true);
    const params = {
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
      date_from: (overrides.date_from ?? filterDateFrom) || undefined,
      date_to: (overrides.date_to ?? filterDateTo) || undefined,
      offset: 0,
      limit: LIMIT,
    };
    api.listResellerReception(token, params)
      .then((data) => {
        setLogs(data);
        setHasMore(data.length === LIMIT);
        setOffset(data.length);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    api.listResellerCustomers(token).then(setCustomers);
    resetAndFetch();
  }, []);

  const handleTenantChange = (v: string) => {
    setFilterTenant(v);
    resetAndFetch({ tenant_id: v });
  };

  const handleStatusChange = (v: string) => {
    setFilterStatus(v);
    resetAndFetch({ status: v });
  };

  const handleDateFromChange = (v: string) => {
    setFilterDateFrom(v);
    resetAndFetch({ date_from: v });
  };

  const handleDateToChange = (v: string) => {
    setFilterDateTo(v);
    resetAndFetch({ date_to: v });
  };

  const handleQChange = (v: string) => {
    setFilterQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => resetAndFetch({ q: v }), 300);
  };

  const loadMore = () => {
    setLoading(true);
    const params = {
      tenant_id: filterTenant || undefined,
      q: filterQ || undefined,
      status: filterStatus || undefined,
      date_from: filterDateFrom || undefined,
      date_to: filterDateTo || undefined,
      offset,
      limit: LIMIT,
    };
    api.listResellerReception(token, params)
      .then((data) => {
        setLogs((prev) => [...prev, ...data]);
        setHasMore(data.length === LIMIT);
        setOffset((prev) => prev + data.length);
      })
      .finally(() => setLoading(false));
  };

  const handleNotesUpdate = (id: string, staff_notes: string | null) => {
    setLogs((prev) => prev.map((l) => l.id === id ? { ...l, staff_notes } : l));
    setSelectedLog((prev) => prev && prev.id === id ? { ...prev, staff_notes } : prev);
  };

  const filteredLogs = useMemo(() => {
    let list = logs;
    if (methodFilter) list = list.filter(r => r.method === methodFilter);
    return list;
  }, [logs, methodFilter]);

  const allSelected = filteredLogs.length > 0 && filteredLogs.every((r) => selectedIds.has(r.id));
  const someSelected = filteredLogs.some((r) => selectedIds.has(r.id));

  const handleBulkStateUpdate = async (newState: string) => {
    const label = newState === "notified" ? "通知済み" : "完了";
    if (!window.confirm(`${selectedIds.size}件を${label}に変更しますか？`)) return;
    const ids = [...selectedIds];
    await Promise.all(ids.map(id =>
      api.updateReceptionLog(token, id, { state: newState }).catch(() => {})
    ));
    setLogs(prev => prev.map(l => selectedIds.has(l.id) ? { ...l, state: newState } : l));
    setSelectedIds(new Set());
  };

  const handleBulkDelete = () => {
    if (!window.confirm(`${selectedIds.size}件の受付ログを削除しますか？`)) return;
    setBulkDeleting(true);
    api.bulkDeleteReceptionLogs(token, [...selectedIds])
      .then(({ deleted }) => {
        if (deleted > 0) {
          setLogs((prev) => prev.filter((l) => !selectedIds.has(l.id)));
        }
        setSelectedIds(new Set());
      })
      .catch(() => {})
      .finally(() => setBulkDeleting(false));
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds((prev) => {
        const s = new Set(prev);
        filteredLogs.forEach((r) => s.delete(r.id));
        return s;
      });
    } else {
      setSelectedIds((prev) => {
        const s = new Set(prev);
        filteredLogs.forEach((r) => s.add(r.id));
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
    <div style={{ padding: "28px 32px" }}>
      {selectedLog && (
        <ResellerReceptionDetailModal log={selectedLog} token={token} onClose={() => setSelectedLog(null)} onNotesUpdate={handleNotesUpdate} />
      )}

      <div style={{ display: "flex", alignItems: "center", marginBottom: 24, gap: 12 }}>
        <MkSectionTitle title="受付ログ" subtitle={`${filteredLogs.length} 件${hasMore ? "+" : ""}（管理顧客テナント全体）`} />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <select style={selectStyle} value={filterTenant} onChange={(e) => handleTenantChange(e.target.value)}>
          <option value="">全テナント</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <input
          style={{ ...inputStyle, width: 200 }}
          placeholder="訪問者名・会社名で検索"
          value={filterQ}
          onChange={(e) => handleQChange(e.target.value)}
        />
        <select
          value={methodFilter}
          onChange={(e) => setMethodFilter(e.target.value)}
          style={SELECT_STYLE}
        >
          <option value="">受付経路: 全て</option>
          <option value="form">フォーム</option>
          <option value="qr">QR</option>
          <option value="phone">電話</option>
          <option value="other">その他</option>
        </select>
        <select style={selectStyle} value={filterStatus} onChange={(e) => handleStatusChange(e.target.value)}>
          <option value="">全ステータス</option>
          <option value="received">受付済</option>
          <option value="notified">通知済</option>
          <option value="completed">完了</option>
          <option value="cancelled">キャンセル</option>
        </select>
        <input
          type="date"
          style={inputStyle}
          value={filterDateFrom}
          onChange={(e) => handleDateFromChange(e.target.value)}
          title="開始日"
        />
        <span style={{ lineHeight: "34px", color: "#a8a198", fontSize: 12 }}>〜</span>
        <input
          type="date"
          style={inputStyle}
          value={filterDateTo}
          onChange={(e) => handleDateToChange(e.target.value)}
          title="終了日"
        />
        <div style={{ marginLeft: "auto" }}>
          <button
            onClick={() => {
              api.exportResellerReceptionCsv(token, {
                tenant_id: filterTenant || undefined,
                q: filterQ || undefined,
                status: filterStatus || undefined,
                date_from: filterDateFrom || undefined,
                date_to: filterDateTo || undefined,
              }).then((blob) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `reception_${new Date().toISOString().slice(0, 10)}.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }).catch(() => {});
            }}
            style={{ height: 34, padding: "0 14px", border: "1px solid #c8a96e", borderRadius: 6, fontSize: 13, cursor: "pointer", background: "#fffefb", color: "#b88b44", display: "flex", alignItems: "center", gap: 5 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            CSV出力
          </button>
        </div>
      </div>

      {loading && logs.length === 0 ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <>
          <MkCard padding="0">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #efece5" }}>
                  <th style={{ padding: "10px 14px", width: 40 }}>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(el) => { if (el) el.indeterminate = !allSelected && someSelected; }}
                      onChange={toggleSelectAll}
                      onClick={(e) => e.stopPropagation()}
                      style={{ width: 15, height: 15, cursor: "pointer", accentColor: "#c8a96e" }}
                    />
                  </th>
                  {["テナント名", "訪問者", "会社名", "担当者", "ステータス", "日時"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px", whiteSpace: "nowrap" as const }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((log) => (
                  <RowWithHover key={log.id} selected={selectedIds.has(log.id)} onClick={() => setSelectedLog(log)}>
                    <td style={{ padding: "10px 14px" }} onClick={(e) => { e.stopPropagation(); toggleSelectRow(log.id); }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(log.id)}
                        onChange={() => toggleSelectRow(log.id)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ width: 15, height: 15, cursor: "pointer", accentColor: "#c8a96e" }}
                      />
                    </td>
                    <td style={{ padding: "10px 14px", fontWeight: 600, color: "#1d1a15", whiteSpace: "nowrap" as const }}>{log.tenant_name}</td>
                    <td style={{ padding: "10px 14px", color: "#1d1a15" }}>
                      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        {log.visitor_name}
                        {log.staff_notes && <span style={{ fontSize: 10, fontWeight: 600, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a", borderRadius: 4, padding: "1px 6px" }}>メモあり</span>}
                      </span>
                    </td>
                    <td style={{ padding: "10px 14px", color: "#6b6559" }}>{log.company ?? "—"}</td>
                    <td style={{ padding: "10px 14px", color: "#6b6559" }}>{log.staff ?? "—"}</td>
                    <td style={{ padding: "10px 14px" }}><StatusPill state={log.state} /></td>
                    <td style={{ padding: "10px 14px", color: "#a8a198", whiteSpace: "nowrap" as const }}>{new Date(log.created_at).toLocaleString("ja-JP")}</td>
                  </RowWithHover>
                ))}
                {filteredLogs.length === 0 && !loading && (
                  <tr>
                    <td colSpan={7} style={{ padding: "32px", textAlign: "center" as const, color: "#a8a198" }}>受付ログがありません</td>
                  </tr>
                )}
              </tbody>
            </table>
          </MkCard>

          {hasMore && (
            <div style={{ marginTop: 16, textAlign: "center" as const }}>
              <button
                onClick={loadMore}
                disabled={loading}
                style={{ height: 36, padding: "0 24px", border: "1px solid #c8a96e", borderRadius: 6, fontSize: 13, cursor: "pointer", background: "#fffefb", color: "#8a5a1e" }}
              >
                {loading ? "読み込み中…" : "もっと読み込む"}
              </button>
            </div>
          )}
        </>
      )}

      {selectedIds.size > 0 && (
        <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#2a2620", color: "#f4f0e8", padding: "16px 24px", display: "flex", alignItems: "center", gap: 16, zIndex: 100 }}>
          <span style={{ fontSize: 13 }}>{selectedIds.size}件選択中</span>
          <button
            onClick={() => handleBulkStateUpdate("notified")}
            style={{ background: "#c8a96e", color: "#ffffff", border: "none", borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            通知済みに変更
          </button>
          <button
            onClick={() => handleBulkStateUpdate("completed")}
            style={{ background: "#4a7c4e", color: "#ffffff", border: "none", borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            完了に変更
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
            style={{ background: "transparent", color: "#a8a198", border: "1px solid #4a4640", borderRadius: 6, padding: "8px 18px", fontSize: 13, cursor: "pointer" }}
          >
            選択解除
          </button>
        </div>
      )}
    </div>
  );
}
