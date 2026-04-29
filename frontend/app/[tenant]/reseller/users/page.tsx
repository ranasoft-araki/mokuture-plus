"use client";

import { useEffect, useState } from "react";
import { api, OperatorUser } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle, MkPill } from "@/components/AdminShell";

const ROLE_LABELS: Record<string, string> = { admin: "管理者", staff: "スタッフ", kiosk: "キオスク" };
const ROLE_TONES: Record<string, "live" | "info" | "neutral"> = { admin: "live", staff: "info", kiosk: "neutral" };

export default function ResellerUsersPage() {
  const [users, setUsers] = useState<OperatorUser[]>([]);
  const [loading, setLoading] = useState(true);
  const token = getAccessToken() ?? "";

  useEffect(() => {
    api.listResellerUsers(token).then(setUsers).finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="ユーザー管理" subtitle={`${users.length} ユーザー（管理顧客テナント全体）`} style={{ marginBottom: 24 }} />
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
