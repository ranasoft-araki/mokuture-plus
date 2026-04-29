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

// Dark operator-theme styles for the create-user form
const darkInput: React.CSSProperties = {
  height: 36,
  border: "1px solid #3a3528",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  outline: "none",
  background: "#1a1810",
  color: "#e8e0d0",
  width: "100%",
  boxSizing: "border-box",
};

const darkSelect: React.CSSProperties = {
  ...darkInput,
  cursor: "pointer",
};

export default function OperatorUsersPage() {
  const [users, setUsers] = useState<OperatorUser[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);

  const [filterRole, setFilterRole] = useState("");
  const [filterReseller, setFilterReseller] = useState("");
  const [filterQ, setFilterQ] = useState("");

  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const PAGE_SIZE = 50;

  // Create-user panel state
  const [panelOpen, setPanelOpen] = useState(false);
  const [formTenantId, setFormTenantId] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState("staff");
  const [formError, setFormError] = useState<string | null>(null);
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const token = getAccessToken() ?? "";
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchUsers = (params: { role?: string; reseller_id?: string; q?: string; page?: number }) => {
    setLoading(true);
    api.listOperatorUsers(token, { ...params, page: params.page ?? 1, page_size: PAGE_SIZE })
      .then((res) => {
        setUsers(res.items);
        setTotal(res.total);
        setTotalPages(res.total_pages);
      })
      .finally(() => setLoading(false));
  };

  const handleDeleteUser = async (userId: string) => {
    if (!window.confirm("このユーザーを削除しますか？")) return;
    setDeletingId(userId);
    try {
      await api.deleteOperatorUser(token, userId);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "削除に失敗しました");
    } finally {
      setDeletingId(null);
    }
  };

  const handleRoleEdit = async (userId: string, newRole: string) => {
    try {
      const updated = await api.updateOperatorUserRole(token, userId, newRole);
      setUsers((prev) => prev.map((u) => u.id === userId ? updated : u));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "ロール変更に失敗しました");
    }
  };

  useEffect(() => {
    api.listResellers(token).then(setResellers);
    api.listOperatorTenants(token, { page_size: 200, page: 1 }).then((res) => setTenants(res.items));
    fetchUsers({ page: 1 });
  }, []);

  const triggerFetch = (overrides: { role?: string; reseller_id?: string; q?: string }) => {
    setPage(1);
    fetchUsers({
      role: (overrides.role ?? filterRole) || undefined,
      reseller_id: (overrides.reseller_id ?? filterReseller) || undefined,
      q: (overrides.q ?? filterQ) || undefined,
      page: 1,
    });
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    fetchUsers({
      role: filterRole || undefined,
      reseller_id: filterReseller || undefined,
      q: filterQ || undefined,
      page: newPage,
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

  const handleOpenPanel = () => {
    setPanelOpen(true);
    setFormTenantId(tenants[0]?.id ?? "");
    setFormEmail("");
    setFormPassword("");
    setFormRole("staff");
    setFormError(null);
  };

  const handleClosePanel = () => {
    setPanelOpen(false);
    setFormError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTenantId) { setFormError("テナントを選択してください"); return; }
    if (!formEmail) { setFormError("メールアドレスを入力してください"); return; }
    if (formPassword.length < 8) { setFormError("パスワードは8文字以上で入力してください"); return; }

    setFormSubmitting(true);
    setFormError(null);
    try {
      const newUser = await api.createOperatorUser(token, {
        tenant_id: formTenantId,
        email: formEmail,
        password: formPassword,
        role: formRole,
      });
      setUsers((prev) => [newUser, ...prev]);
      handleClosePanel();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "エラーが発生しました";
      if (msg.includes("409") || msg.toLowerCase().includes("already")) {
        setFormError("このテナントにはそのメールアドレスが既に登録されています");
      } else {
        setFormError(msg);
      }
    } finally {
      setFormSubmitting(false);
    }
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="ユーザー管理" subtitle={`${total} ユーザー（全テナント）`} style={{ marginBottom: 24 }} />

      {/* Filter bar + Add button */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
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

        <div style={{ marginLeft: "auto" }}>
          <button
            onClick={panelOpen ? handleClosePanel : handleOpenPanel}
            style={{
              height: 34,
              padding: "0 16px",
              background: panelOpen ? "#3a3528" : "#c8a96e",
              color: panelOpen ? "#c8a96e" : "#1a1810",
              border: "none",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {panelOpen ? "✕ 閉じる" : "＋ ユーザー追加"}
          </button>
        </div>
      </div>

      {/* Collapsible create-user panel */}
      {panelOpen && (
        <div
          style={{
            background: "#221f16",
            border: "1px solid #3a3528",
            borderRadius: 10,
            padding: "24px 28px",
            marginBottom: 20,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 700, color: "#c8a96e", marginBottom: 20, letterSpacing: "0.3px" }}>
            ユーザー追加
          </div>

          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
              {/* Tenant */}
              <div>
                <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#a89878", marginBottom: 6, letterSpacing: "0.4px" }}>
                  テナント
                </label>
                <select
                  style={darkSelect}
                  value={formTenantId}
                  onChange={(e) => setFormTenantId(e.target.value)}
                  required
                >
                  <option value="">テナントを選択</option>
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>

              {/* Role */}
              <div>
                <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#a89878", marginBottom: 6, letterSpacing: "0.4px" }}>
                  ロール
                </label>
                <select
                  style={darkSelect}
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value)}
                >
                  <option value="staff">スタッフ</option>
                  <option value="admin">管理者</option>
                </select>
              </div>

              {/* Email */}
              <div>
                <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#a89878", marginBottom: 6, letterSpacing: "0.4px" }}>
                  メールアドレス
                </label>
                <input
                  type="email"
                  style={darkInput}
                  placeholder="user@example.com"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  required
                />
              </div>

              {/* Password */}
              <div>
                <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#a89878", marginBottom: 6, letterSpacing: "0.4px" }}>
                  パスワード <span style={{ color: "#7a7060", fontWeight: 400 }}>(8文字以上)</span>
                </label>
                <input
                  type="password"
                  style={darkInput}
                  placeholder="••••••••"
                  value={formPassword}
                  onChange={(e) => setFormPassword(e.target.value)}
                  minLength={8}
                  required
                />
              </div>
            </div>

            {/* Inline error */}
            {formError && (
              <div style={{
                background: "#3a1a1a",
                border: "1px solid #7a2020",
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 12,
                color: "#e88080",
                marginBottom: 16,
              }}>
                {formError}
              </div>
            )}

            {/* Submit */}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={handleClosePanel}
                style={{
                  height: 34,
                  padding: "0 16px",
                  background: "transparent",
                  color: "#a89878",
                  border: "1px solid #3a3528",
                  borderRadius: 6,
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                キャンセル
              </button>
              <button
                type="submit"
                disabled={formSubmitting}
                style={{
                  height: 34,
                  padding: "0 24px",
                  background: formSubmitting ? "#5a4a2a" : "#c8a96e",
                  color: "#1a1810",
                  border: "none",
                  borderRadius: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: formSubmitting ? "not-allowed" : "pointer",
                }}
              >
                {formSubmitting ? "追加中…" : "追加"}
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <MkCard padding="0">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #efece5" }}>
                {["メールアドレス", "ロール", "テナントID", "作成日", "操作"].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", color: "#1d1a15" }}>{u.email}</td>
                  <td style={{ padding: "12px 16px" }}>
                    {u.role === "operator" ? (
                      <MkPill tone={ROLE_TONES[u.role] ?? "neutral"}>{ROLE_LABELS[u.role] ?? u.role}</MkPill>
                    ) : (
                      <select
                        value={u.role}
                        onChange={(e) => handleRoleEdit(u.id, e.target.value)}
                        style={selectStyle}
                      >
                        <option value="reseller">代理店</option>
                        <option value="admin">管理者</option>
                        <option value="staff">スタッフ</option>
                        <option value="kiosk">キオスク</option>
                      </select>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontFamily: '"JetBrains Mono", monospace', fontSize: 11 }}>{u.tenant_id ?? "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{u.created_at ? new Date(u.created_at).toLocaleDateString("ja-JP") : "—"}</td>
                  <td style={{ padding: "12px 16px" }}>
                    {u.role !== "operator" && (
                      <button
                        onClick={() => handleDeleteUser(u.id)}
                        disabled={deletingId === u.id}
                        title="ユーザーを削除"
                        style={{
                          background: "none",
                          border: "1px solid #e8c4c4",
                          borderRadius: 6,
                          color: "#c05050",
                          cursor: deletingId === u.id ? "not-allowed" : "pointer",
                          fontSize: 15,
                          lineHeight: 1,
                          padding: "4px 8px",
                          opacity: deletingId === u.id ? 0.5 : 1,
                        }}
                      >
                        🗑
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={5} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>ユーザーがいません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}

      {/* ── Pagination controls ───────────────────────────────────────────── */}
      {!loading && totalPages > 1 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            marginTop: 16,
          }}
        >
          <button
            onClick={() => handlePageChange(page - 1)}
            disabled={page <= 1}
            style={{
              padding: "6px 14px",
              border: "1px solid #d8d3c7",
              borderRadius: 6,
              background: page <= 1 ? "#f4f1ea" : "#fff",
              color: page <= 1 ? "#a8a198" : "#1d1a15",
              fontSize: 13,
              cursor: page <= 1 ? "not-allowed" : "pointer",
            }}
          >
            ← 前へ
          </button>
          <span style={{ fontSize: 13, color: "#6b6559" }}>
            {page} / {totalPages} ページ（全 {total} 件）
          </span>
          <button
            onClick={() => handlePageChange(page + 1)}
            disabled={page >= totalPages}
            style={{
              padding: "6px 14px",
              border: "1px solid #d8d3c7",
              borderRadius: 6,
              background: page >= totalPages ? "#f4f1ea" : "#fff",
              color: page >= totalPages ? "#a8a198" : "#1d1a15",
              fontSize: 13,
              cursor: page >= totalPages ? "not-allowed" : "pointer",
            }}
          >
            次へ →
          </button>
        </div>
      )}
    </div>
  );
}
