"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { api, OperatorReceptionItem, OperatorTenant } from "@/lib/api";
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
  background: "#faf8f4",
  color: "#1d1a15",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};

const SELECT_STYLE: React.CSSProperties = {
  height: 34,
  border: "1px solid #3a3528",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  background: "#1a1810",
  color: "#f0ead6",
  cursor: "pointer",
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

function OperatorReceptionDetailModal({ log, token, onClose, onNotesUpdate }: { log: OperatorReceptionItem; token: string; onClose: () => void; onNotesUpdate: (id: string, notes: string | null) => void }) {
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
  const statusLabel = STATUS_LABEL[log.state ?? ""] ?? (log.state || "—");

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
            <div style={labelStyle}>テナント名</div>
            <div style={valueStyle}>{log.tenant_name}</div>
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
          <div>
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

function RowWithHover({ children, selected, onClick, onCheckClick }: { children: React.ReactNode; selected: boolean; onClick: () => void; onCheckClick: (e: React.MouseEvent) => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <tr
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ borderBottom: "1px solid #f4f1ea", background: selected ? "#f0fdf4" : hovered ? "#faf8f4" : "transparent", cursor: "pointer" }}
    >
      {children}
    </tr>
  );
}

export default function OperatorReceptionPage() {
  const token = getAccessToken() ?? "";
  const [logs, setLogs] = useState<OperatorReceptionItem[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [selectedLog, setSelectedLog] = useState<OperatorReceptionItem | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [bulkUpdating, setBulkUpdating] = useState(false);

  const [filterReseller, setFilterReseller] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterQ, setFilterQ] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [methodFilter, setMethodFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const buildParams = useCallback(
    (overrides: Record<string, string | undefined> = {}, currentOffset = 0) => ({
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
      method: (overrides.method ?? methodFilter) || undefined,
      date_from: (overrides.date_from ?? filterDateFrom) || undefined,
      date_to: (overrides.date_to ?? filterDateTo) || undefined,
      offset: currentOffset,
      limit: LIMIT,
    }),
    [filterReseller, filterTenant, filterQ, filterStatus, methodFilter, filterDateFrom, filterDateTo]
  );

  const fetchLogs = useCallback(
    (overrides: Record<string, string | undefined> = {}, append = false) => {
      setLoading(true);
      const currentOffset = append ? offset : 0;
      api.listOperatorReception(token, buildParams(overrides, currentOffset))
        .then((data) => {
          setLogs((prev) => (append ? [...prev, ...data] : data));
          setHasMore(data.length === LIMIT);
          if (append) setOffset(currentOffset + data.length);
          else setOffset(data.length);
        })
        .finally(() => setLoading(false));
    },
    [token, buildParams, offset]
  );

  useEffect(() => {
    api.listResellers(token).then(setResellers);
    api.listOperatorTenants(token, { page_size: 200, page: 1 }).then((res) => setTenants(res.items));
    fetchLogs();
  }, []);

  useEffect(() => {
    if (!autoRefresh || !token) return;
    const id = setInterval(() => {
      const params = {
        reseller_id: filterReseller || undefined,
        tenant_id: filterTenant || undefined,
        q: filterQ || undefined,
        status: filterStatus || undefined,
        method: methodFilter || undefined,
        date_from: filterDateFrom || undefined,
        date_to: filterDateTo || undefined,
        offset: 0,
        limit: LIMIT,
      };
      api.listOperatorReception(token, params)
        .then((data) => {
          setLogs(data);
          setHasMore(data.length === LIMIT);
          setOffset(data.length);
          setLastRefreshed(new Date());
        })
        .catch(() => {});
    }, 30000);
    return () => clearInterval(id);
  }, [autoRefresh, token, filterReseller, filterTenant, filterQ, filterStatus, methodFilter, filterDateFrom, filterDateTo]);

  const resetAndFetch = (overrides: Record<string, string | undefined> = {}) => {
    setOffset(0);
    setLoading(true);
    const params = {
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
      method: (overrides.method ?? methodFilter) || undefined,
      date_from: (overrides.date_from ?? filterDateFrom) || undefined,
      date_to: (overrides.date_to ?? filterDateTo) || undefined,
      offset: 0,
      limit: LIMIT,
    };
    api.listOperatorReception(token, params)
      .then((data) => {
        setLogs(data);
        setHasMore(data.length === LIMIT);
        setOffset(data.length);
        setLastRefreshed(new Date());
      })
      .finally(() => setLoading(false));
  };

  const handleResellerChange = (v: string) => {
    setFilterReseller(v);
    resetAndFetch({ reseller_id: v });
  };

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
      reseller_id: filterReseller || undefined,
      tenant_id: filterTenant || undefined,
      q: filterQ || undefined,
      status: filterStatus || undefined,
      method: methodFilter || undefined,
      date_from: filterDateFrom || undefined,
      date_to: filterDateTo || undefined,
      offset,
      limit: LIMIT,
    };
    api.listOperatorReception(token, params)
      .then((data) => {
        setLogs((prev) => [...prev, ...data]);
        setHasMore(data.length === LIMIT);
        setOffset((prev) => prev + data.length);
      })
      .finally(() => setLoading(false));
  };

  const filteredLogs = useMemo(() => {
    let list = logs;
    if (stateFilter) list = list.filter((r) => r.state === stateFilter);
    return list;
  }, [logs, stateFilter]);

  const allSelected = filteredLogs.length > 0 && filteredLogs.every((l) => selectedIds.has(l.id));
  const someSelected = filteredLogs.some((l) => selectedIds.has(l.id));

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredLogs.map((l) => l.id)));
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

  const handleBulkDelete = () => {
    if (!window.confirm(`${selectedIds.size}件の受付ログを削除しますか？`)) return;
    setBulkDeleting(true);
    api.bulkDeleteOperatorReception(token, [...selectedIds])
      .then(({ deleted }) => {
        if (deleted > 0) {
          setLogs((prev) => prev.filter((l) => !selectedIds.has(l.id)));
        }
        setSelectedIds(new Set());
      })
      .catch(() => {})
      .finally(() => setBulkDeleting(false));
  };

  const handleBulkStateUpdate = async (newState: string) => {
    const label = newState === "notified" ? "通知済み" : "完了";
    if (!window.confirm(`${selectedIds.size}件を${label}に変更しますか？`)) return;
    setBulkUpdating(true);
    const ids = [...selectedIds];
    await Promise.all(ids.map((id) =>
      api.updateOperatorReceptionLog(token, id, { state: newState }).catch(() => {})
    ));
    setLogs((prev) => prev.map((l) => selectedIds.has(l.id) ? { ...l, state: newState } : l));
    setSelectedIds(new Set());
    setBulkUpdating(false);
  };

  const handleNotesUpdate = (id: string, staff_notes: string | null) => {
    setLogs((prev) => prev.map((l) => l.id === id ? { ...l, staff_notes } : l));
    setSelectedLog((prev) => prev && prev.id === id ? { ...prev, staff_notes } : prev);
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <style>{`@keyframes mk-pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
      {selectedLog && (
        <OperatorReceptionDetailModal log={selectedLog} token={token} onClose={() => setSelectedLog(null)} onNotesUpdate={handleNotesUpdate} />
      )}

      <div style={{ display: "flex", alignItems: "center", marginBottom: 24, gap: 12 }}>
        <MkSectionTitle title="受付ログ" subtitle={`${filteredLogs.length} 件${hasMore ? "+" : ""}（全テナント）`} />
        <button
          onClick={async () => {
            try {
              const blob = await api.exportOperatorReceptionCsv(token, {
                tenant_id: filterTenant || undefined,
                reseller_id: filterReseller || undefined,
                q: filterQ || undefined,
                status: filterStatus || undefined,
                date_from: filterDateFrom || undefined,
                date_to: filterDateTo || undefined,
              });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `reception_${new Date().toISOString().slice(0, 10)}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            } catch {
              alert("エクスポートに失敗しました");
            }
          }}
          style={{ marginLeft: "auto", height: 34, padding: "0 16px", border: "1px solid #efece5", borderRadius: 6, fontSize: 12, cursor: "pointer", background: "#faf8f4", color: "#6b6559" }}
        >
          エクスポート
        </button>
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

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <select style={selectStyle} value={filterReseller} onChange={(e) => handleResellerChange(e.target.value)}>
          <option value="">全代理店</option>
          {resellers.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        <select style={selectStyle} value={filterTenant} onChange={(e) => handleTenantChange(e.target.value)}>
          <option value="">全テナント</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <input
          style={{ ...inputStyle, width: 200 }}
          placeholder="訪問者名・会社名で検索"
          value={filterQ}
          onChange={(e) => handleQChange(e.target.value)}
        />
        <select style={selectStyle} value={filterStatus} onChange={(e) => handleStatusChange(e.target.value)}>
          <option value="">全ステータス</option>
          <option value="received">受付済</option>
          <option value="notified">通知済</option>
          <option value="completed">完了</option>
          <option value="cancelled">キャンセル</option>
        </select>
        <select
          style={SELECT_STYLE}
          value={methodFilter}
          onChange={(e) => { setMethodFilter(e.target.value); resetAndFetch({ method: e.target.value }); }}
        >
          <option value="">受付経路: 全て</option>
          <option value="form">フォーム</option>
          <option value="qr">QR</option>
          <option value="phone">電話</option>
          <option value="other">その他</option>
        </select>
        <select
          style={SELECT_STYLE}
          value={stateFilter}
          onChange={(e) => { setStateFilter(e.target.value); }}
        >
          <option value="">ステータス: 全て</option>
          <option value="received">受付済み</option>
          <option value="notified">通知済み</option>
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
      </div>

      {loading && logs.length === 0 ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <>
          {selectedIds.size > 0 && (
            <div style={{ background: "#221f16", border: "1px solid #3a3528", borderRadius: 8, padding: "10px 14px", display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
              <span style={{ fontSize: 12, color: "#c8bfa8" }}>{selectedIds.size}件選択中</span>
              <button
                onClick={() => handleBulkStateUpdate("notified")}
                disabled={bulkUpdating || bulkDeleting}
                style={{ background: "#c8a96e", color: "#1d1a15", border: "none", borderRadius: 6, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
              >
                ✓ 通知済みに変更
              </button>
              <button
                onClick={() => handleBulkStateUpdate("completed")}
                disabled={bulkUpdating || bulkDeleting}
                style={{ background: "#c8a96e", color: "#1d1a15", border: "none", borderRadius: 6, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
              >
                ✓ 完了に変更
              </button>
              <button
                onClick={handleBulkDelete}
                disabled={bulkUpdating || bulkDeleting}
                style={{ background: "none", color: "#e57373", border: "1px solid #5a2a2a", borderRadius: 6, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
              >
                🗑 削除
              </button>
            </div>
          )}

          <MkCard padding="0">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #efece5", background: "#f4f1ea" }}>
                  <th style={{ padding: "10px 14px", textAlign: "left" as const }}>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(el) => { if (el) el.indeterminate = !allSelected && someSelected; }}
                      onChange={toggleSelectAll}
                      style={{ width: 16, height: 16, cursor: "pointer", accentColor: "#2d6a4f" }}
                    />
                  </th>
                  {["テナント名", "訪問者", "会社名", "担当者", "目的", "受付方法", "ステータス", "日時"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px", whiteSpace: "nowrap" as const }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((log) => {
                  const isSelected = selectedIds.has(log.id);
                  return (
                    <RowWithHover
                      key={log.id}
                      selected={isSelected}
                      onClick={() => setSelectedLog(log)}
                      onCheckClick={(e) => { e.stopPropagation(); toggleSelectRow(log.id); }}
                    >
                      <td style={{ padding: "10px 14px" }} onClick={(e) => { e.stopPropagation(); toggleSelectRow(log.id); }}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectRow(log.id)}
                          onClick={(e) => e.stopPropagation()}
                          style={{ width: 16, height: 16, cursor: "pointer", accentColor: "#2d6a4f" }}
                        />
                      </td>
                      <td
                        style={{ padding: "10px 14px", fontWeight: 600, color: "#1d1a15", whiteSpace: "nowrap" as const, cursor: "pointer" }}
                        onClick={() => setSelectedLog(log)}
                      >{log.tenant_name}</td>
                      <td style={{ padding: "10px 14px", color: "#1d1a15", cursor: "pointer" }} onClick={() => setSelectedLog(log)}>
                        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          {log.visitor_name}
                          {log.staff_notes && <span style={{ fontSize: 10, fontWeight: 600, background: "#fef9c3", color: "#854d0e", border: "1px solid #fef08a", borderRadius: 4, padding: "1px 6px" }}>メモあり</span>}
                        </span>
                      </td>
                      <td style={{ padding: "10px 14px", color: "#6b6559", cursor: "pointer" }} onClick={() => setSelectedLog(log)}>{log.company ?? "—"}</td>
                      <td style={{ padding: "10px 14px", color: "#6b6559", cursor: "pointer" }} onClick={() => setSelectedLog(log)}>{log.staff ?? "—"}</td>
                      <td style={{ padding: "10px 14px", color: "#6b6559", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const, cursor: "pointer" }} onClick={() => setSelectedLog(log)}>{log.purpose ?? "—"}</td>
                      <td style={{ padding: "10px 14px", color: "#a8a198", cursor: "pointer" }} onClick={() => setSelectedLog(log)}>{log.method ?? "—"}</td>
                      <td style={{ padding: "10px 14px", cursor: "pointer" }} onClick={() => setSelectedLog(log)}><StatusPill state={log.state} /></td>
                      <td style={{ padding: "10px 14px", color: "#a8a198", whiteSpace: "nowrap" as const, cursor: "pointer" }} onClick={() => setSelectedLog(log)}>{new Date(log.created_at).toLocaleString("ja-JP")}</td>
                    </RowWithHover>
                  );
                })}
                {filteredLogs.length === 0 && !loading && (
                  <tr>
                    <td colSpan={9} style={{ padding: "32px", textAlign: "center" as const, color: "#a8a198" }}>受付ログがありません</td>
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
                style={{ height: 36, padding: "0 24px", border: "1px solid #efece5", borderRadius: 6, fontSize: 13, cursor: "pointer", background: "#faf8f4", color: "#6b6559" }}
              >
                {loading ? "読み込み中…" : "もっと読み込む"}
              </button>
            </div>
          )}
        </>
      )}

      {selectedIds.size > 0 && (
        <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#1d1a15", color: "#f4f0e8", padding: "12px 24px", display: "flex", alignItems: "center", gap: 12, zIndex: 100 }}>
          <span style={{ fontSize: 13 }}>{selectedIds.size}件を選択中</span>
          <button
            onClick={() => handleBulkStateUpdate("notified")}
            disabled={bulkUpdating || bulkDeleting}
            style={{ background: "#c8a96e", color: "#1d1a15", border: "none", borderRadius: 6, padding: "7px 16px", fontSize: 13, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
          >
            ✓ 通知済みに変更
          </button>
          <button
            onClick={() => handleBulkStateUpdate("completed")}
            disabled={bulkUpdating || bulkDeleting}
            style={{ background: "#c8a96e", color: "#1d1a15", border: "none", borderRadius: 6, padding: "7px 16px", fontSize: 13, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
          >
            ✓ 完了に変更
          </button>
          <button
            onClick={handleBulkDelete}
            disabled={bulkUpdating || bulkDeleting}
            style={{ background: "#dc2626", color: "#ffffff", border: "none", borderRadius: 6, padding: "7px 16px", fontSize: 13, fontWeight: 600, cursor: (bulkUpdating || bulkDeleting) ? "not-allowed" : "pointer", opacity: (bulkUpdating || bulkDeleting) ? 0.7 : 1 }}
          >
            🗑 削除
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            style={{ background: "transparent", color: "#a8a198", border: "1px solid #3d3a34", borderRadius: 6, padding: "7px 16px", fontSize: 13, cursor: "pointer" }}
          >
            選択解除
          </button>
        </div>
      )}
    </div>
  );
}
