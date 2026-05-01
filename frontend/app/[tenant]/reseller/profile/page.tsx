"use client";

import { useEffect, useState } from "react";
import { api, type MeProfile } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const ACCENT = "#b8763a";

function MkCard({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: "#fffefb",
      border: "1px solid #efece5",
      borderRadius: 10,
      padding: 20,
      boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
      fontFamily: FONT_JP,
      ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, letterSpacing: "-0.1px" }}>{title}</div>
      {subtitle && <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3, fontFamily: FONT_JP }}>{subtitle}</div>}
    </div>
  );
}

function RoleTag({ role }: { role: string }) {
  const label = role === "reseller" ? "代理店" : role === "admin" ? "管理者" : role === "operator" ? "運営" : role;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "3px 10px", borderRadius: 999,
      background: "#fdf3e4", color: "#8a5a1e",
      border: `1px solid ${ACCENT}`,
      fontSize: 11, fontWeight: 600, fontFamily: FONT_JP,
    }}>
      {label}
    </span>
  );
}

export default function ResellerProfilePage() {
  const [profile, setProfile] = useState<MeProfile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Profile section
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Password section
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

  const inputStyle: React.CSSProperties = {
    flex: 1, border: "none", outline: "none",
    background: "transparent", fontSize: 12.5,
    color: "#2d2a24", height: "100%", fontFamily: FONT_JP,
  };

  const inputWrap: React.CSSProperties = {
    display: "flex", alignItems: "center",
    border: "1px solid #d8d3c7", borderRadius: 7,
    background: "#fffefb", padding: "0 10px", height: 34,
  };

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    display: "inline-flex", alignItems: "center",
    padding: "5px 12px", fontSize: 12,
    background: ACCENT, color: "#fffefb",
    border: `1px solid ${ACCENT}`, borderRadius: 7,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    fontFamily: FONT_JP,
  });

  return (
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
              <SectionTitle title="プロフィール" subtitle="表示名・メールアドレス・ロール" />

              {error && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, fontSize: 12.5, color: "#a84238" }}>
                  {error}
                </div>
              )}
              {saved && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f0ebe0", border: "1px solid #d9c9a8", borderRadius: 7, fontSize: 12.5, color: "#7a5a1e" }}>
                  保存しました
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>表示名</div>
                  <div style={inputWrap}>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="例: 山田 太郎"
                      style={inputStyle}
                    />
                  </div>
                </label>

                <div>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>メールアドレス</div>
                  <div style={{ ...inputWrap, background: "#f8f6f2" }}>
                    <span style={{ fontSize: 12.5, color: "#a8a198", fontFamily: FONT_JP }}>{profile.email}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#a8a198", marginTop: 4 }}>メールアドレスの変更は管理者にお問い合わせください</div>
                </div>

                <div>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>ロール</div>
                  <RoleTag role={profile.role} />
                </div>

                <div>
                  <button onClick={handleSaveProfile} disabled={saving} style={btnStyle(saving)}>
                    {saving ? "保存中..." : "保存"}
                  </button>
                </div>
              </div>
            </MkCard>

            {/* ── Card 2: パスワード変更 ── */}
            <MkCard>
              <SectionTitle title="パスワード変更" subtitle="ログインパスワードを変更します" />

              {pwError && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, fontSize: 12.5, color: "#a84238" }}>
                  {pwError}
                </div>
              )}
              {pwSaved && (
                <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f0ebe0", border: "1px solid #d9c9a8", borderRadius: 7, fontSize: 12.5, color: "#7a5a1e" }}>
                  パスワードを変更しました
                </div>
              )}

              <form onSubmit={handleChangePassword} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>現在のパスワード</div>
                  <div style={inputWrap}>
                    <input
                      type="password"
                      required
                      value={currentPw}
                      onChange={(e) => setCurrentPw(e.target.value)}
                      autoComplete="current-password"
                      style={inputStyle}
                    />
                  </div>
                </label>

                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>新しいパスワード</div>
                  <div style={inputWrap}>
                    <input
                      type="password"
                      required
                      minLength={8}
                      value={newPw}
                      onChange={(e) => setNewPw(e.target.value)}
                      autoComplete="new-password"
                      style={inputStyle}
                    />
                  </div>
                  <div style={{ fontSize: 11, color: "#a8a198", marginTop: 4 }}>8文字以上</div>
                </label>

                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>確認</div>
                  <div style={inputWrap}>
                    <input
                      type="password"
                      required
                      value={confirmPw}
                      onChange={(e) => setConfirmPw(e.target.value)}
                      autoComplete="new-password"
                      style={inputStyle}
                    />
                  </div>
                </label>

                <div>
                  <button type="submit" disabled={pwSaving} style={btnStyle(pwSaving)}>
                    {pwSaving ? "変更中..." : "変更"}
                  </button>
                </div>
              </form>
            </MkCard>
          </>
        )}
      </div>
  );
}
