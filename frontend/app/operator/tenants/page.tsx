"use client";

import { useEffect, useRef, useState } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

// ── Dark operator theme constants ──────────────────────────────────────────
const DARK_CARD: React.CSSProperties = {
  background: "#1a1810",
  border: "1px solid #3a3528",
  borderRadius: 10,
  padding: "20px 24px",
  marginBottom: 20,
};

const DARK_LABEL: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: "rgba(255,255,255,0.45)",
  letterSpacing: "0.5px",
  textTransform: "uppercase",
  display: "block",
  marginBottom: 6,
};

const DARK_INPUT: React.CSSProperties = {
  width: "100%",
  background: "#0e0c08",
  border: "1px solid #3a3528",
  borderRadius: 7,
  padding: "9px 12px",
  fontSize: 13,
  color: "#fffefb",
  outline: "none",
  boxSizing: "border-box",
  fontFamily: "inherit",
};

const DARK_SELECT: React.CSSProperties = {
  ...DARK_INPUT,
  cursor: "pointer",
};

// ── DarkFormField ──────────────────────────────────────────────────────────
function DarkFormField({
  label,
  value,
  onChange,
  hint,
  type = "text",
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  type?: string;
  required?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <label style={DARK_LABEL}>{label}</label>
        {hint && <span style={{ fontSize: 11, color: "rgba(255,255,255,0.3)" }}>{hint}</span>}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        style={{ ...DARK_INPUT, borderColor: focused ? "#c8a96e" : "#3a3528" }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      />
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function OperatorTenantsPage() {
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const PAGE_SIZE = 50;

  // create-form panel
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    slug: "",
    reseller_id: "",
    admin_email: "",
    admin_password: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // notes
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const [notesDraft, setNotesDraft] = useState<Record<string, string>>({});
  const [notesSaved, setNotesSaved] = useState<Record<string, boolean>>({});

  // reseller change
  const [expandedReseller, setExpandedReseller] = useState<Set<string>>(new Set());
  const [resellerDraft, setResellerDraft] = useState<Record<string, string>>({});
  const [resellerSaving, setResellerSaving] = useState<Record<string, boolean>>({});
  const [resellerMsg, setResellerMsg] = useState<Record<string, { ok: boolean; text: string }>>({});

  // delete error banner
  const [deleteError, setDeleteError] = useState("");

  // panel height for animation
  const formPanelRef = useRef<HTMLDivElement>(null);
  const [panelHeight, setPanelHeight] = useState(0);

  const token = getAccessToken() ?? "";

  const load = async (targetPage = page) => {
    setLoading(true);
    const [res, r] = await Promise.all([
      api.listOperatorTenants(token, { page: targetPage, page_size: PAGE_SIZE }),
      api.listResellers(token),
    ]);
    const t = res.items;
    setTenants(t);
    setTotal(res.total);
    setTotalPages(res.total_pages);
    setResellers(r);
    const drafts: Record<string, string> = {};
    for (const tenant of t) {
      drafts[tenant.id] = tenant.operator_notes ?? "";
    }
    setNotesDraft((prev) => {
      const next = { ...drafts };
      for (const id of Object.keys(prev)) {
        if (id in next) next[id] = prev[id];
      }
      return next;
    });
    setLoading(false);
  };

  useEffect(() => {
    load(1);
    setPage(1);
  }, []);

  // Measure panel height whenever form opens/closes
  useEffect(() => {
    if (showForm && formPanelRef.current) {
      setPanelHeight(formPanelRef.current.scrollHeight);
    } else {
      setPanelHeight(0);
    }
  }, [showForm]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.admin_password.length < 8) {
      setError("パスワードは8文字以上で入力してください");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const newTenant = await api.createOperatorTenant(token, {
        ...form,
        reseller_id: form.reseller_id || undefined,
      });
      // Prepend newly created tenant to list
      setTenants((prev) => [
        {
          id: newTenant.id,
          slug: newTenant.slug,
          name: newTenant.name,
          reseller_id: form.reseller_id || null,
          is_suspended: false,
          created_at: new Date().toISOString(),
          operator_notes: null,
        } as OperatorTenant,
        ...prev,
      ]);
      setShowForm(false);
      setForm({ name: "", slug: "", reseller_id: "", admin_email: "", admin_password: "" });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "エラーが発生しました";
      if (msg.includes("slug") || msg.includes("Slug") || msg.includes("already taken")) {
        setError("スラッグが既に使用されています");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`「${name}」を完全に削除しますか？この操作は取り消せません。`)) return;
    setDeleteError("");
    try {
      await api.deleteOperatorTenant(token, id);
      setTenants((prev) => prev.filter((t) => t.id !== id));
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  };

  const handleSuspend = async (tenant: OperatorTenant) => {
    const action = tenant.is_suspended ? "再開" : "停止";
    if (!confirm(`テナント「${tenant.name}」を${action}しますか？`)) return;
    try {
      await api.suspendTenant(token, tenant.id, !tenant.is_suspended);
      await load(page);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "操作に失敗しました");
    }
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    load(newPage);
  };

  const handleProxyLogin = async (tenant: OperatorTenant) => {
    if (
      !confirm(
        `「${tenant.name}」の管理画面に代理ログインします。新しいタブで開きます。続行しますか？`
      )
    )
      return;
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

  const toggleNotes = (id: string, currentNotes: string | null) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        setNotesDraft((d) => ({ ...d, [id]: d[id] ?? (currentNotes ?? "") }));
      }
      return next;
    });
  };

  const handleSaveNotes = async (tenantId: string) => {
    const notes = notesDraft[tenantId] ?? "";
    try {
      await api.updateTenantNotes(token, tenantId, notes);
      setTenants((prev) =>
        prev.map((t) =>
          t.id === tenantId ? { ...t, operator_notes: notes || null } : t
        )
      );
      setNotesSaved((s) => ({ ...s, [tenantId]: true }));
      setTimeout(
        () => setNotesSaved((s) => ({ ...s, [tenantId]: false })),
        2000
      );
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "保存に失敗しました");
    }
  };

  const toggleReseller = (id: string, currentResellerId: string | null | undefined) => {
    setExpandedReseller((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        setResellerDraft((d) => ({ ...d, [id]: currentResellerId ?? "" }));
        setResellerMsg((m) => ({ ...m, [id]: { ok: true, text: "" } }));
      }
      return next;
    });
  };

  const handleUpdateReseller = async (tenantId: string) => {
    const newResellerId = resellerDraft[tenantId] ?? "";
    setResellerSaving((s) => ({ ...s, [tenantId]: true }));
    setResellerMsg((m) => ({ ...m, [tenantId]: { ok: true, text: "" } }));
    try {
      await api.updateTenantReseller(token, tenantId, newResellerId || null);
      setTenants((prev) =>
        prev.map((t) =>
          t.id === tenantId ? { ...t, reseller_id: newResellerId || null } : t
        )
      );
      setResellerMsg((m) => ({ ...m, [tenantId]: { ok: true, text: "変更しました" } }));
      setTimeout(
        () => setResellerMsg((m) => ({ ...m, [tenantId]: { ok: true, text: "" } })),
        2000
      );
    } catch (err: unknown) {
      setResellerMsg((m) => ({
        ...m,
        [tenantId]: { ok: false, text: err instanceof Error ? err.message : "変更に失敗しました" },
      }));
    } finally {
      setResellerSaving((s) => ({ ...s, [tenantId]: false }));
    }
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 20,
        }}
      >
        <MkSectionTitle
          title="テナント管理"
          subtitle={`${total} テナント`}
        />
        <button
          onClick={() => {
            setShowForm((v) => !v);
            setError("");
          }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 16px",
            background: showForm ? "#2a2418" : "#c8a96e",
            border: showForm ? "1px solid #c8a96e" : "none",
            borderRadius: 7,
            color: showForm ? "#c8a96e" : "#1a1810",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            transition: "background 0.15s, color 0.15s",
            fontFamily: "inherit",
          }}
        >
          <span style={{ fontSize: 16, lineHeight: 1 }}>＋</span>
          新規テナント追加
        </button>
      </div>

      {/* ── Delete error banner ──────────────────────────────────────────── */}
      {deleteError && (
        <div
          style={{
            background: "rgba(239,68,68,0.10)",
            border: "1px solid rgba(239,68,68,0.4)",
            borderRadius: 7,
            padding: "10px 14px",
            marginBottom: 16,
            fontSize: 13,
            color: "#dc2626",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span>{deleteError}</span>
          <button
            onClick={() => setDeleteError("")}
            style={{
              background: "transparent",
              border: "none",
              color: "#dc2626",
              fontSize: 16,
              cursor: "pointer",
              lineHeight: 1,
              padding: "0 4px",
            }}
          >
            ×
          </button>
        </div>
      )}

      {/* ── Expandable create-form panel ─────────────────────────────────── */}
      <div
        style={{
          overflow: "hidden",
          maxHeight: showForm ? (panelHeight > 0 ? panelHeight : 9999) : 0,
          transition: "max-height 0.3s cubic-bezier(0.4,0,0.2,1)",
        }}
      >
        <div ref={formPanelRef}>
          <div style={{ ...DARK_CARD, marginBottom: 20 }}>
            {/* Panel header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 20,
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 600,
                    color: "#fffefb",
                    letterSpacing: "-0.2px",
                  }}
                >
                  新規テナント作成
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "rgba(255,255,255,0.35)",
                    marginTop: 2,
                  }}
                >
                  テナントと管理者アカウントを同時に作成します
                </div>
              </div>
              <button
                onClick={() => setShowForm(false)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "rgba(255,255,255,0.35)",
                  fontSize: 20,
                  cursor: "pointer",
                  lineHeight: 1,
                  padding: "2px 6px",
                }}
              >
                ×
              </button>
            </div>

            {/* Error message */}
            {error && (
              <div
                style={{
                  background: "rgba(239,68,68,0.12)",
                  border: "1px solid rgba(239,68,68,0.4)",
                  borderRadius: 7,
                  padding: "10px 14px",
                  marginBottom: 16,
                  fontSize: 13,
                  color: "#f87171",
                }}
              >
                {error}
              </div>
            )}

            <form
              onSubmit={handleCreate}
              style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}
            >
              {/* テナント名 */}
              <DarkFormField
                label="テナント名"
                value={form.name}
                onChange={(v) => setForm((f) => ({ ...f, name: v }))}
                required
              />

              {/* スラッグ */}
              <DarkFormField
                label="スラッグ"
                value={form.slug}
                onChange={(v) => setForm((f) => ({ ...f, slug: v.toLowerCase() }))}
                hint="英小文字・数字・ハイフン 3-64文字"
                required
              />

              {/* 管理者メールアドレス */}
              <DarkFormField
                label="管理者メールアドレス"
                type="email"
                value={form.admin_email}
                onChange={(v) => setForm((f) => ({ ...f, admin_email: v }))}
                required
              />

              {/* 管理者パスワード */}
              <DarkFormField
                label="管理者パスワード"
                type="password"
                value={form.admin_password}
                onChange={(v) => setForm((f) => ({ ...f, admin_password: v }))}
                hint="8文字以上"
                required
              />

              {/* 代理店 — full width */}
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={DARK_LABEL}>代理店に紐付ける（任意）</label>
                <select
                  value={form.reseller_id}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, reseller_id: e.target.value }))
                  }
                  style={DARK_SELECT}
                >
                  <option value="">なし（直営テナント）</option>
                  {resellers.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} ({r.slug})
                    </option>
                  ))}
                </select>
              </div>

              {/* Actions */}
              <div
                style={{
                  gridColumn: "1 / -1",
                  display: "flex",
                  gap: 10,
                  justifyContent: "flex-end",
                  marginTop: 4,
                  paddingTop: 16,
                  borderTop: "1px solid #3a3528",
                }}
              >
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setError("");
                    setForm({
                      name: "",
                      slug: "",
                      reseller_id: "",
                      admin_email: "",
                      admin_password: "",
                    });
                  }}
                  style={{
                    padding: "8px 18px",
                    background: "transparent",
                    border: "1px solid #3a3528",
                    borderRadius: 7,
                    color: "rgba(255,255,255,0.5)",
                    fontSize: 13,
                    cursor: "pointer",
                    fontFamily: "inherit",
                  }}
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  style={{
                    padding: "8px 22px",
                    background: submitting ? "#6b5e40" : "#c8a96e",
                    border: "none",
                    borderRadius: 7,
                    color: "#1a1810",
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: submitting ? "not-allowed" : "pointer",
                    fontFamily: "inherit",
                    transition: "background 0.15s",
                  }}
                >
                  {submitting ? "作成中…" : "テナントを作成"}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>

      {/* ── Tenant table ─────────────────────────────────────────────────── */}
      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <MkCard padding="0">
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
          >
            <thead>
              <tr style={{ borderBottom: "1px solid #efece5" }}>
                {["テナント名", "スラッグ", "デバイス", "本日受付", "代理店", "作成日", ""].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 16px",
                      textAlign: "left" as const,
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#a8a198",
                      letterSpacing: "0.4px",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <>
                  <tr
                    key={t.id}
                    style={{
                      borderBottom: expandedNotes.has(t.id)
                        ? "none"
                        : "1px solid #f4f1ea",
                      background: t.is_suspended ? "#fff8f8" : undefined,
                    }}
                  >
                    <td
                      style={{
                        padding: "12px 16px",
                        fontWeight: 600,
                        color: "#1d1a15",
                      }}
                    >
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        {t.name}
                        {t.is_suspended && (
                          <span
                            style={{
                              background: "#fef3c7",
                              border: "1px solid #f59e0b",
                              color: "#b45309",
                              fontSize: 11,
                              fontWeight: 600,
                              padding: "2px 8px",
                              borderRadius: 999,
                            }}
                          >
                            停止中
                          </span>
                        )}
                        {t.operator_notes && (
                          <span
                            style={{
                              background: "#fef9c3",
                              color: "#854d0e",
                              border: "1px solid #fef08a",
                              borderRadius: 10,
                              padding: "2px 7px",
                              fontSize: 10,
                              fontWeight: 600,
                            }}
                          >
                            メモあり
                          </span>
                        )}
                      </span>
                    </td>
                    <td
                      style={{
                        padding: "12px 16px",
                        color: "#6b6559",
                        fontFamily: '"JetBrains Mono", monospace',
                        fontSize: 12,
                      }}
                    >
                      {t.slug}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#6b6559", fontSize: 13 }}>
                      {(t.device_count ?? 0) > 0 ? `📱 ${t.device_count}` : "—"}
                    </td>
                    <td style={{ padding: "12px 16px", fontSize: 13 }}>
                      {(t.reception_today ?? 0) > 0 ? (
                        <span style={{ color: "#16a34a", fontWeight: 700 }}>{t.reception_today}</span>
                      ) : (
                        <span style={{ color: "#a8a198" }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#a8a198" }}>
                      {resellers.find((r) => r.id === t.reseller_id)?.name ?? "—"}
                    </td>
                    <td
                      style={{
                        padding: "12px 16px",
                        color: "#a8a198",
                        fontSize: 12,
                      }}
                    >
                      {t.created_at
                        ? new Date(t.created_at).toLocaleDateString("ja-JP")
                        : "—"}
                    </td>
                    <td
                      style={{
                        padding: "12px 16px",
                        textAlign: "right" as const,
                        display: "flex",
                        gap: 8,
                        justifyContent: "flex-end",
                        alignItems: "center",
                      }}
                    >
                      <button
                        onClick={() => toggleNotes(t.id, t.operator_notes)}
                        style={{
                          border: "1px solid #d8d3c7",
                          color: "#6b6559",
                          background: expandedNotes.has(t.id)
                            ? "#f4f1ea"
                            : "transparent",
                          padding: "4px 10px",
                          borderRadius: 6,
                          fontSize: 11,
                          cursor: "pointer",
                        }}
                      >
                        メモ
                      </button>
                      <button
                        onClick={() => toggleReseller(t.id, t.reseller_id)}
                        style={{
                          border: "1px solid #6366f1",
                          color: "#6366f1",
                          background: expandedReseller.has(t.id)
                            ? "#eef2ff"
                            : "transparent",
                          padding: "4px 10px",
                          borderRadius: 6,
                          fontSize: 11,
                          cursor: "pointer",
                        }}
                      >
                        代理店変更
                      </button>
                      {t.is_suspended ? (
                        <button
                          onClick={() => handleSuspend(t)}
                          style={{
                            border: "none",
                            color: "#fff",
                            background: "#4a7c4e",
                            padding: "4px 10px",
                            borderRadius: 6,
                            fontSize: 11,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          テナントを再開
                        </button>
                      ) : (
                        <button
                          onClick={() => handleSuspend(t)}
                          style={{
                            border: "none",
                            color: "#fff",
                            background: "#dc2626",
                            padding: "4px 10px",
                            borderRadius: 6,
                            fontSize: 11,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          テナントを停止
                        </button>
                      )}
                      <button
                        onClick={() => handleProxyLogin(t)}
                        style={{
                          background: "#2d6a4f",
                          border: "none",
                          color: "#fff",
                          padding: "6px 14px",
                          borderRadius: 6,
                          fontSize: 12,
                          cursor: "pointer",
                          fontFamily: "inherit",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#235a3f"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#2d6a4f"; }}
                      >
                        ↗ 管理画面を開く
                      </button>
                      <button
                        onClick={() => handleDelete(t.id, t.name)}
                        title="テナントを削除"
                        style={{
                          border: "1px solid #ef4444",
                          color: "#ef4444",
                          background: "transparent",
                          padding: "4px 10px",
                          borderRadius: 6,
                          fontSize: 14,
                          cursor: "pointer",
                          lineHeight: 1,
                        }}
                      >
                        🗑
                      </button>
                    </td>
                  </tr>
                  {expandedNotes.has(t.id) && (
                    <tr
                      key={`${t.id}-notes`}
                      style={{ borderBottom: "1px solid #f4f1ea" }}
                    >
                      <td
                        colSpan={7}
                        style={{
                          background: "#fffef8",
                          borderTop: "1px solid #f4f1ea",
                          padding: "12px 16px",
                        }}
                      >
                        <NotesEditor
                          tenantId={t.id}
                          value={notesDraft[t.id] ?? ""}
                          saved={notesSaved[t.id] ?? false}
                          onChange={(v) =>
                            setNotesDraft((d) => ({ ...d, [t.id]: v }))
                          }
                          onSave={() => handleSaveNotes(t.id)}
                        />
                      </td>
                    </tr>
                  )}
                  {expandedReseller.has(t.id) && (
                    <tr
                      key={`${t.id}-reseller`}
                      style={{ borderBottom: "1px solid #f4f1ea" }}
                    >
                      <td
                        colSpan={7}
                        style={{
                          background: "#f5f3ff",
                          borderTop: "1px solid #e0e7ff",
                          padding: "12px 16px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <span style={{ fontSize: 12, fontWeight: 600, color: "#4338ca", minWidth: 80 }}>
                            代理店変更
                          </span>
                          <select
                            value={resellerDraft[t.id] ?? ""}
                            onChange={(e) =>
                              setResellerDraft((d) => ({ ...d, [t.id]: e.target.value }))
                            }
                            style={{
                              border: "1px solid #c7d2fe",
                              borderRadius: 6,
                              padding: "5px 10px",
                              fontSize: 13,
                              background: "#fff",
                              color: "#1d1a15",
                              cursor: "pointer",
                              minWidth: 200,
                            }}
                          >
                            <option value="">なし（直営）</option>
                            {resellers.map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.name} ({r.slug})
                              </option>
                            ))}
                          </select>
                          <button
                            onClick={() => handleUpdateReseller(t.id)}
                            disabled={resellerSaving[t.id]}
                            style={{
                              padding: "5px 14px",
                              background: resellerSaving[t.id] ? "#a5b4fc" : "#6366f1",
                              border: "none",
                              borderRadius: 6,
                              color: "#fff",
                              fontSize: 12,
                              fontWeight: 600,
                              cursor: resellerSaving[t.id] ? "not-allowed" : "pointer",
                              fontFamily: "inherit",
                            }}
                          >
                            {resellerSaving[t.id] ? "変更中…" : "変更する"}
                          </button>
                          {resellerMsg[t.id]?.text && (
                            <span
                              style={{
                                fontSize: 12,
                                color: resellerMsg[t.id].ok ? "#16a34a" : "#dc2626",
                              }}
                            >
                              {resellerMsg[t.id].text}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {tenants.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    style={{
                      padding: "24px",
                      textAlign: "center" as const,
                      color: "#a8a198",
                    }}
                  >
                    テナントがありません
                  </td>
                </tr>
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

// ── NotesEditor ────────────────────────────────────────────────────────────
function NotesEditor({
  tenantId,
  value,
  saved,
  onChange,
  onSave,
}: {
  tenantId: string;
  value: string;
  saved: boolean;
  onChange: (v: string) => void;
  onSave: () => void;
}) {
  // suppress unused warning
  void tenantId;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && e.ctrlKey) {
      e.preventDefault();
      onSave();
    }
  };

  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={onSave}
        placeholder="内部メモを追加..."
        style={{
          width: "100%",
          padding: "8px",
          border: "1px solid #d8d3c7",
          borderRadius: 6,
          fontSize: 13,
          fontFamily: "inherit",
          resize: "vertical",
          minHeight: 60,
          background: "#fffef8",
          outline: "none",
          boxSizing: "border-box" as const,
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 8,
          marginTop: 6,
        }}
      >
        {saved && (
          <span style={{ fontSize: 12, color: "#4a7c4e" }}>保存しました</span>
        )}
        <button
          onClick={onSave}
          style={{
            border: "1px solid #4a7c4e",
            color: "#4a7c4e",
            background: "transparent",
            padding: "4px 12px",
            borderRadius: 6,
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          保存
        </button>
      </div>
    </div>
  );
}
