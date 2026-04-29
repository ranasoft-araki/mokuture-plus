"use client";

import { useEffect, useState } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

export default function OperatorTenantsPage() {
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", reseller_id: "", admin_email: "", admin_password: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const token = getAccessToken() ?? "";

  const load = async () => {
    setLoading(true);
    const [t, r] = await Promise.all([api.listOperatorTenants(token), api.listResellers(token)]);
    setTenants(t);
    setResellers(r);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.admin_password.length < 8) { setError("パスワードは8文字以上で入力してください"); return; }
    setSubmitting(true); setError("");
    try {
      await api.createOperatorTenant(token, { ...form, reseller_id: form.reseller_id || undefined });
      setShowForm(false);
      setForm({ name: "", slug: "", reseller_id: "", admin_email: "", admin_password: "" });
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`テナント「${name}」を削除しますか？この操作は取り消せません。`)) return;
    await api.deleteOperatorTenant(token, id);
    await load();
  };

  const handleProxyLogin = async (tenant: OperatorTenant) => {
    if (!confirm(`「${tenant.name}」の管理画面に代理ログインします。新しいタブで開きます。続行しますか？`)) return;
    try {
      const { access_token, refresh_token, tenant_slug } = await api.proxyLoginAsTenant(token, tenant.id);
      localStorage.setItem("mk_proxy_access", access_token);
      localStorage.setItem("mk_proxy_refresh", refresh_token);
      localStorage.setItem("mk_proxy_tenant", tenant_slug);
      window.open(`/${tenant_slug}/admin`, "_blank");
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "代理ログインに失敗しました");
    }
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <MkSectionTitle title="テナント管理" subtitle={`${tenants.length} テナント`} />
        <MkBtn variant="primary" size="sm" onClick={() => setShowForm(!showForm)}>+ テナント追加</MkBtn>
      </div>

      {showForm && (
        <MkCard style={{ marginBottom: 20 }}>
          <MkSectionTitle title="新規テナント作成" />
          {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 12px", marginBottom: 12, fontSize: 13, color: "#dc2626" }}>{error}</div>}
          <form onSubmit={handleCreate} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <FormField label="テナント名" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} required />
            <FormField label="スラッグ（URL）" value={form.slug} onChange={(v) => setForm((f) => ({ ...f, slug: v.toLowerCase() }))} hint="例：isonoki" required />
            <div style={{ gridColumn: "1 / -1" }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", display: "block", marginBottom: 6 }}>代理店（任意）</label>
              <select value={form.reseller_id} onChange={(e) => setForm((f) => ({ ...f, reseller_id: e.target.value }))} style={{ width: "100%", border: "1px solid #e2ddd6", borderRadius: 8, padding: "9px 12px", fontSize: 13, background: "#faf8f4", color: "#1d1a15" }}>
                <option value="">（なし — 直接管理）</option>
                {resellers.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.slug})</option>)}
              </select>
            </div>
            <FormField label="管理者メール" type="email" value={form.admin_email} onChange={(v) => setForm((f) => ({ ...f, admin_email: v }))} required />
            <FormField label="管理者パスワード" type="password" value={form.admin_password} onChange={(v) => setForm((f) => ({ ...f, admin_password: v }))} required />
            <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <MkBtn variant="default" size="sm" onClick={() => setShowForm(false)}>キャンセル</MkBtn>
              <MkBtn variant="primary" size="sm" type="submit" disabled={submitting}>{submitting ? "作成中…" : "作成"}</MkBtn>
            </div>
          </form>
        </MkCard>
      )}

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <MkCard padding="0">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #efece5" }}>
                {["テナント名", "スラッグ", "代理店", "作成日", ""].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1d1a15" }}>{t.name}</td>
                  <td style={{ padding: "12px 16px", color: "#6b6559", fontFamily: '"JetBrains Mono", monospace', fontSize: 12 }}>{t.slug}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198" }}>{resellers.find((r) => r.id === t.reseller_id)?.name ?? "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{t.created_at ? new Date(t.created_at).toLocaleDateString("ja-JP") : "—"}</td>
                  <td style={{ padding: "12px 16px", textAlign: "right" as const, display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
                    <button onClick={() => handleProxyLogin(t)} style={{ border: "1px solid #c8a96e", color: "#c8a96e", background: "transparent", padding: "4px 10px", borderRadius: 6, fontSize: 12, cursor: "pointer" }}>代理ログイン</button>
                    <MkBtn variant="danger" size="sm" onClick={() => handleDelete(t.id, t.name)}>削除</MkBtn>
                  </td>
                </tr>
              ))}
              {tenants.length === 0 && (
                <tr><td colSpan={5} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>テナントがありません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}
    </div>
  );
}

function FormField({ label, value, onChange, hint, type = "text", required }: { label: string; value: string; onChange: (v: string) => void; hint?: string; type?: string; required?: boolean }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15" }}>{label}</label>
        {hint && <span style={{ fontSize: 11, color: "#a8a198" }}>{hint}</span>}
      </div>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} required={required}
        style={{ width: "100%", border: "1px solid #e2ddd6", borderRadius: 8, padding: "9px 12px", fontSize: 13, background: "#faf8f4", color: "#1d1a15", outline: "none", boxSizing: "border-box" as const }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "#4a7c4e"; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "#e2ddd6"; }}
      />
    </div>
  );
}
