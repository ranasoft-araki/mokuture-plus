"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";

type RoleTab = "operator" | "reseller" | "customer";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, monospace';

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<RoleTab>("customer");

  return (
    <div style={{ width: "100vw", height: "100vh", overflow: "hidden", fontFamily: FONT_UI, background: "#faf8f4" }}>
      {/* Role selector bar */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
        display: "flex", justifyContent: "center", padding: "16px",
        background: "rgba(250,248,244,0.9)", backdropFilter: "blur(8px)",
        borderBottom: "1px solid #efece5",
      }}>
        <div style={{ display: "flex", gap: 4, background: "#fffefb", border: "1px solid #e2ddd6", borderRadius: 10, padding: 4 }}>
          {(["operator", "reseller", "customer"] as RoleTab[]).map((t) => {
            const labels = { operator: "運営", reseller: "代理店", customer: "利用者" };
            return (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  padding: "7px 20px", borderRadius: 7, border: "none",
                  background: tab === t ? (t === "operator" ? "#1d1a15" : "#4a7c4e") : "transparent",
                  color: tab === t ? "#fffefb" : "#6b6559",
                  fontSize: 13, fontWeight: 600, cursor: "pointer",
                  fontFamily: FONT_JP, transition: "all 0.15s",
                }}
              >
                {labels[t]}
              </button>
            );
          })}
        </div>
      </div>

      {/* Panel */}
      <div style={{ paddingTop: 72, height: "100%" }}>
        {tab === "operator" && <OperatorLogin onSuccess={(role, slug) => afterLogin(role, slug, router)} />}
        {tab === "reseller" && <ResellerLogin onSuccess={(role, slug) => afterLogin(role, slug, router)} />}
        {tab === "customer" && <CustomerLogin onSuccess={(role, slug) => afterLogin(role, slug, router)} />}
      </div>
    </div>
  );
}

function afterLogin(role: string, tenantSlug: string, router: ReturnType<typeof useRouter>) {
  if (role === "operator") {
    router.push("/operator");
  } else if (role === "reseller") {
    router.push(`/${tenantSlug}/reseller`);
  } else {
    router.push(`/${tenantSlug}/admin`);
  }
}

// ── Operator Login ─────────────────────────────────────────────────────────

