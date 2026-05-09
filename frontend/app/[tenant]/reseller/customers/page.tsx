"use client";

import { useEffect, useRef, useState } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";
import { ConfirmModal } from "@/components/ConfirmModal";

const INPUT_STYLE: React.CSSProperties = { height: 34, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#1d1a15" };

export default function ResellerCustomersPage() {
  const [customers, setCustomers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", admin_email: "", admin_password: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [modal, setModal] = useState<{ msg: string; confirmLabel?: string; action: () => Promise<void> } | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const token = getAccessToken() ?? "";

  const load = async (search?: string) => {
    setLoading(true);
    const r = await api.listResellerCustomers(token, { q: search || undefined });
    setCustomers(r);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleQChange = (v: string) => {
    setQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { load(v); }, 300);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true); setError("");
    try {
      await api.createResellerCustomer(token, form);
      setShowForm(false);
      setForm({ name: "", slug: "", admin_email: "", admin_password: "" });
      await load(q);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "エラーが発生しました";
      const isSlugTaken = msg.toLowerCase().includes("slug") || msg.includes("already taken") || msg.includes("409");
      setError(isSlugTaken ? "このスラッグはすでに使用されています。別のスラッグを入力してください。" : msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = (id: string, name: string) => {
    setModal({
      msg: `顧客「${name}」を削除しますか？`,
      action: async () => {
        await api.deleteResellerCustomer(token, id);
        await load(q);
      },
    });
  };

  const handleProxyLogin = (customer: OperatorTenant) => {
    setModal({
      msg: `「${customer.name}」の管理画面に代理ログインします。新しいタブで開きます。続行しますか？`,
      confirmLabel: "代理ログイン",
      action: async () => {
        const result = await api.proxyLoginAsCustomer(token, customer.id);
        localStorage.setItem("mk_proxy_access", result.access_token);
        localStorage.setItem("mk_proxy_refresh", result.refresh_token);
        localStorage.setItem("mk_proxy_tenant", result.tenant_slug);
        window.open(`/${result.tenant_slug}/admin`, "_blank");
      },
    });
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      {modal && (
        <ConfirmModal
          message={modal.msg}
          confirmLabel={modal.confirmLabel}
          onConfirm={async () => { const action = modal.action; setModal(null); await action(); }}
          onCancel={() => setModal(null)}
        />
      )}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <MkSectionTitle title="顧客管理" subtitle={`${customers.length} 顧客テナント`} />
        <MkBtn variant="primary" size="sm" onClick={() => { setShowForm(!showForm); setError(""); }}>＋ 新規顧客テナント追加</MkBtn>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          style={INPUT_STYLE}
          placeholder="テナント名・スラッグで検索"
          value={q}
          onChange={(e) => handleQChange(e.target.value)}
        />
        <span style={{ fontSize: 12, color: "#a8a198" }}>{customers.length} 件</span>
      </div>

      {showForm && (
        <MkCard style={{ marginBottom: 20, border: "1px solid #e8d9b8", borderRadius: 8, background: "#fffefb" }}>
          <div style={{ borderBottom: "1px solid #efece5", paddingBottom: 12, marginBottom: 16 }}>
            <MkSectionTitle title="新規顧客テナント追加" />
          </div>
          {error && (
            <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 14px", marginBottom: 14, fontSize: 13, color: "#dc2626", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 16 }}>⚠</span>
              <span>{error}</span>
            </div>
          )}
          <form onSubmit={handleCreate} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <FormField label="テナント名" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} required />
            <FormField label="スラッグ" value={form.slug} onChange={(v) => setForm((f) => ({ ...f, slug: v.toLowerCase() }))} hint="英小文字・数字・ハイフン (3-64文字)" required />
            <FormField label="管理者メールアドレス" type="email" value={form.admin_email} onChange={(v) => setForm((f) => ({ ...f, admin_email: v }))} required />
            <FormField label="管理者パスワード" type="password" value={form.admin_password} onChange={(v) => setForm((f) => ({ ...f, admin_password: v }))} hint="8文字以上" required minLength={8} />
            <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8, justifyContent: "flex-end", paddingTop: 4 }}>
              <MkBtn variant="default" size="sm" onClick={() => { setShowForm(false); setError(""); }}>キャンセル</MkBtn>
              <MkBtn variant="primary" size="sm" type="submit" disabled={submitting}>{submitting ? "作成中…" : "作成する"}</MkBtn>
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
                {["テナント名", "スラッグ", "作成日", "デバイス", "本日の受付", "管理画面", "操作", ""].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.id} style={{ borderBottom: "1px solid #f4f1ea", background: c.is_suspended ? "#fff8f8" : undefined }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1d1a15" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      {c.name}
                      {c.is_suspended && (
                        <span style={{ background: "#fef2f2", color: "#dc2626", border: "1px solid #fecaca", borderRadius: 12, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>停止中</span>
                      )}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#6b6559", fontFamily: '"JetBrains Mono", monospace', fontSize: 12 }}>{c.slug}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{c.created_at ? new Date(c.created_at).toLocaleDateString("ja-JP") : "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#6b6559", fontSize: 12 }}>
                    {(c.device_count ?? 0) > 0 ? (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                        <span style={{ fontSize: 13 }}>📱</span>
                        {c.device_count}
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ padding: "12px 16px", fontSize: 12 }}>
                    {(c.reception_today ?? 0) > 0 ? (
                      <span style={{ color: "#4a7c4e", fontWeight: 600 }}>{c.reception_today}</span>
                    ) : <span style={{ color: "#a8a198" }}>—</span>}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <a href={`/${c.slug}/admin`} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: "#4a7c4e", textDecoration: "none" }}>詳細 →</a>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <button onClick={() => handleProxyLogin(c)} style={{ border: "1px solid #c8a96e", color: "#b88b44", background: "transparent", padding: "4px 10px", borderRadius: 6, fontSize: 12, cursor: "pointer" }}>代理ログイン</button>
                  </td>
                  <td style={{ padding: "12px 16px", textAlign: "right" as const }}>
                    <MkBtn variant="danger" size="sm" onClick={() => handleDelete(c.id, c.name)}>削除</MkBtn>
                  </td>
                </tr>
              ))}
              {customers.length === 0 && (
                <tr><td colSpan={8} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>顧客テナントがありません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}
    </div>
  );
}

function FormField({ label, value, onChange, hint, type = "text", required, minLength }: { label: string; value: string; onChange: (v: string) => void; hint?: string; type?: string; required?: boolean; minLength?: number }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15" }}>
          {label}
          {required && <span style={{ color: "#c8a96e", marginLeft: 3 }}>*</span>}
        </label>
        {hint && <span style={{ fontSize: 11, color: "#a8a198" }}>{hint}</span>}
      </div>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} required={required} minLength={minLength}
        style={{ width: "100%", border: "1px solid #e2ddd6", borderRadius: 8, padding: "9px 12px", fontSize: 13, background: "#faf8f4", color: "#1d1a15", outline: "none", boxSizing: "border-box" as const }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "#c8a96e"; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "#e2ddd6"; }}
      />
    </div>
  );
}
