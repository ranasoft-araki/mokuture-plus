"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, monospace';

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ email: "", password: "", tenant_name: "", tenant_slug: "" });
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handle = (field: string, value: string) => setForm((f) => ({ ...f, [field]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let tokens;
      if (tab === "login") {
        tokens = await api.login(form.email, form.password);
      } else {
        tokens = await api.register({
          tenant_name: form.tenant_name,
          tenant_slug: form.tenant_slug,
          email: form.email,
          password: form.password,
        });
      }
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role, rememberMe);
      if (tokens.role === "operator") {
        router.push("/ops-console");
      } else if (tokens.role === "reseller") {
        router.push(`/${tokens.tenant_slug}/reseller`);
      } else {
        router.push(`/${tokens.tenant_slug}/admin`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ width: "100vw", height: "100vh", overflow: "hidden", fontFamily: FONT_UI, background: "#faf8f4", display: "flex" }}>
      <div style={{ flex: 1, position: "relative", overflow: "hidden", background: "#0e1410", borderRight: "1px solid #efece5" }}>
        <img
          src="/mokuture-header.png"
          alt="mokuture+ — 木に、新しい答えを。"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", objectPosition: "center" }}
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
        />
        <div style={{ position: "absolute", bottom: 24, right: 24, fontSize: 12, color: "rgba(255,255,255,0.5)", fontFamily: FONT_MONO, letterSpacing: 1 }}>v2.4 · 2026</div>
      </div>

      <div style={{ width: 480, padding: 64, display: "flex", flexDirection: "column", justifyContent: "center", background: "#fffefb" }}>
        <div style={{ maxWidth: 360, width: "100%", alignSelf: "center" }}>
          <div style={{ fontSize: 32, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>
            {tab === "login" ? "おかえりなさい" : "アカウント作成"}
          </div>
          <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.6, marginBottom: 32 }}>
            {tab === "login" ? "管理画面にサインインしてください" : "テナント情報を入力してください"}
          </div>

          <div style={{ display: "flex", gap: 4, background: "#f4f1ea", border: "1px solid #e2ddd6", borderRadius: 8, padding: 3, marginBottom: 24 }}>
            {(["login", "register"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{ flex: 1, padding: "7px 0", borderRadius: 6, border: "none", background: tab === t ? "#fffefb" : "transparent", color: tab === t ? "#1d1a15" : "#6b6559", fontSize: 13, fontWeight: tab === t ? 600 : 500, cursor: "pointer", fontFamily: FONT_JP, boxShadow: tab === t ? "0 1px 3px rgba(29,26,21,0.08)" : "none" }}
              >
                {t === "login" ? "ログイン" : "新規登録"}
              </button>
            ))}
          </div>

          {error && (
            <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#dc2626" }}>
              {error}
            </div>
          )}

          <form onSubmit={submit}>
            {tab === "register" && (
              <>
                <LightField label="テナント名（会社名など）" type="text" value={form.tenant_name} onChange={(v) => handle("tenant_name", v)} hint="磯野木工所" />
                <LightField label="テナントID（URLに使用）" type="text" value={form.tenant_slug} onChange={(v) => handle("tenant_slug", v.toLowerCase())} hint="isonoki（小文字英数字）" />
              </>
            )}
            <LightField label="メールアドレス" type="email" value={form.email} onChange={(v) => handle("email", v)} icon="user" />
            <LightField label="パスワード" type="password" value={form.password} onChange={(v) => handle("password", v)} icon="lock" />

            {tab === "login" && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b6559", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    style={{ width: 16, height: 16, accentColor: "#4a7c4e", cursor: "pointer" }}
                  />
                  ログイン状態を保持
                </label>
                <a href="#" style={{ fontSize: 13, color: "#4a7c4e", fontWeight: 500, textDecoration: "none" }}>お困りですか？</a>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{ width: "100%", padding: "16px", borderRadius: 10, background: "#4a7c4e", color: "#fffefb", border: "none", fontSize: 15, fontWeight: 600, fontFamily: FONT_JP, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1, boxShadow: "0 4px 16px rgba(74,124,78,0.25)", marginBottom: 8 }}
            >
              {loading ? "処理中…" : tab === "login" ? "サインイン →" : "アカウント作成"}
            </button>
          </form>

          <div style={{ marginTop: 24, fontSize: 11, color: "#a8a198", textAlign: "center" as const, lineHeight: 1.6 }}>
            サインインすることで、<a href="#" style={{ color: "#6b6559" }}>利用規約</a> および <a href="#" style={{ color: "#6b6559" }}>プライバシーポリシー</a> に同意したものとみなされます
          </div>
        </div>
      </div>
    </div>
  );
}

function LightField({ label, type, value, onChange, hint, icon }: {
  label: string; type: string; value: string; onChange: (v: string) => void; hint?: string; icon?: string;
}) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", letterSpacing: 0.4, marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
        <span>{label}</span>
        {hint && <span style={{ color: "#a8a198", fontWeight: 400 }}>{hint}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, background: "#faf8f4", border: "1.5px solid #e2ddd6", borderRadius: 10, padding: "12px 14px" }}>
        {icon === "lock" && <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>}
        {icon === "user" && <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>}
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 14, color: "#1d1a15", fontFamily: type === "password" ? FONT_MONO : FONT_UI, letterSpacing: type === "password" ? 2 : 0 }}
          onFocus={(e) => {
            const wrapper = e.currentTarget.closest("div") as HTMLDivElement;
            if (wrapper) { wrapper.style.borderColor = "#4a7c4e"; wrapper.style.boxShadow = "0 0 0 3px rgba(74,124,78,0.1)"; }
          }}
          onBlur={(e) => {
            const wrapper = e.currentTarget.closest("div") as HTMLDivElement;
            if (wrapper) { wrapper.style.borderColor = "#e2ddd6"; wrapper.style.boxShadow = "none"; }
          }}
        />
      </div>
    </div>
  );
}