function OperatorLogin({ onSuccess }: { onSuccess: (role: string, slug: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const tokens = await api.operatorLogin(email, password);
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role);
      onSuccess(tokens.role, tokens.tenant_slug);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      width: "100%", height: "calc(100vh - 72px)",
      background: "#0e0c08", display: "flex", alignItems: "center", justifyContent: "center",
      position: "relative", overflow: "hidden",
    }}>
      {/* Grid background */}
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 0.04, pointerEvents: "none" }}>
        <defs>
          <pattern id="op-grid" x="0" y="0" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M48 0H0v48" fill="none" stroke="#fff" strokeWidth="0.5"/>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#op-grid)"/>
      </svg>

      {/* Header badge */}
      <div style={{ position: "absolute", top: 24, right: 40 }}>
        <span style={{ fontSize: 11, padding: "5px 10px", border: "1px solid rgba(255,255,255,0.18)", borderRadius: 4, color: "rgba(255,255,255,0.55)", letterSpacing: "1.5px", fontFamily: FONT_MONO }}>
          OPS · INTERNAL
        </span>
      </div>

      <div style={{ width: 400, color: "#fffefb", position: "relative" }}>
        {/* Lock icon */}
        <div style={{ width: 56, height: 56, borderRadius: 14, background: "rgba(74,124,78,0.15)", border: "1px solid rgba(74,124,78,0.35)", display: "flex", alignItems: "center", justifyContent: "center", color: "#4a7c4e", marginBottom: 24 }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
        </div>

        <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>サインイン</div>
        <div style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", marginBottom: 32, lineHeight: 1.6 }}>認証情報を入力してください</div>

        {error && <div style={{ background: "rgba(255,80,80,0.12)", border: "1px solid rgba(255,80,80,0.3)", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#ff9090" }}>{error}</div>}

        <form onSubmit={submit}>
          <DarkField label="メールアドレス" type="email" value={email} onChange={setEmail} />
          <DarkField label="パスワード" type="password" value={password} onChange={setPassword} />

          <button
            type="submit" disabled={loading}
            style={{ width: "100%", padding: "16px", borderRadius: 10, background: "#4a7c4e", color: "#fffefb", border: "none", fontSize: 15, fontWeight: 600, fontFamily: FONT_JP, marginTop: 8, marginBottom: 16, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1 }}
          >
            {loading ? "処理中…" : "続ける"}
          </button>
        </form>

        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 14px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", fontSize: 12, color: "rgba(255,255,255,0.55)" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          このページの操作はすべて監査ログに記録されます
        </div>
      </div>

      <div style={{ position: "absolute", bottom: 24, left: 0, right: 0, display: "flex", justifyContent: "space-between", padding: "0 40px", fontSize: 11, color: "rgba(255,255,255,0.35)", fontFamily: FONT_MONO, letterSpacing: 1 }}>
        <span>© 2026 mokuture+</span>
        <span>v2.4</span>
      </div>
    </div>
  );
}

function DarkField({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "rgba(255,255,255,0.7)", letterSpacing: 0.4, marginBottom: 8 }}>{label}</div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        style={{ width: "100%", background: "rgba(255,255,255,0.04)", border: "1.5px solid rgba(255,255,255,0.12)", borderRadius: 10, padding: "14px 16px", fontSize: 15, color: "#fffefb", fontFamily: type === "password" ? FONT_MONO : FONT_UI, letterSpacing: type === "password" ? 2 : 0, outline: "none", boxSizing: "border-box" }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "#4a7c4e"; e.currentTarget.style.boxShadow = "0 0 0 3px rgba(74,124,78,0.18)"; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.12)"; e.currentTarget.style.boxShadow = "none"; }}
      />
    </div>
  );
}

// ── Reseller Login ─────────────────────────────────────────────────────────

