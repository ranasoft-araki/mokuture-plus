"use client";

import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkSectionTitle } from "@/components/AdminShell";

export default function AdminSettingsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  return (
    <AdminShell
      active="settings"
      title="基本設定"
      breadcrumb="ホーム / 設定 / 基本情報"
      subtitle="キオスク画面のブランディング・歓迎メッセージ・タイムアウト"
      actions={
        <>
          <MkBtn variant="ghost" size="sm">変更をキャンセル</MkBtn>
          <MkBtn variant="primary" size="sm">保存</MkBtn>
        </>
      }
    >
      <div className="adm-grid-main" style={{ gap: 20 }}>
        {/* Form */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <MkCard>
            <MkSectionTitle title="ブランディング" subtitle="キオスク画面・管理画面共通" />
            <div className="adm-grid-2" style={{ gap: 16 }}>
              <Field label="テナント名" required>
                <TextInput value={tenant} />
              </Field>
              <Field label="テナント ID">
                <TextInput value={tenant} mono />
              </Field>
              <div style={{ gridColumn: "span 2" }}>
                <Field label="企業ロゴ" hint="PNG / SVG · 透明背景推奨 · 512×512以上">
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <div style={{ width: 72, height: 72, borderRadius: 7, background: "#f4f1ea", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center", color: "#a8a198", fontFamily: "monospace", fontSize: 9 }}>[ logo ]</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: "#2d2a24", fontWeight: 500 }}>ロゴ未設定</div>
                      <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", marginTop: 3 }}>PNG / SVG 推奨</div>
                    </div>
                    <MkBtn size="sm" variant="default">アップロード</MkBtn>
                  </div>
                </Field>
              </div>
              <Field label="テーマカラー" hint="キオスクUIのアクセントカラー">
                <div style={{ display: "flex", gap: 8 }}>
                  {["#4a7c4e", "#2d2a24", "#b8763a", "#2e6b8e", "#a84238"].map((c, i) => (
                    <div key={c} style={{ width: 34, height: 34, borderRadius: 7, background: c, cursor: "pointer", border: i === 0 ? "2.5px solid #fffefb" : "1px solid #efece5", boxShadow: i === 0 ? `0 0 0 2px ${c}` : "none" }} />
                  ))}
                  <div style={{ width: 34, height: 34, borderRadius: 7, background: "#fffefb", border: "1px dashed #d8d3c7", display: "flex", alignItems: "center", justifyContent: "center", color: "#a8a198", cursor: "pointer" }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
                  </div>
                </div>
              </Field>
              <Field label="フォント">
                <TextInput value="Noto Sans JP / Inter" suffix={
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round"><path d="M6 9l6 6 6-6"/></svg>
                } />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle title="キオスク画面の文言" subtitle="受付トップ・完了・案内テキスト" />
            <div style={{ display: "grid", gap: 16 }}>
              <Field label="受付トップ メインメッセージ">
                <TextInput value={`ようこそ、${tenant}へ`} />
              </Field>
              <Field label="歓迎メッセージ" hint="{name} は Google カレンダー連携で自動挿入されます">
                <TextInput value="{name} 様、お待ちしておりました" />
              </Field>
              <Field label="呼び出し中メッセージ">
                <TextInput value="担当者をお呼びしています。少々お待ちください。" />
              </Field>
              <Field label="会議室・目的地案内" hint="完了画面の下部に表示">
                <TextInput value="担当者がご案内します" />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle title="タイムアウト" />
            <div className="adm-grid-2" style={{ gap: 16 }}>
              <Field label="受付画面の無操作タイムアウト" hint="30 〜 120 秒">
                <TextInput value="60" mono suffix={<span style={{ color: "#a8a198", fontSize: 12 }}>秒</span>} />
              </Field>
              <Field label="完了画面の表示時間">
                <TextInput value="60" mono suffix={<span style={{ color: "#a8a198", fontSize: 12 }}>秒</span>} />
              </Field>
            </div>
          </MkCard>
        </div>

        {/* Live preview */}
        <div style={{ position: "sticky", top: 0 }}>
          <MkCard>
            <MkSectionTitle title="プレビュー" subtitle="キオスク受付完了画面" />
            <div style={{
              aspectRatio: "9/16", background: "#fffefb", borderRadius: 7,
              border: "1px solid #efece5", overflow: "hidden",
              display: "flex", flexDirection: "column", padding: 22, position: "relative",
            }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/><path d="M12 4v10"/>
                </svg>
              </div>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", textAlign: "center" }}>
                <div style={{ width: 60, height: 60, borderRadius: "50%", background: "#eaf0e8", color: "#4a7c4e", margin: "0 auto 20px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 6"/></svg>
                </div>
                <div style={{ fontSize: 22, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.4px", lineHeight: 1.3 }}>
                  佐々木 様、<br/>お待ちしておりました
                </div>
                <div style={{ fontSize: 13, color: "#6b6559", marginTop: 14 }}>
                  担当者をお呼びしています
                </div>
                <div style={{ display: "flex", justifyContent: "center", gap: 5, marginTop: 14 }}>
                  {[0, 1, 2].map((i) => (
                    <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#4a7c4e", opacity: i === 1 ? 1 : 0.3 }} />
                  ))}
                </div>
              </div>
              <div style={{ padding: 14, background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e" }}>
                <div style={{ fontSize: 10, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase" }}>NEXT</div>
                <div style={{ fontSize: 13, color: "#2d2a24", fontWeight: 500, marginTop: 4, lineHeight: 1.4 }}>
                  担当者がご案内します
                </div>
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

function TextInput({ value, placeholder, mono, suffix }: { value?: string; placeholder?: string; mono?: boolean; suffix?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        defaultValue={value}
        placeholder={placeholder}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: mono ? "monospace" : undefined, height: "100%" }}
      />
      {suffix}
    </div>
  );
}
