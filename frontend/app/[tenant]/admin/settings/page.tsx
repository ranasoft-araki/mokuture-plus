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

  const [pwOpen, setPwOpen] = useState(false);
  const [pwCurrent, setPwCurrent] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwConfirm, setPwConfirm] = useState("");
  const [pwSaving, setPwSaving] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState(false);

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

  const handleLogoDelete = async () => {
    const token = getAccessToken();
    if (!token) return;
    setUploading(true);
    setError(null);
    try {
      const updated = await api.deleteLogo(token);
      setLogoUrl(updated.logo_url);
      setLogoPreview(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "ロゴの削除に失敗しました");
    } finally {
      setUploading(false);
    }
  };

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

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pwNew !== pwConfirm) {
      setPwError("新しいパスワードと確認用パスワードが一致しません");
      return;
    }
    if (pwNew.length < 8) {
      setPwError("新しいパスワードは8文字以上にしてください");
      return;
    }
    const token = getAccessToken();
    if (!token) return;
    setPwSaving(true);
    setPwError(null);
    try {
      await api.changePassword(token, pwCurrent, pwNew);
      setPwSuccess(true);
      setPwCurrent("");
      setPwNew("");
      setPwConfirm("");
      setTimeout(() => setPwSuccess(false), 3000);
    } catch (err: unknown) {
      setPwError(err instanceof Error ? err.message : "パスワードの変更に失敗しました");
    } finally {
      setPwSaving(false);
    }
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
                      {uploading ? "処理中..." : "アップロード"}
                    </MkBtn>
                    {(logoPreview ?? logoUrl) && (
                      <MkBtn size="sm" variant="ghost" onClick={handleLogoDelete} disabled={uploading}>
                        削除
                      </MkBtn>
                    )}
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
            <div
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", userSelect: "none" }}
              onClick={() => { setPwOpen((v) => !v); setPwError(null); setPwSuccess(false); }}
            >
              <MkSectionTitle title="パスワード変更" subtitle="ログインパスワードを変更します" />
              <span style={{ fontSize: 12, color: "#a8a198", marginLeft: 12 }}>{pwOpen ? "▲" : "▼"}</span>
            </div>
            {pwOpen && (
              <form onSubmit={handlePasswordChange} style={{ marginTop: 16 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <Field label="現在のパスワード">
                    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                      <input
                        type="password"
                        required
                        value={pwCurrent}
                        onChange={(e) => setPwCurrent(e.target.value)}
                        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
                      />
                    </div>
                  </Field>
                  <Field label="新しいパスワード" hint="8文字以上">
                    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                      <input
                        type="password"
                        required
                        minLength={8}
                        value={pwNew}
                        onChange={(e) => setPwNew(e.target.value)}
                        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
                      />
                    </div>
                  </Field>
                  <Field label="確認用パスワード">
                    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
                      <input
                        type="password"
                        required
                        value={pwConfirm}
                        onChange={(e) => setPwConfirm(e.target.value)}
                        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
                      />
                    </div>
                  </Field>
                </div>
                {pwError && (
                  <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "10px 14px", fontSize: 12.5, color: "#a84238", marginTop: 12 }}>
                    {pwError}
                  </div>
                )}
                {pwSuccess && (
                  <div style={{ background: "#f1f8f2", border: "1px solid #b5d9b8", borderRadius: 7, padding: "10px 14px", fontSize: 12.5, color: "#2d6a32", marginTop: 12 }}>
                    パスワードを変更しました
                  </div>
                )}
                <div style={{ marginTop: 16 }}>
                  <MkBtn type="submit" variant="primary" size="sm" disabled={pwSaving}>
                    {pwSaving ? "変更中..." : "パスワードを変更"}
                  </MkBtn>
                </div>
              </form>
            )}
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

