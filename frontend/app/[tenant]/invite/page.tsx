"use client";

import { useEffect, useState } from "react";
import { api, InvitationLookup } from "@/lib/api";
import { saveTokens, rememberLoginId } from "@/lib/auth";

// 招待メールのリンク先（公開・認証不要）。
// リンクは /{slug}/invite#token=… の形。トークンは「#」の後ろ（サーバーへ送られない部分）にあり、
// ここで読んで公開 API へ本文で渡す。パスワードを決めると登録され、そのままログインした状態で管理画面へ進む。

const FONT_JP = "'Noto Sans JP', Inter, system-ui, sans-serif";
const ROLE_LABEL: Record<string, string> = { admin: "管理者", staff: "スタッフ" };

const TOKEN_KEY = "mk_invite_token";

// URL の「#token=…」を読んだら、アドレス欄と閲覧履歴から消してこのタブの sessionStorage へ移す
// (共有画面や履歴にリンクが残らないように。再読み込みしても続きから入れる)。
function readToken(): string {
  if (typeof window === "undefined") return "";
  const hash = window.location.hash.replace(/^#/, "");
  const fromHash = new URLSearchParams(hash).get("token") ?? "";
  try {
    if (fromHash) {
      sessionStorage.setItem(TOKEN_KEY, fromHash);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      return fromHash;
    }
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return fromHash;
  }
}

function forgetToken() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch {}
}

function fmt(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function InvitePage() {
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<InvitationLookup | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const t = readToken();
    // マウント後にだけ読める URL の「#」以降からトークンを取る
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(t);
    if (!t) {
      setLoadError("招待リンクが正しくありません。招待メールのボタン（またはリンク）をもう一度開いてください。");
      setLoading(false);
      return;
    }
    api.lookupInvitation(t)
      .then((res) => setInfo(res))
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : "招待を確認できませんでした。時間をおいて再度お試しください。"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) { setError("パスワードは8文字以上にしてください"); return; }
    if (password !== confirm) { setError("確認用のパスワードが一致しません"); return; }
    setSubmitting(true);
    try {
      const res = await api.acceptInvitation(token, password, name.trim() || undefined);
      forgetToken();
      saveTokens(res.access_token, res.refresh_token, res.role, true, res.tenant_slug);
      if (info) rememberLoginId("login", info.email);
      // iOS Safari/PWA にパスワード保存を促すため、ログイン画面と同じく実ナビゲーションで移る
      window.location.assign(`/${res.tenant_slug}/admin`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "登録に失敗しました。時間をおいて再度お試しください。");
      setSubmitting(false);
    }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%", border: "1px solid #d8d3c7", borderRadius: 10, background: "#fffefb",
    padding: "12px 14px", fontSize: 16, color: "#1d1a15", outline: "none", boxSizing: "border-box", fontFamily: FONT_JP,
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: "#2d2a24", marginBottom: 6, display: "block" };
  const card: React.CSSProperties = { background: "#fffefb", border: "1px solid #e7e3d9", borderRadius: 16, padding: "28px 24px" };

  return (
    <div style={{ minHeight: "100vh", background: "#faf8f4", display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 16px", fontFamily: FONT_JP }}>
      <div style={{ width: "100%", maxWidth: 480 }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.3em", color: "#a8a198", marginBottom: 8 }}>mokuture+</div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "#1d1a15", margin: 0 }}>管理画面への招待</h1>
        </div>

        {loading ? (
          <div style={{ ...card, textAlign: "center", color: "#a8a198", fontSize: 14 }}>招待を確認しています...</div>
        ) : loadError || !info ? (
          <div style={card}>
            <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#a84238" }}>{loadError}</p>
            <a href="/login" style={{ fontSize: 14, color: "#3e6b42", fontWeight: 600 }}>ログイン画面へ</a>
          </div>
        ) : info.email_taken ? (
          <div style={card}>
            <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#4a463d" }}>
              {info.email} は既に登録されています。ログイン画面からログインしてください。
            </p>
            <a href="/login" style={{ fontSize: 14, color: "#3e6b42", fontWeight: 600 }}>ログイン画面へ</a>
          </div>
        ) : (
          <form onSubmit={submit} style={card}>
            <p style={{ margin: "0 0 20px", fontSize: 14, lineHeight: 1.8, color: "#4a463d" }}>
              <b>{info.tenant_name}</b> の管理画面に、{ROLE_LABEL[info.role] ?? info.role}として招待されています。
              パスワードを決めると登録され、そのままログインします。
            </p>

            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle} htmlFor="inv-email">ログインID（メールアドレス）</label>
              <input id="inv-email" name="username" autoComplete="username" value={info.email} readOnly
                style={{ ...inputStyle, background: "#f3f1ec", color: "#6b6559" }} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle} htmlFor="inv-name">お名前（任意）</label>
              <input id="inv-name" name="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} style={inputStyle} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle} htmlFor="inv-password">パスワード（8文字以上）</label>
              <input id="inv-password" name="password" type="password" autoComplete="new-password" required minLength={8}
                value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle} />
            </div>
            <div style={{ marginBottom: 18 }}>
              <label style={labelStyle} htmlFor="inv-confirm">パスワード（確認のためもう一度）</label>
              <input id="inv-confirm" name="password-confirm" type="password" autoComplete="new-password" required minLength={8}
                value={confirm} onChange={(e) => setConfirm(e.target.value)} style={inputStyle} />
            </div>

            {error && <div style={{ fontSize: 13, color: "#a84238", marginBottom: 14, lineHeight: 1.7 }}>{error}</div>}

            <button type="submit" disabled={submitting}
              style={{ width: "100%", padding: "14px 16px", border: "none", borderRadius: 10, background: submitting ? "#9db59f" : "#4a7c4e", color: "#fff", fontSize: 15, fontWeight: 700, cursor: submitting ? "default" : "pointer", fontFamily: FONT_JP }}>
              {submitting ? "登録しています..." : "パスワードを決めて登録する"}
            </button>
            {info.expires_at && (
              <p style={{ margin: "14px 0 0", fontSize: 12, color: "#8a8478", textAlign: "center" }}>
                このリンクは {fmt(info.expires_at)} まで使えます
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
