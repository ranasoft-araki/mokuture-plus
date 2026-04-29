"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkCard, MkSectionTitle, MkBtn, MkPill } from "@/components/AdminShell";
import { api, type MeProfile } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';

export default function AdminProfilePage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [profile, setProfile] = useState<MeProfile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Profile section state
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Password section state
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwSaving, setPwSaving] = useState(false);
  const [pwSaved, setPwSaved] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getMe(token)
      .then((p) => {
        setProfile(p);
        setName(p.name ?? "");
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : "読み込みに失敗しました"));
  }, []);

  const roleLabel = (role: string) => {
    if (role === "admin") return "管理者";
    if (role === "staff") return "スタッフ";
    if (role === "reseller") return "代理店";
    if (role === "operator") return "運営";
    return role;
  };

  const roleTone = (role: string): "live" | "info" | "warn" | "neutral" => {
    if (role === "admin") return "live";
    if (role === "operator") return "info";
    if (role === "reseller") return "warn";
    return "neutral";
  };

  const handleSaveProfile = async () => {
    const token = getAccessToken();
    if (!token) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.updateMe(token, { name });
      setProfile(updated);
      setName(updated.name ?? "");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPw !== confirmPw) {
      setPwError("パスワードが一致しません");
      return;
    }
    if (newPw.length < 8) {
      setPwError("新しいパスワードは8文字以上にしてください");
      return;
    }
    const token = getAccessToken();
    if (!token) return;
    setPwSaving(true);
    setPwError(null);
    setPwSaved(false);
    try {
      await api.changePassword(token, currentPw, newPw);
      setPwSaved(true);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
      setTimeout(() => setPwSaved(false), 3000);
    } catch (e: unknown) {
      setPwError(e instanceof Error ? e.message : "パスワードの変更に失敗しました");
    } finally {
      setPwSaving(false);
    }
  };

  return (
    <AdminShell
      active="profile"
      title="アカウント設定"
      breadcrumb={`ホーム / 設定 / アカウント`}
      subtitle="プロフィール情報とパスワードの管理"
    >
      <div style={{ padding: "28px 32px", maxWidth: 600, display: "flex", flexDirection: "column", gap: 20, fontFamily: FONT_JP }}>
        {loadError && (
          <div style={{ padding: "10px 14px", background: "#f6e0dc", borderRadius: 8, color: "#a84238", fontSize: 13 }}>
            {loadError}
          </div>
        )}

        {!profile && !loadError && (
          <div style={{ color: "#a8a198", fontSize: 13 }}>読み込み中…</div>
        )}

        {profile && (
          <>
            {/* ── Card 1: プロフィール ── */}
            <MkCard>
              <MkSectionTitle title="プロフィール" subtitle="表示名・メールアドレス・ロール" />

              {error && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, fontSize: 12.5, color: "#a84238" }}>
                  {error}
                </div>
              )}
              {saved && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f1f8f2", border: "1px solid #b5d9b8", borderRadius: 7, fontSize: 12.5, color: "#2d6a32" }}>
                  保存しました
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>表示名</div>
                  <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="例: 山田 太郎"
                      style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%", fontFamily: FONT_JP }}
                    />
                  </div>
                </label>

                <div>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>メールアドレス</div>
                  <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#f8f6f2", padding: "0 10px", height: 34 }}>
                    <span style={{ fontSize: 12.5, color: "#a8a198", fontFamily: FONT_JP }}>{profile.email}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#a8a198", marginTop: 4 }}>メールアドレスの変更は管理者にお問い合わせください</div>
                </div>

                <div>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>ロール</div>
                  <MkPill tone={roleTone(profile.role)}>{roleLabel(profile.role)}</MkPill>
                </div>

                <div>
                  <MkBtn variant="primary" size="sm" onClick={handleSaveProfile} disabled={saving}>
                    {saving ? "保存中..." : "保存"}
                  </MkBtn>
                </div>
              </div>
            </MkCard>

            {/* ── Card 2: パスワード変更 ── */}
            <MkCard>
              <MkSectionTitle title="パスワード変更" subtitle="ログインパスワードを変更します" />

              {pwError && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, fontSize: 12.5, color: "#a84238" }}>
                  {pwError}
                </div>
              )}
              {pwSaved && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f1f8f2", border: "1px solid #b5d9b8", borderRadius: 7, fontSize: 12.5, color: "#2d6a32" }}>
                  パスワードを変更しました
                </div>
              )}

              <form onSubmit={handleChangePassword} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>現在のパスワード</div>
                  <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                    <input
                      type="password"
                      required
                      value={currentPw}
                      onChange={(e) => setCurrentPw(e.target.value)}
                      autoComplete="current-password"
                      style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%", fontFamily: FONT_JP }}
                    />
                  </div>
                </label>

                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>新しいパスワード</div>
                  <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                    <input
                      type="password"
                      required
                      minLength={8}
                      value={newPw}
                      onChange={(e) => setNewPw(e.target.value)}
                      autoComplete="new-password"
                      style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%", fontFamily: FONT_JP }}
                    />
                  </div>
                  <div style={{ fontSize: 11, color: "#a8a198", marginTop: 4 }}>8文字以上</div>
                </label>

                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>確認</div>
                  <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                    <input
                      type="password"
                      required
                      value={confirmPw}
                      onChange={(e) => setConfirmPw(e.target.value)}
                      autoComplete="new-password"
                      style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%", fontFamily: FONT_JP }}
                    />
                  </div>
                </label>

                <div>
                  <MkBtn type="submit" variant="primary" size="sm" disabled={pwSaving}>
                    {pwSaving ? "変更中..." : "変更"}
                  </MkBtn>
                </div>
              </form>
            </MkCard>
          </>
        )}
      </div>
    </AdminShell>
  );
}
