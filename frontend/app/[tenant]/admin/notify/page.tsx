"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { requestAndSubscribe, sendSubscriptionToServer, unsubscribeFromPush, getCurrentPushSubscription } from "@/lib/push";
import { getAccessToken } from "@/lib/auth";

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

function TextInput({ placeholder, mono, value, onChange }: { placeholder?: string; mono?: boolean; value?: string; onChange?: (v: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        value={value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: mono ? "monospace" : undefined, height: "100%" }}
      />
    </div>
  );
}

// ── PWA Push Panel ────────────────────────────────────────────────────
function PWAPushPanel({ authToken }: { authToken: string }) {
  const [vapidKey, setVapidKey] = useState<string | null>(null);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [subscriptions, setSubscriptions] = useState<{ id: string; endpoint: string; display_endpoint: string; created_at: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [testSent, setTestSent] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [keyRes, subs, sub] = await Promise.all([
        api.getPushVapidKey(authToken),
        api.listPushSubscriptions(authToken),
        getCurrentPushSubscription(),
      ]);
      setVapidKey(keyRes.public_key);
      setSubscriptions(subs);
      setIsSubscribed(!!sub);
    } catch {
      setError("設定の読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [authToken]);

  useEffect(() => { reload(); }, [reload]);

  const handleSetupVapid = async () => {
    setWorking(true);
    setError("");
    try {
      const res = await api.setupPushVapid(authToken);
      setVapidKey(res.public_key);
    } catch {
      setError("VAPID鍵の生成に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleSubscribe = async () => {
    if (!vapidKey) return;
    setWorking(true);
    setError("");
    try {
      const sub = await requestAndSubscribe(vapidKey);
      if (!sub) { setError("通知の許可が拒否されました。ブラウザの設定を確認してください。"); return; }
      const ok = await sendSubscriptionToServer(authToken, sub);
      if (!ok) { setError("サーバーへの登録に失敗しました"); return; }
      setIsSubscribed(true);
      await reload();
    } catch {
      setError("登録に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleUnsubscribe = async () => {
    setWorking(true);
    setError("");
    try {
      await unsubscribeFromPush(authToken);
      setIsSubscribed(false);
      await reload();
    } catch {
      setError("登録解除に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleTestPush = async () => {
    setWorking(true);
    setError("");
    try {
      await api.testPushNotification(authToken);
      setTestSent(true);
      setTimeout(() => setTestSent(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleDeleteSub = async (endpoint: string) => {
    await api.deletePushSubscription(authToken, endpoint);
    await reload();
  };

  if (loading) {
    return <div style={{ padding: "24px 0", color: "#a8a198", fontSize: 13 }}>読み込み中…</div>;
  }

  return (
    <div className="adm-grid-2" style={{ gap: 20 }}>
      {/* Left: setup + device list */}
      <div>
        {/* VAPID Setup */}
        {!vapidKey ? (
          <div style={{ padding: "20px", background: "#f4f1ea", borderRadius: 10, marginBottom: 16, border: "1px solid #efece5" }}>
            <div style={{ fontSize: 13, color: "#6b6559", marginBottom: 12, lineHeight: 1.55 }}>
              プッシュ通知を有効にするには、まず VAPID 鍵を生成してください。
            </div>
            <MkBtn variant="primary" size="sm" onClick={handleSetupVapid}>
              {working ? "生成中…" : "VAPID 鍵を生成"}
            </MkBtn>
          </div>
        ) : (
          <div style={{ marginBottom: 16, padding: "12px 14px", background: "#eaf0e8", borderRadius: 8, border: "1px solid rgba(74,124,78,0.2)", display: "flex", gap: 10, alignItems: "center" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="2" strokeLinecap="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span style={{ fontSize: 12, color: "#3a6240", fontWeight: 500 }}>VAPID 鍵が設定されています</span>
          </div>
        )}

        {/* Subscribe button */}
        {vapidKey && (
          <div style={{ marginBottom: 16 }}>
            {isSubscribed ? (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500, flex: 1 }}>
                  このデバイスで受信中
                </div>
                <MkBtn variant="ghost" size="sm" onClick={handleUnsubscribe}>
                  このデバイスを解除
                </MkBtn>
              </div>
            ) : (
              <MkBtn variant="primary" size="sm" onClick={handleSubscribe}>
                {working ? "設定中…" : "このデバイスで通知を受け取る"}
              </MkBtn>
            )}
          </div>
        )}

        {/* Subscription list */}
        <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 }}>
          登録済み端末（{subscriptions.length}）
        </div>
        {subscriptions.length === 0 ? (
          <div style={{ padding: "20px 0", textAlign: "center", color: "#a8a198", fontSize: 12 }}>
            端末が登録されていません。<br />
            上のボタンで登録してください。
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {subscriptions.map((s, i) => (
              <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0", borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#f4f1ea", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6b6559" strokeWidth="1.8" strokeLinecap="round"><rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="17" r="1"/></svg>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11.5, color: "#2d2a24", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.display_endpoint}</div>
                  <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2 }}>{new Date(s.created_at).toLocaleString("ja-JP")}</div>
                </div>
                <button
                  onClick={() => handleDeleteSub(s.endpoint)}
                  style={{ background: "none", border: "none", color: "#a8a198", cursor: "pointer", padding: 4, borderRadius: 4 }}
                  title="削除"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, padding: "10px 14px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 8, color: "#a84238", fontSize: 12 }}>
            {error}
          </div>
        )}
      </div>

      {/* Right: notification preview */}
      <div>
        <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 }}>通知プレビュー</div>
        <div style={{ background: "#f4f1ea", borderRadius: 10, padding: 16, border: "1px solid #efece5", marginBottom: 16 }}>
          <div style={{ background: "rgba(255,255,255,0.85)", border: "1px solid #efece5", borderRadius: 10, padding: 14, boxShadow: "0 1px 3px rgba(29,26,21,0.06)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 24, height: 24, borderRadius: 6, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700, flexShrink: 0 }}>M+</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#2d2a24", letterSpacing: 0.2 }}>MOKUTURE+</div>
              <div style={{ flex: 1 }} />
              <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace" }}>今</div>
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15" }}>来客のお知らせ</div>
            <div style={{ fontSize: 12, color: "#2d2a24", marginTop: 3, lineHeight: 1.5 }}>
              佐々木 美咲 様（アルチザン株式会社）が受付を完了しました。用件：打ち合わせ
            </div>
          </div>
          <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 12, textAlign: "center" }}>
            ロック画面・バックグラウンドでも受信可能
          </div>
        </div>

        {vapidKey && subscriptions.length > 0 && (
          <MkBtn
            variant="default"
            size="sm"
            onClick={handleTestPush}
            style={{ width: "100%", justifyContent: "center" }}
          >
            {working ? "送信中…" : testSent ? "✓ 送信しました" : "テスト通知を送信"}
          </MkBtn>
        )}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────
export default function AdminNotifyPage() {
  const params = useParams<{ tenant: string }>();
  const [authToken, setAuthToken] = useState("");

  useEffect(() => {
    setAuthToken(getAccessToken() ?? "");
  }, []);

  return (
    <AdminShell
      active="notify"
      title="通知設定"
      breadcrumb="ホーム / 設定 / 通知"
      subtitle="Slack · Chatwork · PWA プッシュ通知の連携と受信者管理"
    >
      <div className="adm-grid-2" style={{ gap: 20 }}>
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
          <div style={{ marginTop: 16 }}><MkBtn variant="primary" size="sm">保存</MkBtn></div>
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
          <div style={{ marginTop: 16 }}><MkBtn variant="primary" size="sm">保存</MkBtn></div>
        </MkCard>

        {/* PWA Push */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <MkSectionTitle
            title="PWA プッシュ通知"
            subtitle="担当者スマホに Web Push API (VAPID) で通知を配信"
          />
          {authToken ? (
            <PWAPushPanel authToken={authToken} />
          ) : (
            <div style={{ padding: "20px 0", color: "#a8a198", fontSize: 13 }}>認証が必要です。ページを再読み込みしてください。</div>
          )}
        </MkCard>
      </div>
    </AdminShell>
  );
}
