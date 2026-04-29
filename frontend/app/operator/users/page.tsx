"use client";

import { useEffect, useState, useRef } from "react";
import { api, OperatorUser, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle, MkPill } from "@/components/AdminShell";

const ROLE_LABELS: Record<string, string> = {
  operator: "運営", reseller: "代理店", admin: "管理者", staff: "スタッフ", kiosk: "キオスク",
};
const ROLE_TONES: Record<string, "live" | "warn" | "info" | "neutral" | "error"> = {
  operator: "error", reseller: "warn", admin: "live", staff: "info", kiosk: "neutral",
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

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};

export default function OperatorUsersPage() {
  const [users, setUsers] = useState<OperatorUser[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);

  const [filterRole, setFilterRole] = useState("");
  const [filterReseller, setFilterReseller] = useState("");
  const [filterQ, setFilterQ] = useState("");

  const token = getAccessToken() ?? "";
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchUsers = (params: { role?: string; reseller_id?: string; q?: string }) => {
    setLoading(true);
    api.listOperatorUsers(token, params).then(setUsers).finally(() => setLoading(false));
  };

  useEffect(() => {
    api.listResellers(token).then(setResellers);
    fetchUsers({});
  }, []);

  const triggerFetch = (overrides: { role?: string; reseller_id?: string; q?: string }) => {
    fetchUsers({
      role: (overrides.role ?? filterRole) || undefined,
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
    });
  };

  const handleRoleChange = (v: string) => {
    setFilterRole(v);
    triggerFetch({ role: v || undefined });
  };

  const handleResellerChange = (v: string) => {
    setFilterReseller(v);
    triggerFetch({ reseller_id: v || undefined });
  };

  const handleQChange = (v: string) => {
    setFilterQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => triggerFetch({ q: v || undefined }), 300);
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="ユーザー管理" subtitle={`${users.length} ユーザー（全テナント）`} style={{ marginBottom: 24 }} />

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <select
          style={selectStyle}
          value={filterRole}
          onChange={(e) => handleRoleChange(e.target.value)}
        >
          <option value="">全ロール</option>
          <option value="operator">運営</option>
          <option value="reseller">代理店</option>
          <option value="admin">管理者</option>
          <option value="staff">スタッフ</option>
          <option value="kiosk">キオスク</option>
        </select>
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
          placeholder="メールアドレスで検索"
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
                {["メールアドレス", "ロール", "テナントID", "作成日"].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", color: "#1d1a15" }}>{u.email}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <MkPill tone={ROLE_TONES[u.role] ?? "neutral"}>{ROLE_LABELS[u.role] ?? u.role}</MkPill>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontFamily: '"JetBrains Mono", monospace', fontSize: 11 }}>{u.tenant_id ?? "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{u.created_at ? new Date(u.created_at).toLocaleDateString("ja-JP") : "—"}</td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={4} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>ユーザーがいません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}
    </div>
  );
}
