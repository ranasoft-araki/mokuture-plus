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

  // Kiosk message state
  const [kioskWelcome, setKioskWelcome] = useState("ようこそ");
  const [kioskSub, setKioskSub] = useState("ご用件をお選びください");
  const [kioskCalling, setKioskCalling] = useState("担当者をお呼びしています。少々お待ちください。");
  const [kioskComplete, setKioskComplete] = useState("担当者がご案内します");
  const [kioskIdleTimeout, setKioskIdleTimeout] = useState("60");
  const [kioskCompleteTimeout, setKioskCompleteTimeout] = useState("10");

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token).then((s) => {
      setSettings(s);
      setBrandColor(s.brand_color);
      setFont(s.font);
      setLogoUrl(s.logo_url);
      setKioskWelcome(s.kiosk_welcome_message ?? "ようこそ");
      setKioskSub(s.kiosk_sub_message ?? "ご用件をお選びください");
      setKioskCalling(s.kiosk_calling_message ?? "担当者をお呼びしています。少々お待ちください。");
      setKioskComplete(s.kiosk_complete_message ?? "担当者がご案内します");
      setKioskIdleTimeout(String(s.kiosk_idle_timeout_sec ?? 60));
      setKioskCompleteTimeout(String(s.kiosk_complete_timeout_sec ?? 10));
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
      await api.updateTenantSettings(token, {
        brand_color: brandColor,
        font,
        kiosk_welcome_message: kioskWelcome,
        kiosk_sub_message: kioskSub,
        kiosk_calling_message: kioskCalling,
        kiosk_complete_message: kioskComplete,
        kiosk_idle_timeout_sec: Number(kioskIdleTimeout) || 60,
        kiosk_complete_timeout_sec: Number(kioskCompleteTimeout) || 10,
      });
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
    setKioskWelcome(settings.kiosk_welcome_message ?? "ようこそ");
    setKioskSub(settings.kiosk_sub_message ?? "ご用件をお選びください");
    setKioskCalling(settings.kiosk_calling_message ?? "担当者をお呼びしています。少々お待ちください。");
    setKioskComplete(settings.kiosk_complete_message ?? "担当者がご案内します");
    setKioskIdleTimeout(String(settings.kiosk_idle_timeout_sec ?? 60));
    setKioskCompleteTimeout(String(settings.kiosk_complete_timeout_sec ?? 10));
    setError(null);
  };

  return (
    <AdminShell
      active="settings"
      title="基本設定"
      breadcrumb="ホーム / 設定 / 基本情報"
      subtitle="キオスク画面のブランディング・歓迎メッセージ・タイムアウト"
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
      <div className="adm-grid-main" style={{ gap: 20 }}>
        {/* Form */}
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

          <MkCard>
            <MkSectionTitle title="キオスク画面の文言" subtitle="変更後「保存」ボタンで反映されます" />
            <div style={{ display: "grid", gap: 16 }}>
              <Field label="受付トップ メインメッセージ">
                <TextInput value={kioskWelcome} onChange={setKioskWelcome} placeholder="ようこそ" />
              </Field>
              <Field label="受付トップ サブメッセージ">
                <TextInput value={kioskSub} onChange={setKioskSub} placeholder="ご用件をお選びください" />
              </Field>
              <Field label="呼び出し中メッセージ">
                <TextInput value={kioskCalling} onChange={setKioskCalling} placeholder="担当者をお呼びしています。少々お待ちください。" />
              </Field>
              <Field label="完了画面メッセージ" hint="完了画面の下部に表示">
                <TextInput value={kioskComplete} onChange={setKioskComplete} placeholder="担当者がご案内します" />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle title="タイムアウト" subtitle="秒数を変更して保存してください" />
            <div className="adm-grid-2" style={{ gap: 16 }}>
              <Field label="受付画面の無操作タイムアウト" hint="10 〜 300 秒">
                <TextInputWithSuffix
                  value={kioskIdleTimeout}
                  onChange={setKioskIdleTimeout}
                  mono
                  suffix={<span style={{ color: "#a8a198", fontSize: 12 }}>秒</span>}
                />
              </Field>
              <Field label="完了画面の表示時間" hint="5 〜 60 秒">
                <TextInputWithSuffix
                  value={kioskCompleteTimeout}
                  onChange={setKioskCompleteTimeout}
                  mono
                  suffix={<span style={{ color: "#a8a198", fontSize: 12 }}>秒</span>}
                />
              </Field>
            </div>
          </MkCard>
        </div>

        {/* Live preview */}
        <div style={{ position: "sticky", top: 0 }}>
          <MkCard>
            <MkSectionTitle title="プレビュー" subtitle="キオスク受付トップ画面" />
            <div style={{
              aspectRatio: "9/16", background: "#faf8f4", borderRadius: 7,
              border: "1px solid #efece5", overflow: "hidden",
              display: "flex", flexDirection: "column", padding: 18, gap: 10,
            }}>
              {/* Header */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 28, height: 28, borderRadius: 6, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  {(logoPreview ?? logoUrl) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={logoPreview ?? logoUrl!} alt="logo" style={{ width: 22, height: 22, objectFit: "contain" }} />
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/>
                    </svg>
                  )}
                </div>
                <div style={{ fontSize: 8, color: "#a8a198", letterSpacing: 2, textTransform: "uppercase", fontFamily: "Inter, system-ui, sans-serif" }}>RECEPTION</div>
              </div>

              {/* Welcome heading */}
              <div style={{ paddingTop: 4 }}>
                <div style={{ fontSize: 26, fontWeight: 700, color: "#1d1a15", letterSpacing: -0.8, lineHeight: 1.1 }}>
                  {kioskWelcome || "ようこそ"}
                </div>
                <div style={{ fontSize: 11, color: "#6b6559", marginTop: 4 }}>
                  {kioskSub || "ご用件をお選びください"}
                </div>
              </div>

              {/* Tile grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, flex: 1, minHeight: 0 }}>
                {[
                  { label: "ご訪問", primary: true },
                  { label: "QR 受付", primary: false },
                  { label: "配送・宅配", primary: false },
                  { label: "その他", primary: false },
                ].map((t, i) => (
                  <div key={i} style={{
                    background: t.primary ? "#1d1a15" : "#fffefb",
                    border: `1px solid ${t.primary ? "#1d1a15" : "#efece5"}`,
                    borderRadius: 9, padding: "8px 10px",
                    display: "flex", alignItems: "flex-end",
                    minHeight: 0,
                  }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color: t.primary ? "#ffffff" : "#2d2a24" }}>{t.label}</span>
                  </div>
                ))}
              </div>

              {/* Calling / Complete message references */}
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ background: "#fffefb", border: "1px solid #efece5", borderRadius: 6, padding: "6px 10px" }}>
                  <div style={{ fontSize: 8, color: "#a8a198", letterSpacing: 1, textTransform: "uppercase", marginBottom: 2 }}>CALLING</div>
                  <div style={{ fontSize: 10, color: "#2d2a24", fontWeight: 500, lineHeight: 1.3 }}>
                    {kioskCalling || "担当者をお呼びしています"}
                  </div>
                </div>
                <div style={{ background: "#1d1a15", borderRadius: 6, padding: "6px 10px" }}>
                  <div style={{ fontSize: 8, color: "rgba(255,255,255,0.4)", letterSpacing: 1, textTransform: "uppercase", marginBottom: 2 }}>COMPLETE</div>
                  <div style={{ fontSize: 10, color: "#ffffff", fontWeight: 500, lineHeight: 1.3 }}>
                    {kioskComplete || "担当者がご案内します"}
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div style={{ fontSize: 8, color: "#a8a198", textAlign: "right", fontFamily: "monospace" }}>
                {kioskIdleTimeout || "60"}秒で待機画面へ
              </div>
            </div>
          </MkCard>
        </div>
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

function TextInputWithSuffix({ value, placeholder, mono, suffix, onChange }: { value?: string; placeholder?: string; mono?: boolean; suffix?: React.ReactNode; onChange?: (v: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        value={value ?? ""}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        type="number"
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: mono ? "monospace" : undefined, height: "100%" }}
      />
      {suffix}
    </div>
  );
}
