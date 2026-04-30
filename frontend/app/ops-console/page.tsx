"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, monospace';

export default function OpsConsolePage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const tokens = await api.operatorLogin(email, password);
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role, true);
      if (tokens.role === "operator") {
        router.push("/operator");
      } else {
        router.push("/ops-console");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      width: "100vw", height: "100vh", overflow: "hidden",
      fontFamily: FONT_UI, background: "#0e0c08",
      display: "flex", alignItems: "center", justifyContent: "center",
      position: "relative",
    }}>
      <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 0.04, pointerEvents: "none" }}>
        <defs>
          <pattern id="op-grid" x="0" y="0" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M48 0H0v48" fill="none" stroke="#fff" strokeWidth="0.5"/>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#op-grid)"/>
      </svg>

      <div style={{ position: "absolute", top: 24, right: 40 }}>
        <span style={{ fontSize: 11, padding: "5px 10px", border: "1px solid rgba(255,255,255,0.18)", borderRadius: 4, color: "rgba(255,255,255,0.55)", letterSpacing: "1.5px", fontFamily: FONT_MONO }}>
          OPS · INTERNAL
        </span>
      </div>

      <div style={{ width: 400, color: "#fffefb", position: "relative" }}>
        <div style={{ width: 56, height: 56, borderRadius: 14, background: "rgba(74,124,78,0.15)", border: "1px solid rgba(74,124,78,0.35)", display: "flex", alignItems: "center", justifyContent: "center", color: "#4a7c4e", marginBottom: 24 }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
        </div>

        <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>サインイン</div>
        <div style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", marginBottom: 32, lineHeight: 1.6 }}>認証情報を入力してください</div>

        {error && (
          <div style={{ background: "rgba(255,80,80,0.12)", border: "1px solid rgba(255,80,80,0.3)", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#ff9090" }}>
            {error}
          </div>
        )}

        <form onSubmit={submit}>
          <DarkField label="メールアドレス" type="email" value={email} onChange={setEmail} />
          <DarkField label="パスワード" type="password" value={password} onChange={setPassword} />

          <button
            type="submit"
            disabled={loading}
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