function ResellerLogin({ onSuccess }: { onSuccess: (role: string, slug: string) => void }) {
  const [resellerId, setResellerId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const tokens = await api.resellerLogin(resellerId, password);
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role);
      onSuccess(tokens.role, tokens.tenant_slug);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ width: "100%", height: "calc(100vh - 72px)", display: "flex", background: "#faf8f4" }}>
      {/* Left panel */}
      <div style={{ flex: 1, background: "#f4f1ea", borderRight: "1px solid #efece5", padding: 64, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 0 }}>
          <div style={{ width: 36, height: 36, borderRadius: 9, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/><path d="M12 4v10"/></svg>
          </div>
          <span style={{ fontSize: 16, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.3px" }}>mokuture<span style={{ color: "#4a7c4e" }}>+</span></span>
          <span style={{ width: 1, height: 18, background: "#d8d3c7", margin: "0 4px" }} />
          <span style={{ fontSize: 13, color: "#6b6559", letterSpacing: "0.4px" }}>パートナーポータル</span>
        </div>

        <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ fontSize: 11, letterSpacing: 3, color: "#b8763a", textTransform: "uppercase" as const, fontWeight: 700, marginBottom: 18 }}>FOR AUTHORIZED PARTNERS</div>
          <div style={{ fontSize: 48, fontWeight: 600, color: "#1d1a15", letterSpacing: "-1.4px", lineHeight: 1.1, fontFamily: FONT_JP, marginBottom: 24 }}>
            販売パートナー、<br/>ようこそ。
          </div>
          <div style={{ fontSize: 16, color: "#6b6559", lineHeight: 1.8, maxWidth: 380 }}>
            顧客管理・デバイス管理・サポート代行を<br/>一画面で。代理店IDでサインインしてください。
          </div>
        </div>

        <div style={{ fontSize: 12, color: "#a8a198", lineHeight: 1.6 }}>
          パートナー契約のお問い合わせは <a href="mailto:partners@mokuture.jp" style={{ color: "#1d1a15", fontWeight: 500 }}>partners@mokuture.jp</a> まで
        </div>
      </div>

      {/* Right form */}
      <div style={{ width: 480, padding: 64, display: "flex", flexDirection: "column", justifyContent: "center", background: "#fffefb" }}>
        <div style={{ maxWidth: 360, width: "100%", alignSelf: "center" }}>
          <div style={{ fontSize: 32, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>代理店ログイン</div>
          <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.6, marginBottom: 32 }}>代理店IDとパスワードを入力してください</div>

          {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#dc2626" }}>{error}</div>}

          <form onSubmit={submit}>
            <LightField label="代理店ID" type="text" value={resellerId} onChange={setResellerId} hint="例：asahi-1042" icon="folder" />
            <LightField label="パスワード" type="password" value={password} onChange={setPassword} icon="lock" />

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4, marginBottom: 24 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b6559", cursor: "pointer" }}>
                <span style={{ width: 16, height: 16, borderRadius: 4, border: "1.5px solid #d8d3c7", background: "#fffefb", display: "block" }} />
                このデバイスを30日間記憶
              </label>
              <a href="#" style={{ fontSize: 13, color: "#4a7c4e", fontWeight: 500, textDecoration: "none" }}>お困りの方</a>
            </div>

            <button
              type="submit" disabled={loading}
              style={{ width: "100%", padding: "16px", borderRadius: 10, background: "#1d1a15", color: "#fffefb", border: "none", fontSize: 15, fontWeight: 600, fontFamily: FONT_JP, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1 }}
            >
              {loading ? "処理中…" : "サインイン"}
            </button>
          </form>

          <div style={{ marginTop: 36, fontSize: 11, color: "#a8a198", textAlign: "center" as const }}>© 2026 mokuture+ Partners</div>
        </div>
      </div>
    </div>
  );
}

// ── Customer Login ─────────────────────────────────────────────────────────

function CustomerLogin({ onSuccess }: { onSuccess: (role: string, slug: string) => void }) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ email: "", password: "", tenant_name: "", tenant_slug: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handle = (field: string, value: string) => setForm((f) => ({ ...f, [field]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      let tokens;
      if (tab === "login") {
        tokens = await api.login(form.email, form.password);
      } else {
        tokens = await api.register({ tenant_name: form.tenant_name, tenant_slug: form.tenant_slug, email: form.email, password: form.password });
      }
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role);
      onSuccess(tokens.role, tokens.tenant_slug);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ width: "100%", height: "calc(100vh - 72px)", display: "flex", background: "#faf8f4" }}>
      {/* Left panel — forest image */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", background: "#0e1410", borderRight: "1px solid #efece5" }}>
        <img
          src="/mokuture-header.png"
          alt="mokuture+ — 木に、新しい答えを。"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", objectPosition: "center" }}
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
        />
        <div style={{ position: "absolute", bottom: 24, right: 24, fontSize: 12, color: "rgba(255,255,255,0.5)", fontFamily: FONT_MONO, letterSpacing: 1 }}>v2.4 · 2026</div>
      </div>

      {/* Right form */}
      <div style={{ width: 480, padding: 64, display: "flex", flexDirection: "column", justifyContent: "center", background: "#fffefb" }}>
        <div style={{ maxWidth: 360, width: "100%", alignSelf: "center" }}>
          <div style={{ fontSize: 32, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>
            {tab === "login" ? "おかえりなさい" : "アカウント作成"}
          </div>
          <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.6, marginBottom: 32 }}>
            {tab === "login" ? "管理画面にサインインしてください" : "テナント情報を入力してください"}
          </div>

          {/* Tab switcher */}
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

          {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#dc2626" }}>{error}</div>}

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
                  <span style={{ width: 16, height: 16, borderRadius: 4, border: "1.5px solid #d8d3c7", background: "#fffefb", display: "block" }} />
                  ログイン状態を保持
                </label>
                <a href="#" style={{ fontSize: 13, color: "#4a7c4e", fontWeight: 500, textDecoration: "none" }}>お困りですか？</a>
              </div>
            )}

            <button
              type="submit" disabled={loading}
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

// ── Shared form field ──────────────────────────────────────────────────────

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
        {icon === "folder" && <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>}
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
