"use client";

import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";

export default function AdminNotifyPage() {
  return (
    <AdminShell
      active="notify"
      title="通知設定"
      breadcrumb="ホーム / 設定 / 通知"
      subtitle="Slack · Chatwork · PWA プッシュ通知の連携と受信者管理"
      actions={<MkBtn variant="default" size="sm">テスト通知を送信</MkBtn>}
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Slack */}
        <MkCard>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#eaf0e8", color: "#3a6240", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4" y="10" width="12" height="4" rx="2"/><rect x="10" y="4" width="4" height="12" rx="2"/>
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>Slack</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>Incoming Webhook で指定チャンネルへ通知</div>
            </div>
            <MkPill tone="off">未設定</MkPill>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Webhook URL" required>
              <TextInput placeholder="https://hooks.slack.com/services/..." mono />
            </Field>
            <Field label="通知先チャンネル">
              <TextInput placeholder="#reception-alerts" mono />
            </Field>
            <Field label="通知テンプレート" hint="{name} {company} {purpose} {time} が利用可能">
              <div style={{ border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: 10, fontSize: 12, color: "#2d2a24", lineHeight: 1.55 }}>
                来客があります：<b>{"{company}"}</b> {"{name}"} 様（用件：{"{purpose}"}）{"{time}"}
              </div>
            </Field>
          </div>
          <div style={{ marginTop: 16 }}>
            <MkBtn variant="primary" size="sm">保存</MkBtn>
          </div>
        </MkCard>

        {/* Chatwork */}
        <MkCard>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#e4eef5", color: "#2e6b8e", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 15, flexShrink: 0 }}>
              CW
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>Chatwork</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>API トークン + ルーム ID で通知</div>
            </div>
            <MkPill tone="off">未設定</MkPill>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="API トークン" required>
              <TextInput placeholder="Chatwork API トークン" mono />
            </Field>
            <Field label="通知先ルーム ID" required>
              <TextInput placeholder="例: 312648719" mono />
            </Field>
            <Field label="通知対象">
              <div style={{ display: "flex", gap: 8 }}>
                {["受付完了", "呼び出し中", "タイムアウト"].map((l, i) => (
                  <label key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", border: "1px solid #d8d3c7", background: "#fffefb", borderRadius: 5, fontSize: 11.5, color: "#6b6559", cursor: "pointer" }}>
                    <span style={{ width: 14, height: 14, borderRadius: 3, border: "1.5px solid #d8d3c7", background: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center" }} />
                    {l}
                  </label>
                ))}
              </div>
            </Field>
          </div>
          <div style={{ marginTop: 16 }}>
            <MkBtn variant="primary" size="sm">保存</MkBtn>
          </div>
        </MkCard>

        {/* PWA Push */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <MkSectionTitle
            title="PWA プッシュ通知"
            subtitle="担当者スマホに Web Push API (VAPID) で通知を配信"
            action={
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <MkPill tone="off">VAPID 鍵 未設定</MkPill>
                <MkBtn size="sm" variant="default">インストール QR</MkBtn>
              </div>
            }
          />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            <div>
              <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 }}>登録済み担当者端末</div>
              <div style={{ padding: "32px 0", textAlign: "center", color: "#a8a198", fontSize: 12 }}>
                端末が登録されていません。<br/>
                スマートフォンでキオスク管理URLにアクセスしてインストールしてください。
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 }}>通知プレビュー</div>
              <div style={{ background: "#f4f1ea", borderRadius: 10, padding: 16, border: "1px solid #efece5" }}>
                <div style={{ background: "rgba(255,255,255,0.8)", border: "1px solid #efece5", borderRadius: 10, padding: 14, boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                    <div style={{ width: 24, height: 24, borderRadius: 6, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700 }}>M+</div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#2d2a24", letterSpacing: "0.2px" }}>MOKUTURE+</div>
                    <div style={{ flex: 1 }} />
                    <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace" }}>今</div>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15" }}>来客のお知らせ</div>
                  <div style={{ fontSize: 12, color: "#2d2a24", marginTop: 3, lineHeight: 1.5 }}>
                    来訪者様が受付を完了しました。
                  </div>
                </div>
                <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 12, textAlign: "center" }}>
                  ロック画面・バックグラウンドでも受信可能
                </div>
              </div>
            </div>
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

function TextInput({ placeholder, mono }: { placeholder?: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        placeholder={placeholder}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: mono ? "monospace" : undefined, height: "100%" }}
      />
    </div>
  );
}
