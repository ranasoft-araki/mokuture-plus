"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { requestAndSubscribe, getCurrentPushSubscription, getPushStatus, type PushStatus } from "@/lib/push";
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

// ── Push Push Panel ────────────────────────────────────────────────────
function PushPanel({ authToken }: { authToken: string }) {
  const [vapidKey, setVapidKey] = useState<string | null>(null);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [subscriptions, setSubscriptions] = useState<{ id: string; endpoint: string; display_endpoint: string; created_at: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [testSent, setTestSent] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"settings" | "devices">("settings");
  const [pushStatus, setPushStatus] = useState<PushStatus | null>(null);

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
  useEffect(() => { setPushStatus(getPushStatus()); }, []);

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
      const status = getPushStatus();
      setPushStatus(status);
      if (status === "unsupported") {
        setError("このブラウザはプッシュ通知に対応していません。Chrome または Edge をお使いください。");
        return;
      }
      if (status === "ios-not-pwa") {
        setError('Safari の「共有」→「ホーム画面に追加」でアプリをインストールしてから再度お試しください。');
        return;
      }
      if (status === "denied") {
        setError("通知がブロックされています。ブラウザの設定から mokuture+ の通知を「許可」に変更してください。");
        return;
      }
      const sub = await requestAndSubscribe(vapidKey);
      if (!sub) { setError("通知の許可が必要です。ダイアログが表示されたら「許可」を選択してください。"); return; }
      const json = sub.toJSON();
      await api.subscribePush(authToken, {
        endpoint: sub.endpoint,
        p256dh: json.keys?.p256dh ?? "",
        auth: json.keys?.auth ?? "",
      });
      setIsSubscribed(true);
      setPushStatus(getPushStatus());
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "登録に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleUnsubscribe = async () => {
    setWorking(true);
    setError("");
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
          await api.deletePushSubscription(authToken, sub.endpoint);
          await sub.unsubscribe();
        }
      }
      setIsSubscribed(false);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "登録解除に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleTestPush = async () => {
    setWorking(true);
    setError("");
    try {
      const res = await api.testPushNotification(authToken);
      if (res.sent === 0) {
        setError(`送信失敗: ${res.total}件中0件成功。Renderのログで詳細を確認してください。`);
      } else {
        setTestSent(true);
        setTimeout(() => setTestSent(false), 3000);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setWorking(false);
    }
  };

  const handleRegenerateVapid = async () => {
    setWorking(true);
    setError("");
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (sub) await sub.unsubscribe();
      }
      await api.regenerateVapid(authToken);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "再生成に失敗しました");
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
    <div>
      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #efece5", marginBottom: 20 }}>
        {[
          { id: "settings" as const, label: "設定" },
          { id: "devices" as const, label: `登録端末 (${subscriptions.length})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "10px 16px", fontSize: 12.5, fontWeight: activeTab === tab.id ? 600 : 400,
              color: activeTab === tab.id ? "#1d1a15" : "#6b6559",
              background: "none", border: "none",
              borderBottom: activeTab === tab.id ? "2px solid #1d1a15" : "2px solid transparent",
              cursor: "pointer", marginBottom: -1, fontFamily: '"Noto Sans JP", system-ui, sans-serif',
            }}
          >{tab.label}</button>
        ))}
      </div>

      {activeTab === "settings" && (
        <div className="adm-grid-2" style={{ gap: 20 }}>
          {/* Left: VAPID setup + subscribe */}
          <div>
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
                <span style={{ fontSize: 12, color: "#3a6240", fontWeight: 500, flex: 1 }}>VAPID 鍵が設定されています</span>
                <button
                  onClick={handleRegenerateVapid}
                  disabled={working}
                  style={{ fontSize: 10.5, color: "#a8a198", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", padding: 0 }}
                >
                  再生成
                </button>
              </div>
            )}

            {vapidKey && pushStatus === "ios-not-pwa" && (
              <div style={{ marginBottom: 12, padding: "10px 14px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.3)", borderRadius: 8, fontSize: 12, color: "#7a5c00", display: "flex", gap: 8, alignItems: "flex-start" }}>
                <span style={{ flexShrink: 0 }}>⚠️</span>
                <span>iPhone/iPad の場合は、Safari の「共有」→「ホーム画面に追加」でインストールしてから通知を有効にしてください。</span>
              </div>
            )}

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

            {error && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 8, color: "#a84238", fontSize: 12 }}>
                {error}
              </div>
            )}
          </div>

          {/* Right: notification preview + test */}
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
      )}

      {activeTab === "devices" && (
        <div>
          {subscriptions.length === 0 ? (
            <div style={{ padding: "40px 0", textAlign: "center", color: "#a8a198", fontSize: 12 }}>
              端末が登録されていません。<br />
              「設定」タブで登録してください。
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              {subscriptions.map((s, i) => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 0", borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                  <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#f4f1ea", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b6559" strokeWidth="1.8" strokeLinecap="round"><rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="17" r="1"/></svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11.5, color: "#2d2a24", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.display_endpoint}</div>
                    <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2 }}>登録日: {new Date(s.created_at).toLocaleString("ja-JP")}</div>
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
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────
export default function AdminNotifyPage() {
  const params = useParams<{ tenant: string }>();
  const [authToken, setAuthToken] = useState("");

  const [webhookUrl, setWebhookUrl] = useState("");
  const [slackConfigured, setSlackConfigured] = useState(false);
  const [slackSaving, setSlackSaving] = useState(false);
  const [slackTesting, setSlackTesting] = useState(false);
  const [slackError, setSlackError] = useState("");
  const [slackTested, setSlackTested] = useState(false);

  const [cwApiToken, setCwApiToken] = useState("");
  const [cwRoomId, setCwRoomId] = useState("");
  const [cwConfigured, setCwConfigured] = useState(false);
  const [cwSaving, setCwSaving] = useState(false);
  const [cwTesting, setCwTesting] = useState(false);
  const [cwError, setCwError] = useState("");
  const [cwTested, setCwTested] = useState(false);

  const [customWebhookUrl, setCustomWebhookUrl] = useState("");
  const [customWebhookConfigured, setCustomWebhookConfigured] = useState(false);
  const [customWebhookSaving, setCustomWebhookSaving] = useState(false);
  const [customWebhookTesting, setCustomWebhookTesting] = useState(false);
  const [customWebhookError, setCustomWebhookError] = useState("");
  const [customWebhookTested, setCustomWebhookTested] = useState(false);

  useEffect(() => {
    setAuthToken(getAccessToken() ?? "");
  }, []);

  useEffect(() => {
    if (!authToken) return;
    api.getNotificationSettings(authToken).then((settings) => {
      const slack = settings["slack"] ?? {};
      const cw = settings["chatwork"] ?? {};
      const wh = settings["webhook"] ?? {};
      if (slack["webhook_url"]) setSlackConfigured(true);
      if (cw["api_token"]) setCwConfigured(true);
      if (wh["webhook_url"]) setCustomWebhookConfigured(true);
    }).catch(() => {});
  }, [authToken]);

  const handleSaveSlack = async () => {
    setSlackSaving(true);
    setSlackError("");
    try {
      await api.updateSlackSettings(authToken, webhookUrl);
      setSlackConfigured(true);
      setWebhookUrl("");
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSlackSaving(false);
    }
  };

  const handleSaveChatwork = async () => {
    setCwSaving(true);
    setCwError("");
    try {
      await api.updateChatworkSettings(authToken, cwApiToken, cwRoomId);
      setCwConfigured(true);
      setCwApiToken("");
      setCwRoomId("");
    } catch (e: unknown) {
      setCwError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setCwSaving(false);
    }
  };

  const handleTestSlack = async () => {
    setSlackTesting(true);
    setSlackError("");
    try {
      const res = await api.testNotification(authToken, "slack");
      if (res.ok) {
        setSlackTested(true);
        setTimeout(() => setSlackTested(false), 3000);
      } else {
        setSlackError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setSlackTesting(false);
    }
  };

  const handleTestChatwork = async () => {
    setCwTesting(true);
    setCwError("");
    try {
      const res = await api.testNotification(authToken, "chatwork");
      if (res.ok) {
        setCwTested(true);
        setTimeout(() => setCwTested(false), 3000);
      } else {
        setCwError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setCwError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setCwTesting(false);
    }
  };

  const handleSaveCustomWebhook = async () => {
    setCustomWebhookSaving(true);
    setCustomWebhookError("");
    try {
      await api.updateWebhookSettings(authToken, customWebhookUrl);
      setCustomWebhookConfigured(true);
      setCustomWebhookUrl("");
    } catch (e: unknown) {
      setCustomWebhookError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setCustomWebhookSaving(false);
    }
  };

  const handleTestCustomWebhook = async () => {
    setCustomWebhookTesting(true);
    setCustomWebhookError("");
    try {
      const res = await api.testNotification(authToken, "webhook");
      if (res.ok) {
        setCustomWebhookTested(true);
        setTimeout(() => setCustomWebhookTested(false), 3000);
      } else {
        setCustomWebhookError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setCustomWebhookError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setCustomWebhookTesting(false);
    }
  };

  return (
    <AdminShell
      active="notify"
      title="通知設定"
      breadcrumb="ホーム / 設定 / 通知"
      subtitle="Slack · Chatwork · プッシュ通知の連携と受信者管理"
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
            <MkPill tone={slackConfigured ? "live" : "off"}>{slackConfigured ? "設定済" : "未設定"}</MkPill>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Webhook URL" required>
              <TextInput
                placeholder="https://hooks.slack.com/services/..."
                mono
                value={webhookUrl}
                onChange={setWebhookUrl}
              />
            </Field>
            <Field label="通知テンプレート" hint="{name} {company} {purpose} {time} が利用可能">
              <div style={{ border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: 10, fontSize: 12, color: "#2d2a24", lineHeight: 1.55 }}>
                来客があります：<b>{"{company}"}</b> {"{name}"} 様（用件：{"{purpose}"}）{"{time}"}
              </div>
            </Field>
          </div>
          {slackError && (
            <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
              {slackError}
            </div>
          )}
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
            <MkBtn variant="primary" size="sm" onClick={handleSaveSlack}>
              {slackSaving ? "保存中…" : "保存"}
            </MkBtn>
            {slackConfigured && (
              <button
                onClick={handleTestSlack}
                disabled={slackTesting}
                style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: slackTesting ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: slackTesting ? 0.6 : 1 }}
              >
                {slackTesting ? "送信中..." : "テスト送信"}
              </button>
            )}
            {slackTested && (
              <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
            )}
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
            <MkPill tone={cwConfigured ? "live" : "off"}>{cwConfigured ? "設定済" : "未設定"}</MkPill>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="API トークン" required>
              <TextInput
                placeholder="Chatwork API トークン"
                mono
                value={cwApiToken}
                onChange={setCwApiToken}
              />
            </Field>
            <Field label="通知先ルーム ID" required>
              <TextInput
                placeholder="例: 312648719"
                mono
                value={cwRoomId}
                onChange={setCwRoomId}
              />
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
          {cwError && (
            <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
              {cwError}
            </div>
          )}
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
            <MkBtn variant="primary" size="sm" onClick={handleSaveChatwork}>
              {cwSaving ? "保存中…" : "保存"}
            </MkBtn>
            {cwConfigured && (
              <button
                onClick={handleTestChatwork}
                disabled={cwTesting}
                style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: cwTesting ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: cwTesting ? 0.6 : 1 }}
              >
                {cwTesting ? "送信中..." : "テスト送信"}
              </button>
            )}
            {cwTested && (
              <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
            )}
          </div>
        </MkCard>

        {/* Push Notifications */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <MkSectionTitle
            title="プッシュ通知"
            subtitle="担当者スマホに Web Push API (VAPID) で通知を配信"
          />
          {authToken ? (
            <PushPanel authToken={authToken} />
          ) : (
            <div style={{ padding: "20px 0", color: "#a8a198", fontSize: 13 }}>認証が必要です。ページを再読み込みしてください。</div>
          )}
        </MkCard>

        {/* Custom Webhook */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#f0eaf5", color: "#6b3fa0", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>カスタムWebhook</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>受付があった際に指定URLへPOSTリクエストを送信します</div>
            </div>
            <MkPill tone={customWebhookConfigured ? "live" : "off"}>{customWebhookConfigured ? "設定済" : "未設定"}</MkPill>
          </div>
          <div className="adm-grid-2" style={{ gap: 20 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Field label="Webhook URL" required>
                <TextInput
                  placeholder="https://hooks.example.com/..."
                  mono
                  value={customWebhookUrl}
                  onChange={setCustomWebhookUrl}
                />
              </Field>
              <div style={{ padding: "12px 14px", background: "#f4f1ea", borderRadius: 8, border: "1px solid #efece5" }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#6b6559", marginBottom: 6 }}>送信されるJSONペイロード例</div>
                <pre style={{ fontSize: 10.5, color: "#2d2a24", margin: 0, lineHeight: 1.6, fontFamily: "monospace", whiteSpace: "pre-wrap" }}>{`{
  "event": "reception",
  "tenant_id": "...",
  "visitor_name": "佐々木 美咲",
  "company": "アルチザン株式会社",
  "staff": "田中 誠",
  "purpose": "打ち合わせ",
  "method": "form",
  "created_at": "2026-01-01T10:00:00"
}`}</pre>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ padding: "14px", background: "#f4f1ea", borderRadius: 8, border: "1px solid #efece5" }}>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 }}>使い方</div>
                <ul style={{ fontSize: 11.5, color: "#6b6559", margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
                  <li>Zapier・Make・n8n などの自動化ツールと連携できます</li>
                  <li>自社システムへのリアルタイム通知に利用できます</li>
                  <li>HTTP POST（JSON形式）で受付情報を送信します</li>
                  <li>送信失敗時もキオスク受付処理はブロックしません</li>
                </ul>
              </div>
            </div>
          </div>
          {customWebhookError && (
            <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
              {customWebhookError}
            </div>
          )}
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
            <MkBtn variant="primary" size="sm" onClick={handleSaveCustomWebhook}>
              {customWebhookSaving ? "保存中…" : "保存"}
            </MkBtn>
            {customWebhookConfigured && (
              <button
                onClick={handleTestCustomWebhook}
                disabled={customWebhookTesting}
                style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: customWebhookTesting ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: customWebhookTesting ? 0.6 : 1 }}
              >
                {customWebhookTesting ? "送信中..." : "テスト送信"}
              </button>
            )}
            {customWebhookTested && (
              <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
            )}
          </div>
        </MkCard>
      </div>
    </AdminShell>
  );
}
