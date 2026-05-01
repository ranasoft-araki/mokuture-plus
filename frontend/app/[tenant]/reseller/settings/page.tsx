"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, type TenantSettings } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';
const ACCENT = "#c8a96e";
const BG = "#fffefb";
const TEXT = "#1d1a15";

const cardStyle: React.CSSProperties = {
  background: BG,
  border: "1px solid #efece5",
  borderRadius: 12,
  padding: "22px 26px",
  marginBottom: 20,
};

const labelStyle: React.CSSProperties = {
  fontSize: 11.5,
  color: "#a8a198",
  fontFamily: FONT_JP,
  marginBottom: 5,
  display: "block",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  border: "1px solid #e2ddd6",
  borderRadius: 7,
  fontSize: 13,
  fontFamily: FONT_JP,
  color: TEXT,
  background: BG,
  outline: "none",
  boxSizing: "border-box",
};

const btnPrimary: React.CSSProperties = {
  padding: "9px 18px",
  background: ACCENT,
  color: BG,
  border: "none",
  borderRadius: 7,
  fontSize: 13,
  fontFamily: FONT_JP,
  cursor: "pointer",
};

const btnDisabled: React.CSSProperties = {
  ...btnPrimary,
  opacity: 0.6,
  cursor: "not-allowed",
};

export default function ResellerSettingsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Section 1: Tenant basic info
  const [tenantName, setTenantName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSuccess, setNameSuccess] = useState(false);

  // Section 2: Brand color
  const [brandColor, setBrandColor] = useState("#c8a96e");
  const [colorSaving, setColorSaving] = useState(false);
  const [colorError, setColorError] = useState<string | null>(null);
  const [colorSuccess, setColorSuccess] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token)
      .then((s) => {
        setSettings(s);
        setTenantName(s.tenant_name);
        setBrandColor(s.brand_color || "#c8a96e");
      })
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleSaveName() {
    const token = getAccessToken();
    if (!token) return;
    setNameSaving(true);
    setNameError(null);
    setNameSuccess(false);
    try {
      const updated = await api.updateTenantSettings(token, { name: tenantName });
      setSettings(updated);
      setTenantName(updated.tenant_name);
      setNameSuccess(true);
      setTimeout(() => setNameSuccess(false), 2500);
    } catch (e: unknown) {
      setNameError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setNameSaving(false);
    }
  }

  async function handleSaveColor() {
    const token = getAccessToken();
    if (!token) return;
    setColorSaving(true);
    setColorError(null);
    setColorSuccess(false);
    try {
      const updated = await api.updateTenantSettings(token, { brand_color: brandColor });
      setSettings(updated);
      setBrandColor(updated.brand_color);
      setColorSuccess(true);
      setTimeout(() => setColorSuccess(false), 2500);
    } catch (e: unknown) {
      setColorError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setColorSaving(false);
    }
  }

  return (
    <div style={{ padding: "28px 32px", maxWidth: 640, fontFamily: FONT_JP }}>
        {loading && (
          <div style={{ color: "#a8a198", fontSize: 13, fontFamily: FONT_JP }}>読み込み中…</div>
        )}
        {loadError && (
          <div style={{ marginBottom: 16, padding: "10px 14px", background: "#f6e0dc", borderRadius: 8, color: "#a84238", fontSize: 13, fontFamily: FONT_JP }}>
            {loadError}
          </div>
        )}

        {!loading && settings && (
          <>
            {/* Section 1: Tenant basic info */}
            <div style={cardStyle}>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: TEXT, fontFamily: FONT_JP, marginBottom: 18, paddingBottom: 12, borderBottom: "1px solid #efece5" }}>
                テナント基本情報
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div>
                  <label style={labelStyle}>テナント名</label>
                  <input
                    type="text"
                    value={tenantName}
                    onChange={(e) => setTenantName(e.target.value)}
                    placeholder="テナント名を入力"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>スラッグ（URL識別子）</label>
                  <div style={{
                    padding: "9px 12px",
                    background: "#f4f1ea",
                    border: "1px solid #e2ddd6",
                    borderRadius: 7,
                    fontSize: 13,
                    fontFamily: FONT_MONO,
                    color: "#6b6559",
                    userSelect: "none",
                  }}>
                    {settings.tenant_slug ?? tenant}
                  </div>
                  <div style={{ fontSize: 11, color: "#b0a898", fontFamily: FONT_JP, marginTop: 4 }}>
                    スラッグはURLに使用され、変更できません。
                  </div>
                </div>

                {nameError && (
                  <div style={{ padding: "8px 12px", background: "#f6e0dc", borderRadius: 7, color: "#a84238", fontSize: 12.5, fontFamily: FONT_JP }}>
                    {nameError}
                  </div>
                )}
                {nameSuccess && (
                  <div style={{ padding: "8px 12px", background: "#f0ebe0", borderRadius: 7, color: "#7a5a1e", fontSize: 12.5, fontFamily: FONT_JP }}>
                    保存しました
                  </div>
                )}

                <div>
                  <button
                    onClick={handleSaveName}
                    disabled={nameSaving || !tenantName.trim()}
                    style={nameSaving || !tenantName.trim() ? btnDisabled : btnPrimary}
                  >
                    {nameSaving ? "保存中…" : "保存"}
                  </button>
                </div>
              </div>
            </div>

            {/* Section 2: Brand color */}
            <div style={cardStyle}>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: TEXT, fontFamily: FONT_JP, marginBottom: 18, paddingBottom: 12, borderBottom: "1px solid #efece5" }}>
                ブランドカラー
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div>
                  <label style={labelStyle}>テーマカラー</label>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <input
                      type="color"
                      value={brandColor}
                      onChange={(e) => setBrandColor(e.target.value)}
                      style={{
                        width: 48,
                        height: 40,
                        border: "1px solid #e2ddd6",
                        borderRadius: 7,
                        cursor: "pointer",
                        padding: 2,
                        background: "transparent",
                      }}
                    />
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "9px 12px",
                      border: "1px solid #e2ddd6",
                      borderRadius: 7,
                      background: BG,
                      minWidth: 120,
                    }}>
                      <div style={{
                        width: 16,
                        height: 16,
                        borderRadius: 4,
                        background: brandColor,
                        border: "1px solid #e2ddd6",
                        flexShrink: 0,
                      }} />
                      <span style={{ fontSize: 13, fontFamily: FONT_MONO, color: TEXT, letterSpacing: 1 }}>
                        {brandColor.toUpperCase()}
                      </span>
                    </div>
                  </div>
                </div>

                {colorError && (
                  <div style={{ padding: "8px 12px", background: "#f6e0dc", borderRadius: 7, color: "#a84238", fontSize: 12.5, fontFamily: FONT_JP }}>
                    {colorError}
                  </div>
                )}
                {colorSuccess && (
                  <div style={{ padding: "8px 12px", background: "#f0ebe0", borderRadius: 7, color: "#7a5a1e", fontSize: 12.5, fontFamily: FONT_JP }}>
                    保存しました
                  </div>
                )}

                <div>
                  <button
                    onClick={handleSaveColor}
                    disabled={colorSaving}
                    style={colorSaving ? btnDisabled : btnPrimary}
                  >
                    {colorSaving ? "保存中…" : "保存"}
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
  );
}
