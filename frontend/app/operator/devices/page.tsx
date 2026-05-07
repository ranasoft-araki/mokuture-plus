"use client";

import { useEffect, useState, useRef } from "react";
import { api, OperatorDevice, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle, MkPill } from "@/components/AdminShell";

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

export default function OperatorDevicesPage() {
  const [devices, setDevices] = useState<OperatorDevice[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);

  const [filterReseller, setFilterReseller] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterQ, setFilterQ] = useState("");

  const token = getAccessToken() ?? "";
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchDevices = (params: { reseller_id?: string; tenant_id?: string; status?: string; q?: string }) => {
    setLoading(true);
    api.listOperatorDevices(token, params).then(r => setDevices(r.items)).finally(() => setLoading(false));
  };

  useEffect(() => {
    api.listResellers(token).then(setResellers);
    fetchDevices({});
  }, []);

  const triggerFetch = (overrides: { reseller_id?: string; tenant_id?: string; status?: string; q?: string }) => {
    fetchDevices({
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      tenant_id: (overrides.tenant_id ?? filterTenant) || undefined,
      status: (overrides.status ?? filterStatus) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
    });
  };

  const handleResellerChange = (v: string) => {
    setFilterReseller(v);
    triggerFetch({ reseller_id: v || undefined });
  };

  const handleStatusChange = (v: string) => {
    setFilterStatus(v);
    triggerFetch({ status: v || undefined });
  };

  const handleTenantChange = (v: string) => {
    setFilterTenant(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => triggerFetch({ tenant_id: v || undefined }), 300);
  };

  const handleQChange = (v: string) => {
    setFilterQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => triggerFetch({ q: v || undefined }), 300);
  };

  const isOnline = (lastSeen: string | null) => {
    if (!lastSeen) return false;
    return Date.now() - new Date(lastSeen).getTime() < 3 * 60 * 1000;
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="デバイス管理" subtitle={`${devices.length} デバイス（全テナント）`} style={{ marginBottom: 24 }} />

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <select
          style={selectStyle}
          value={filterReseller}
          onChange={(e) => handleResellerChange(e.target.value)}
        >
          <option value="">全代理店</option>
          {resellers.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        <input
          style={inputStyle}
          placeholder="テナントID で絞り込み"
          value={filterTenant}
          onChange={(e) => handleTenantChange(e.target.value)}
        />
        <select
          style={selectStyle}
          value={filterStatus}
          onChange={(e) => handleStatusChange(e.target.value)}
        >
          <option value="">全て</option>
          <option value="online">オンライン</option>
          <option value="offline">オフライン</option>
        </select>
        <input
          style={inputStyle}
          placeholder="デバイス名で検索"
          value={filterQ}
          onChange={(e) => handleQChange(e.target.value)}
        />
      </div>

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <MkCard padding="0">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #efece5" }}>
                {["デバイス名", "場所", "ステータス", "テナントID", "最終接続"].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1d1a15" }}>{d.name}</td>
                  <td style={{ padding: "12px 16px", color: d.location ? "#2d2a24" : "#a8a198", fontSize: 12 }}>{d.location ?? "—"}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <MkPill tone={isOnline(d.last_seen_at) ? "live" : "off"}>{isOnline(d.last_seen_at) ? "オンライン" : "オフライン"}</MkPill>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontFamily: '"JetBrains Mono", monospace', fontSize: 11 }}>{d.tenant_id}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString("ja-JP") : "未接続"}</td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr><td colSpan={5} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>デバイスがありません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}
    </div>
  );
}
