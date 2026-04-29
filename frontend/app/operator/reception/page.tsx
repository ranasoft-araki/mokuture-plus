"use client";

import { useEffect, useState, useRef, useCallback } from "react";
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

export default function OperatorReceptionPage() {
  const token = getAccessToken() ?? "";
  const [logs, setLogs] = useState<OperatorReceptionItem[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const [filterReseller, setFilterReseller] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterQ, setFilterQ] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const buildParams = useCallback(
    (overrides: Record<string, string | undefined> = {}, currentOffset = 0) => ({
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
      date_from: (overrides.date_from ?? filterDateFrom) || undefined,
      date_to: (overrides.date_to ?? filterDateTo) || undefined,
      offset: currentOffset,
      limit: LIMIT,
    }),
    [filterReseller, filterTenant, filterQ, filterStatus, filterDateFrom, filterDateTo]
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
    api.listOperatorTenants(token, { limit: 200 }).then(setTenants);
    fetchLogs();
  }, []);

  const resetAndFetch = (overrides: Record<string, string | undefined> = {}) => {
    setOffset(0);
    setLoading(true);
    const params = {
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
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

  return (
    <div style={{ padding: "28px 32px" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 24, gap: 12 }}>
        <MkSectionTitle title="受付ログ" subtitle={`${logs.length} 件${hasMore ? "+" : ""}（全テナント）`} />
        <button
          onClick={() => alert("準備中")}
          style={{ marginLeft: "auto", height: 34, padding: "0 16px", border: "1px solid #efece5", borderRadius: 6, fontSize: 12, cursor: "pointer", background: "#faf8f4", color: "#6b6559" }}
        >
          エクスポート
        </button>
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
          <MkCard padding="0">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #efece5" }}>
                  {["テナント名", "訪問者", "会社名", "担当者", "目的", "受付方法", "ステータス", "日時"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px", whiteSpace: "nowrap" as const }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                    <td style={{ padding: "10px 14px", fontWeight: 600, color: "#1d1a15", whiteSpace: "nowrap" as const }}>{log.tenant_name}</td>
                    <td style={{ padding: "10px 14px", color: "#1d1a15" }}>{log.visitor_name}</td>
                    <td style={{ padding: "10px 14px", color: "#6b6559" }}>{log.company ?? "—"}</td>
                    <td style={{ padding: "10px 14px", color: "#6b6559" }}>{log.staff ?? "—"}</td>
                    <td style={{ padding: "10px 14px", color: "#6b6559", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>{log.purpose ?? "—"}</td>
                    <td style={{ padding: "10px 14px", color: "#a8a198" }}>{log.method ?? "—"}</td>
                    <td style={{ padding: "10px 14px" }}><StatusPill state={log.state} /></td>
                    <td style={{ padding: "10px 14px", color: "#a8a198", whiteSpace: "nowrap" as const }}>{new Date(log.created_at).toLocaleString("ja-JP")}</td>
                  </tr>
                ))}
                {logs.length === 0 && !loading && (
                  <tr>
                    <td colSpan={8} style={{ padding: "32px", textAlign: "center" as const, color: "#a8a198" }}>受付ログがありません</td>
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
    </div>
  );
}
