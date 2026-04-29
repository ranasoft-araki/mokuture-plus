"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, monospace';

export default function PartnerPortalPage() {
  const router = useRouter();
  const [resellerId, setResellerId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const tokens = await api.resellerLogin(resellerId, password);
      saveTokens(tokens.access_token, tokens.refresh_token, tokens.role);
      if (tokens.role === "reseller") {
        router.push(`/${tokens.tenant_slug}/reseller`);
      } else {
        router.push("/partner-portal");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ width: "100vw", height: "100vh", overflow: "hidden", fontFamily: FONT_UI, background: "#faf8f4", display: "flex" }}>
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
          <div style={{ fontSize: 11, letterSpacing: 3, color: "#c8a96e", textTransform: "uppercase" as const, fontWeight: 700, marginBottom: 18 }}>FOR AUTHORIZED PARTNERS</div>
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

      <div style={{ width: 480, padding: 64, display: "flex", flexDirection: "column", justifyContent: "center", background: "#fffefb" }}>
        <div style={{ maxWidth: 360, width: "100%", alignSelf: "center" }}>
          <div style={{ fontSize: 32, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.6px", marginBottom: 8, fontFamily: FONT_JP }}>代理店ログイン</div>
          <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.6, marginBottom: 32 }}>代理店IDとパスワードを入力してください</div>

          {error && (
            <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#dc2626" }}>
              {error}
            </div>
          )}

          <form onSubmit={submit}>
            <LightField label="代理店ID" type="text" value={resellerId} onChange={setResellerId} hint="例：asahi-1042" icon="folder" />
            <LightField label="パスワード" type="password" value={password} onChange={setPassword} icon="lock" />

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4, marginBottom: 24 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b6559", cursor: "pointer" }}>
                <span style={{ width: 16, height: 16, borderRadius: 4, border: "1.5px solid #d8d3c7", background: "#fffefb", display: "block" }} />
                このデバイスを30日間記憶
              </label>
              <a href="#" style={{ fontSize: 13, color: "#c8a96e", fontWeight: 500, textDecoration: "none" }}>お困りの方</a>
            </div>

            <button
              type="submit"
              disabled={loading}
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
        {icon === "folder" && <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>}
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 14, color: "#1d1a15", fontFamily: type === "password" ? FONT_MONO : FONT_UI, letterSpacing: type === "password" ? 2 : 0 }}
          onFocus={(e) => {
            const wrapper = e.currentTarget.closest("div") as HTMLDivElement;
            if (wrapper) { wrapper.style.borderColor = "#c8a96e"; wrapper.style.boxShadow = "0 0 0 3px rgba(200,169,110,0.12)"; }
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
