"use client";

import { useEffect, useState } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

export default function OperatorResellersPage() {
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", admin_email: "", admin_password: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const token = getAccessToken() ?? "";

  const load = async () => {
    setLoading(true);
    const r = await api.listResellers(token);
    setResellers(r);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true); setError("");
    try {
      await api.createReseller(token, form);
      setShowForm(false);
      setForm({ name: "", slug: "", admin_email: "", admin_password: "" });
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`代理店「${name}」を削除しますか？`)) return;
    await api.deleteReseller(token, id);
    await load();
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <MkSectionTitle title="代理店管理" subtitle={`${resellers.length} 代理店`} />
        <MkBtn variant="primary" size="sm" onClick={() => setShowForm(!showForm)}>+ 代理店追加</MkBtn>
      </div>

      {showForm && (
        <MkCard style={{ marginBottom: 20 }}>
          <MkSectionTitle title="新規代理店作成" />
          {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 12px", marginBottom: 12, fontSize: 13, color: "#dc2626" }}>{error}</div>}
          <form onSubmit={handleCreate} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <FormField label="代理店名" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} required />
            <FormField label="代理店ID（スラッグ）" value={form.slug} onChange={(v) => setForm((f) => ({ ...f, slug: v.toLowerCase() }))} hint="例：asahi-1042" required />
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
                {["代理店名", "代理店ID", "作成日", ""].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {resellers.map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1d1a15" }}>{r.name}</td>
                  <td style={{ padding: "12px 16px", color: "#6b6559", fontFamily: '"JetBrains Mono", monospace', fontSize: 12 }}>{r.slug}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString("ja-JP") : "—"}</td>
                  <td style={{ padding: "12px 16px", textAlign: "right" as const }}>
                    <MkBtn variant="danger" size="sm" onClick={() => handleDelete(r.id, r.name)}>削除</MkBtn>
                  </td>
                </tr>
              ))}
              {resellers.length === 0 && (
                <tr><td colSpan={4} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>代理店がありません</td></tr>
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
