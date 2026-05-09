"use client";

import { useEffect, useState, useMemo } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { ConfirmModal } from "@/components/ConfirmModal";

export default function OperatorResellersPage() {
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", slug: "", admin_email: "", admin_password: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [modal, setModal] = useState<{ msg: string; action: () => Promise<void> } | null>(null);

  const token = getAccessToken() ?? "";

  const load = async () => {
    setLoading(true);
    const r = await api.listResellers(token);
    setResellers(r);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    if (!search.trim()) return resellers;
    const q = search.toLowerCase();
    return resellers.filter(
      (r) => r.name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q)
    );
  }, [resellers, search]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.admin_password.length < 8) { setError("パスワードは8文字以上で入力してください"); return; }
    setSubmitting(true); setError("");
    try {
      await api.createReseller(token, form);
      setShowForm(false);
      setForm({ name: "", slug: "", admin_email: "", admin_password: "" });
      await load();
    } catch (err: unknown) {
      if (err instanceof Error) {
        const msg = err.message;
        if (msg === "Slug already taken") {
          setError("このスラッグはすでに使用されています。別のスラッグを指定してください。");
        } else if (msg === "Admin email already in use") {
          setError("このメールアドレスはすでに登録されています。");
        } else {
          setError(msg || "エラーが発生しました");
        }
      } else {
        setError("エラーが発生しました");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteReseller = (reseller: OperatorTenant) => {
    setModal({
      msg: `「${reseller.name}」を削除しますか？この操作は取り消せません。`,
      action: async () => {
        setDeleteError("");
        try {
          await api.deleteReseller(token, reseller.id);
          setResellers((prev) => prev.filter((r) => r.id !== reseller.id));
        } catch (err: unknown) {
          setDeleteError(err instanceof Error ? (err.message || "削除中にエラーが発生しました") : "削除中にエラーが発生しました");
        }
      },
    });
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      {modal && (
        <ConfirmModal
          message={modal.msg}
          onConfirm={async () => { const action = modal.action; setModal(null); await action(); }}
          onCancel={() => setModal(null)}
        />
      )}
      {/* Delete error banner */}
      {deleteError && (
        <div style={{
          display: "flex", alignItems: "flex-start", justifyContent: "space-between",
          background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.4)",
          borderRadius: 8, padding: "12px 16px", marginBottom: 16,
          fontSize: 13, color: "#f87171",
        }}>
          <span>{deleteError}</span>
          <button
            onClick={() => setDeleteError("")}
            style={{
              marginLeft: 12, background: "none", border: "none",
              color: "#f87171", cursor: "pointer", fontSize: 16, lineHeight: 1, flexShrink: 0,
            }}
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>
      )}

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#f0ead6", letterSpacing: "-0.3px" }}>
            代理店管理
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: 12, color: "#7a7060" }}>
            {resellers.length} 代理店
          </p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setError(""); }}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "8px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
            cursor: "pointer", border: "none",
            background: showForm ? "#a07840" : "#c8a96e",
            color: "#1d1a15",
            transition: "background 0.15s",
          }}
        >
          ＋ 新規代理店追加
        </button>
      </div>

      {/* Create form panel */}
      {showForm && (
        <div style={{
          background: "#211e18", border: "1px solid #3a3528", borderRadius: 12,
          padding: "20px 24px", marginBottom: 20,
        }}>
          <h3 style={{ margin: "0 0 16px", fontSize: 14, fontWeight: 700, color: "#c8a96e", letterSpacing: "0.2px" }}>
            新規代理店作成
          </h3>

          {error && (
            <div style={{
              background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.4)",
              borderRadius: 6, padding: "10px 12px", marginBottom: 14,
              fontSize: 13, color: "#f87171",
            }}>
              {error}
            </div>
          )}

          <form onSubmit={handleCreate} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <DarkFormField
              label="代理店名"
              value={form.name}
              onChange={(v) => setForm((f) => ({ ...f, name: v }))}
              required
            />
            <DarkFormField
              label="代理店スラッグ"
              value={form.slug}
              onChange={(v) => setForm((f) => ({ ...f, slug: v.toLowerCase() }))}
              hint="例: asahi-1042 (英小文字・数字・ハイフン 3-64文字)"
              required
            />
            <DarkFormField
              label="管理者メールアドレス"
              type="email"
              value={form.admin_email}
              onChange={(v) => setForm((f) => ({ ...f, admin_email: v }))}
              required
            />
            <DarkFormField
              label="管理者パスワード"
              type="password"
              value={form.admin_password}
              onChange={(v) => setForm((f) => ({ ...f, admin_password: v }))}
              hint="8文字以上"
              required
            />
            <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
              <button
                type="button"
                onClick={() => { setShowForm(false); setError(""); setForm({ name: "", slug: "", admin_email: "", admin_password: "" }); }}
                style={{
                  padding: "8px 16px", borderRadius: 8, fontSize: 13, fontWeight: 500,
                  cursor: "pointer", background: "transparent",
                  border: "1px solid #3a3528", color: "#a89880",
                  transition: "border-color 0.15s",
                }}
              >
                キャンセル
              </button>
              <button
                type="submit"
                disabled={submitting}
                style={{
                  padding: "8px 20px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                  cursor: submitting ? "not-allowed" : "pointer",
                  background: submitting ? "#7a6540" : "#c8a96e",
                  border: "none", color: "#1d1a15",
                  transition: "background 0.15s",
                }}
              >
                {submitting ? "作成中…" : "作成"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Search bar */}
      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="代理店名・スラッグで検索…"
          style={{
            width: "100%", maxWidth: 360,
            background: "#1a1810", border: "1px solid #3a3528",
            borderRadius: 8, padding: "8px 12px", fontSize: 13,
            color: "#f0ead6", outline: "none", boxSizing: "border-box",
          }}
          onFocus={(e) => { e.currentTarget.style.borderColor = "#c8a96e"; }}
          onBlur={(e) => { e.currentTarget.style.borderColor = "#3a3528"; }}
        />
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: "#7a7060", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <div style={{ background: "#211e18", border: "1px solid #3a3528", borderRadius: 12, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #2e2a22" }}>
                {["代理店名", "代理店スラッグ", "作成日", "顧客テナント", "デバイス", ""].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 16px", textAlign: "left" as const,
                      fontSize: 11, fontWeight: 600, color: "#7a7060", letterSpacing: "0.4px",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid #2e2a22" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#f0ead6" }}>{r.name}</td>
                  <td style={{ padding: "12px 16px", color: "#a89880", fontFamily: '"JetBrains Mono", monospace', fontSize: 12 }}>
                    {r.slug}
                  </td>
                  <td style={{ padding: "12px 16px", color: "#7a7060", fontSize: 12 }}>
                    {r.created_at ? new Date(r.created_at).toLocaleDateString("ja-JP") : "—"}
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a89880", fontSize: 12, textAlign: "right" as const }}>
                    {r.customer_count ? r.customer_count : "—"}
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a89880", fontSize: 12, textAlign: "right" as const }}>
                    {r.device_count ? r.device_count : "—"}
                  </td>
                  <td style={{ padding: "12px 16px", textAlign: "right" as const }}>
                    {(r.customer_count ?? 0) > 0 ? (
                      <button
                        disabled
                        title="顧客テナントが存在するため削除できません"
                        style={{
                          padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: 500,
                          cursor: "not-allowed",
                          background: "transparent", border: "1px solid #3a3528", color: "#4a4438",
                        }}
                      >
                        🗑 削除
                      </button>
                    ) : (
                      <button
                        onClick={() => handleDeleteReseller(r)}
                        style={{
                          padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: 500,
                          cursor: "pointer",
                          background: "transparent", border: "1px solid #5a3030", color: "#e87070",
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(239,68,68,0.12)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                      >
                        🗑 削除
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: "28px", textAlign: "center" as const, color: "#7a7060" }}>
                    {search ? "検索結果がありません" : "代理店がありません"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DarkFormField({
  label, value, onChange, hint, type = "text", required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: "#c8bfa8" }}>{label}</label>
        {hint && <span style={{ fontSize: 11, color: "#7a7060" }}>{hint}</span>}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        style={{
          width: "100%", background: "#1a1810", border: "1px solid #3a3528",
          borderRadius: 8, padding: "9px 12px", fontSize: 13,
          color: "#f0ead6", outline: "none", boxSizing: "border-box" as const,
          transition: "border-color 0.15s",
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "#c8a96e"; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "#3a3528"; }}
      />
    </div>
  );
}
