"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, UserListItem } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

function RolePill({ role }: { role: string }) {
  if (role === "admin") return <MkPill tone="live">管理者</MkPill>;
  if (role === "staff") return <MkPill tone="info">スタッフ</MkPill>;
  return <MkPill tone="neutral">{role}</MkPill>;
}

export default function AdminUsersPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [users, setUsers] = useState<UserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState("staff");
  const [formError, setFormError] = useState<string | null>(null);
  const [formSaving, setFormSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      setCurrentUserId(payload.sub ?? null);
    } catch {}
    load(token);
  }, []);

  function load(token: string) {
    setLoading(true);
    api.listUsers(token)
      .then((data) => { setUsers(data); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true);
    setFormError(null);
    try {
      const created = await api.createUser(token, { email: formEmail, password: formPassword, role: formRole });
      setUsers((prev) => [created, ...prev]);
      setShowForm(false);
      setFormEmail("");
      setFormPassword("");
      setFormRole("staff");
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "作成に失敗しました");
    } finally {
      setFormSaving(false);
    }
  }

  async function handleDelete(userId: string) {
    if (!confirm("このユーザーを削除しますか？")) return;
    const token = getAccessToken();
    if (!token) return;
    setDeletingId(userId);
    try {
      await api.deleteUser(token, userId);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "削除に失敗しました");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleRoleChange(userId: string, role: string) {
    const token = getAccessToken();
    if (!token) return;
    try {
      const updated = await api.updateUserRole(token, userId, role);
      setUsers((prev) => prev.map((u) => u.id === userId ? updated : u));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "ロール変更に失敗しました");
    }
  }

  return (
    <AdminShell
      active="users"
      title="ユーザー管理"
      subtitle="テナントのユーザーを管理します"
      breadcrumb={`${tenant} / 設定`}
      actions={
        <MkBtn variant="primary" size="sm" onClick={() => setShowForm((v) => !v)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          ユーザーを追加
        </MkBtn>
      }
    >
      <div style={{ padding: "24px 28px", maxWidth: 860 }}>
        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="新しいユーザーを追加" />
            <form onSubmit={handleCreate}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                    メールアドレス
                  </label>
                  <input
                    type="email"
                    required
                    value={formEmail}
                    onChange={(e) => setFormEmail(e.target.value)}
                    style={{
                      width: "100%", padding: "8px 10px", fontSize: 13,
                      border: "1px solid #d8d3c7", borderRadius: 7,
                      fontFamily: FONT_JP, background: "#faf8f4",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                    パスワード（8文字以上）
                  </label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={formPassword}
                    onChange={(e) => setFormPassword(e.target.value)}
                    style={{
                      width: "100%", padding: "8px 10px", fontSize: 13,
                      border: "1px solid #d8d3c7", borderRadius: 7,
                      fontFamily: FONT_JP, background: "#faf8f4",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                  ロール
                </label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value)}
                  style={{
                    padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7",
                    borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4",
                    minWidth: 180,
                  }}
                >
                  <option value="staff">スタッフ</option>
                  <option value="admin">管理者</option>
                </select>
              </div>
              {formError && (
                <div style={{ fontSize: 12.5, color: "#a84238", marginBottom: 12, fontFamily: FONT_JP }}>
                  {formError}
                </div>
              )}
              <div style={{ display: "flex", gap: 10 }}>
                <MkBtn type="submit" variant="primary" size="sm" disabled={formSaving}>
                  {formSaving ? "作成中..." : "作成"}
                </MkBtn>
                <MkBtn variant="default" size="sm" onClick={() => { setShowForm(false); setFormError(null); }}>
                  キャンセル
                </MkBtn>
              </div>
            </form>
          </MkCard>
        )}

        <MkCard padding="0">
          <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #efece5" }}>
            <MkSectionTitle
              title="ユーザー一覧"
              subtitle={`${users.length} 名`}
              style={{ marginBottom: 0 }}
            />
          </div>

          {loading ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
              読み込み中...
            </div>
          ) : error ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>
              {error}
            </div>
          ) : users.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
              ユーザーがいません
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #efece5" }}>
                  {["メールアドレス", "ロール", "作成日", "操作"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 20px", textAlign: "left",
                        fontSize: 11, color: "#a8a198", fontWeight: 600,
                        letterSpacing: "0.4px", textTransform: "uppercase",
                        fontFamily: FONT_MONO,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u, idx) => (
                  <tr
                    key={u.id}
                    style={{
                      borderBottom: idx < users.length - 1 ? "1px solid #efece5" : "none",
                      background: "transparent",
                    }}
                  >
                    <td style={{ padding: "12px 20px", fontSize: 13, color: "#1d1a15", fontFamily: FONT_JP }}>
                      {u.email}
                      {u.id === currentUserId && (
                        <span style={{ marginLeft: 8, fontSize: 10.5, color: "#a8a198", fontFamily: FONT_MONO }}>（自分）</span>
                      )}
                    </td>
                    <td style={{ padding: "12px 20px" }}>
                      {u.id === currentUserId ? (
                        <RolePill role={u.role} />
                      ) : (
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value)}
                          style={{
                            padding: "4px 8px", fontSize: 12, border: "1px solid #d8d3c7",
                            borderRadius: 6, fontFamily: FONT_JP, background: "#faf8f4",
                            cursor: "pointer",
                          }}
                        >
                          <option value="staff">スタッフ</option>
                          <option value="admin">管理者</option>
                        </select>
                      )}
                    </td>
                    <td style={{ padding: "12px 20px", fontSize: 12, color: "#6b6559", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                      {new Date(u.created_at).toLocaleDateString("ja-JP")}
                    </td>
                    <td style={{ padding: "12px 20px" }}>
                      <MkBtn
                        variant="danger"
                        size="sm"
                        disabled={u.id === currentUserId || deletingId === u.id}
                        onClick={() => handleDelete(u.id)}
                      >
                        {deletingId === u.id ? "削除中..." : "削除"}
                      </MkBtn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </MkCard>
      </div>
    </AdminShell>
  );
}
