"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkSectionTitle } from "@/components/AdminShell";
import { api, TenantSettings } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const THEME_COLORS = ["#4a7c4e", "#2d2a24", "#b8763a", "#2e6b8e", "#a84238"];
const FONTS = ["Noto Sans JP / Inter", "Noto Serif JP / Georgia", "BIZ UDPGothic / System"];

export default function AdminSettingsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [brandColor, setBrandColor] = useState("#4a7c4e");
  const [font, setFont] = useState("Noto Sans JP / Inter");
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token).then((s) => {
      setSettings(s);
      setBrandColor(s.brand_color);
      setFont(s.font);
      setLogoUrl(s.logo_url);
    }).catch(() => {});
  }, []);

  const handleLogoClick = () => fileInputRef.current?.click();

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const token = getAccessToken();
    if (!token) return;
    setUploading(true);
    setError(null);
    try {
      const { upload_url, public_url } = await api.getLogoUploadUrl(token, file.name, file.type);
      const putRes = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
      });
      if (!putRes.ok) throw new Error(`アップロード失敗 (${putRes.status})`);
      const updated = await api.confirmLogoUpload(token, public_url);
      setLogoUrl(updated.logo_url);
      setLogoPreview(URL.createObjectURL(file));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "ロゴのアップロードに失敗しました");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleSave = async () => {
    const token = getAccessToken();
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateTenantSettings(token, { brand_color: brandColor, font });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!settings) return;
    setBrandColor(settings.brand_color);
    setFont(settings.font);
    setLogoUrl(settings.logo_url);
    setLogoPreview(null);
    setError(null);
  };

  return (
    <AdminShell
      active="settings"
      title="基本設定"
      breadcrumb="ホーム / 設定 / 基本情報"
      subtitle="ロゴ・テーマカラー・フォントなどブランディング設定"
      actions={
        <>
          <MkBtn variant="ghost" size="sm" onClick={handleCancel}>変更をキャンセル</MkBtn>
          <MkBtn variant="primary" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : saved ? "保存しました" : "保存"}
          </MkBtn>
        </>
      }
    >
      {error && (
        <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "10px 14px", fontSize: 12.5, color: "#a84238", marginBottom: 12 }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <MkCard>
            <MkSectionTitle title="ブランディング" subtitle="キオスク画面・管理画面共通" />
            <div className="adm-grid-2" style={{ gap: 16 }}>
              <Field label="テナント名" required>
                <TextInput value={settings?.tenant_name ?? tenant} readOnly />
              </Field>
              <Field label="テナント ID">
                <TextInput value={settings?.tenant_slug ?? tenant} readOnly mono />
              </Field>
              <div style={{ gridColumn: "span 2" }}>
                <Field label="企業ロゴ" hint="PNG / SVG · 透明背景推奨 · 512×512以上">
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <div style={{ width: 72, height: 72, borderRadius: 7, background: "#f4f1ea", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                      {(logoPreview ?? logoUrl) ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={logoPreview ?? logoUrl!} alt="logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
                      ) : (
                        <span style={{ color: "#a8a198", fontFamily: "monospace", fontSize: 9 }}>[ logo ]</span>
                      )}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: "#2d2a24", fontWeight: 500 }}>
                        {(logoPreview ?? logoUrl) ? "ロゴ設定済み" : "ロゴ未設定"}
                      </div>
                      <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", marginTop: 3 }}>PNG / SVG 推奨</div>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg,image/svg+xml"
                      style={{ display: "none" }}
                      onChange={handleFileChange}
                    />
                    <MkBtn size="sm" variant="default" onClick={handleLogoClick} disabled={uploading}>
                      {uploading ? "アップロード中..." : "アップロード"}
                    </MkBtn>
                  </div>
                </Field>
              </div>
              <Field label="テーマカラー" hint="キオスクUIのアクセントカラー">
                <div style={{ display: "flex", gap: 8 }}>
                  {THEME_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setBrandColor(c)}
                      style={{
                        width: 34, height: 34, borderRadius: 7, background: c, cursor: "pointer",
                        border: brandColor === c ? "2.5px solid #fffefb" : "1px solid #efece5",
                        boxShadow: brandColor === c ? `0 0 0 2px ${c}` : "none",
                        padding: 0,
                      }}
                    />
                  ))}
                </div>
              </Field>
              <Field label="フォント">
                <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                  <select
                    value={font}
                    onChange={(e) => setFont(e.target.value)}
                    style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%", cursor: "pointer" }}
                  >
                    {FONTS.map((f) => (
                      <option key={f} value={f}>{f}</option>
                    ))}
                  </select>
                </div>
              </Field>
            </div>
          </MkCard>
      </div>
    </AdminShell>
  );
}

function Field({ label, hint, children, required }: { label: string; hint?: string; children: React.ReactNode; required?: boolean }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
        {label}
        {required && <span style={{ color: "#a84238", fontSize: 10 }}>必須</span>}
      </div>
      {children}
      {hint && <div style={{ fontSize: 11, color: "#a8a198", marginTop: 5 }}>{hint}</div>}
    </label>
  );
}

function TextInput({ value, placeholder, mono, readOnly, onChange }: { value?: string; placeholder?: string; mono?: boolean; readOnly?: boolean; onChange?: (v: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: readOnly ? "#f8f6f2" : "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        value={value ?? ""}
        placeholder={placeholder}
        readOnly={readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: readOnly ? "#a8a198" : "#2d2a24", fontFamily: mono ? "monospace" : undefined, height: "100%", cursor: readOnly ? "default" : undefined }}
      />
    </div>
  );
}

