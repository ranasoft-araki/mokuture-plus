"use client";

import { useEffect, useRef, useState } from "react";
import { api, OperatorUser, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle, MkPill } from "@/components/AdminShell";

const INPUT_STYLE: React.CSSProperties = { height: 34, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#1d1a15" };
const SELECT_STYLE: React.CSSProperties = { height: 34, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#1d1a15" };

const ROLE_LABELS: Record<string, string> = { admin: "管理者", staff: "スタッフ", kiosk: "キオスク" };
const ROLE_TONES: Record<string, "live" | "info" | "neutral"> = { admin: "live", staff: "info", kiosk: "neutral" };

export default function ResellerUsersPage() {
  const [users, setUsers] = useState<OperatorUser[]>([]);
  const [customers, setCustomers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [tenantId, setTenantId] = useState("");
  const [role, setRole] = useState("");
  const [q, setQ] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const token = getAccessToken() ?? "";

  const load = (tid: string, r: string, search: string) => {
    setLoading(true);
    api.listResellerUsers(token, {
      tenant_id: tid || undefined,
      role: r || undefined,
      q: search || undefined,
    }).then(setUsers).finally(() => setLoading(false));
  };

  useEffect(() => {
    api.listResellerCustomers(token).then(setCustomers);
    load("", "", "");
  }, []);

  const handleTenantChange = (v: string) => {
    setTenantId(v);
    load(v, role, q);
  };

  const handleRoleChange = (v: string) => {
    setRole(v);
    load(tenantId, v, q);
  };

  const handleQChange = (v: string) => {
    setQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { load(tenantId, role, v); }, 300);
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="ユーザー管理" subtitle={`${users.length} ユーザー（管理顧客テナント全体）`} style={{ marginBottom: 16 }} />
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <select style={SELECT_STYLE} value={tenantId} onChange={(e) => handleTenantChange(e.target.value)}>
          <option value="">全テナント</option>
          {customers.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select style={SELECT_STYLE} value={role} onChange={(e) => handleRoleChange(e.target.value)}>
          <option value="">全て</option>
          <option value="admin">admin</option>
          <option value="staff">staff</option>
          <option value="kiosk">kiosk</option>
        </select>
        <input
          style={INPUT_STYLE}
          placeholder="メールアドレスで検索"
          value={q}
          onChange={(e) => handleQChange(e.target.value)}
        />
        <span style={{ fontSize: 12, color: "#a8a198" }}>{users.length} 件</span>
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
