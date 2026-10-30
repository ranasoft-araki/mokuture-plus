"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, type NotificationHealth, type StaffNotificationRoute, type StaffNotificationRoutesResponse, type StaffPushUser, type StaffRouteTestResult } from "@/lib/api";
import { requestAndSubscribe, getCurrentPushSubscription, getPushStatus, getClientOsName, matchesVapidKey, type PushStatus } from "@/lib/push";
import { getAccessToken } from "@/lib/auth";

// カスタムWebhook は当面、管理画面に出さない（送信の仕組みと API はそのまま）。
// 戻すときは true にする。説明文に出てくるカード名もこれに合わせて切り替わる。
const SHOW_CUSTOM_WEBHOOK = false;
/** 担当者の個別設定が無いときに届く先（カード名）。 */
const DEFAULT_CARDS = SHOW_CUSTOM_WEBHOOK ? "「Slack」「カスタムWebhook」「プッシュ通知」" : "「Slack」「プッシュ通知」";
/** 担当者の個別設定にある、共通の宛先にも送るチェックの名前。 */
const INCLUDE_DEFAULT_LABEL = SHOW_CUSTOM_WEBHOOK
  ? "上の「Slack」・下の「カスタムWebhook」・上の「プッシュ通知」にも送る"
  : "上の「Slack」・上の「プッシュ通知」にも送る";

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

function NotificationToggle({
  enabled,
  saving,
  error,
  onChange,
}: {
  enabled: boolean;
  saving: boolean;
  error?: string;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 13px", marginBottom: 16, background: "#f4f1ea", border: "1px solid #efece5", borderRadius: 8 }}>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="通知のオン・オフ"
        disabled={saving}
        onClick={() => onChange(!enabled)}
        style={{ width: 38, height: 22, padding: 2, border: "none", borderRadius: 999, background: enabled ? "#4a7c4e" : "#c8c2b7", cursor: saving ? "wait" : "pointer", opacity: saving ? 0.65 : 1, transition: "background 0.15s", flexShrink: 0 }}
      >
        <span style={{ display: "block", width: 18, height: 18, borderRadius: "50%", background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.2)", transform: enabled ? "translateX(16px)" : "translateX(0)", transition: "transform 0.15s" }} />
      </button>
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#2d2a24" }}>{saving ? "保存中…" : enabled ? "通知する" : "通知しない"}</div>
        <div style={{ fontSize: 10.5, color: "#8a8378", marginTop: 2 }}>連携情報は保持されます。担当者ごとに指定した通知先には影響しません。</div>
        {error && <div style={{ fontSize: 10.5, color: "#a84238", marginTop: 4 }}>{error}</div>}
      </div>
    </div>
  );
}

// Official Slack logo mark (4-color hash).
function SlackMark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 122.8 122.8" aria-hidden="true">
      <path d="M25.8 77.6c0 7.1-5.8 12.9-12.9 12.9S0 84.7 0 77.6s5.8-12.9 12.9-12.9h12.9v12.9z" fill="#E01E5A" />
      <path d="M32.3 77.6c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9v32.3c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V77.6z" fill="#E01E5A" />
      <path d="M45.2 25.8c-7.1 0-12.9-5.8-12.9-12.9S38.1 0 45.2 0s12.9 5.8 12.9 12.9v12.9H45.2z" fill="#36C5F0" />
      <path d="M45.2 32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H12.9C5.8 58.1 0 52.3 0 45.2s5.8-12.9 12.9-12.9h32.3z" fill="#36C5F0" />
      <path d="M97 45.2c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9-5.8 12.9-12.9 12.9H97V45.2z" fill="#2EB67D" />
      <path d="M90.5 45.2c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V12.9C64.7 5.8 70.5 0 77.6 0s12.9 5.8 12.9 12.9v32.3z" fill="#2EB67D" />
      <path d="M77.6 97c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9-12.9-5.8-12.9-12.9V97h12.9z" fill="#ECB22E" />
      <path d="M77.6 90.5c-7.1 0-12.9-5.8-12.9-12.9s5.8-12.9 12.9-12.9h32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H77.6z" fill="#ECB22E" />
    </svg>
  );
}

// ── Push Push Panel ────────────────────────────────────────────────────
function PushPanel({ authToken, notificationsEnabled, toggleSaving, toggleError, onToggle, onHealthChanged }: { authToken: string; notificationsEnabled: boolean; toggleSaving: boolean; toggleError?: string; onToggle: (enabled: boolean) => void; onHealthChanged: () => void }) {
  const [vapidKey, setVapidKey] = useState<string | null>(null);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [subscriptions, setSubscriptions] = useState<{ id: string; endpoint: string; display_endpoint: string; os_name: string; created_at: string }[]>([]);
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
      const own = sub ? subs.find((s) => s.endpoint === sub.endpoint) : undefined;
      const osName = getClientOsName();
      // 既存購読には OS 列が無かったため、このブラウザの行は画面を開いた時点で補完する。
      if (sub && own && own.os_name === "不明") {
        const json = sub.toJSON();
        await api.subscribePush(authToken, {
          endpoint: sub.endpoint,
          p256dh: json.keys?.p256dh ?? "",
          auth: json.keys?.auth ?? "",
          os_name: osName,
        });
        own.os_name = osName;
      }
      setSubscriptions(subs);
      // Only "receiving" if this browser's subscription uses the current key and the
      // server still has it — otherwise offer to register again.
      setIsSubscribed(
        !!sub && !!keyRes.public_key && matchesVapidKey(sub, keyRes.public_key)
        && subs.some((s) => s.endpoint === sub.endpoint),
      );
    } catch {
      setError("設定の読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [authToken]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { setPushStatus(getPushStatus()); }, []);

  const handleSubscribe = async () => {
    if (!vapidKey) return;
    setWorking(true);
    setError("");
    try {
      const status = getPushStatus();
      setPushStatus(status);
      if (status === "insecure-context") {
        setError("プッシュ通知には HTTPS 接続が必要です。本番 URL（https://）からアクセスしてください。");
        return;
      }
      if (status === "unsupported") {
        setError("このブラウザはプッシュ通知に対応していません。Chrome・Edge・Safari（macOS/iOS 16.4+）をお使いください。");
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
        os_name: getClientOsName(),
      });
      setIsSubscribed(true);
      setPushStatus(getPushStatus());
      await reload();
      onHealthChanged();
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
      onHealthChanged();
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

  const handleDeleteSub = async (endpoint: string) => {
    await api.deletePushSubscription(authToken, endpoint);
    await reload();
    onHealthChanged();
  };

  if (loading) {
    return <div style={{ padding: "24px 0", color: "#a8a198", fontSize: 13 }}>読み込み中…</div>;
  }

  return (
    <div>
      <NotificationToggle enabled={notificationsEnabled} saving={toggleSaving} error={toggleError} onChange={onToggle} />
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
          {/* Left: subscribe this device */}
          <div>
            {!vapidKey && (
              <div style={{ padding: "20px", background: "#f4f1ea", borderRadius: 10, marginBottom: 16, border: "1px solid #efece5" }}>
                <div style={{ fontSize: 13, color: "#6b6559", lineHeight: 1.55 }}>
                  プッシュ通知が使えない状態です。運営にお問い合わせください。
                </div>
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
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
                    <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2 }}>OS: {s.os_name || "不明"}</div>
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

// ── 担当者ごとの通知先 / 代理通知 ─────────────────────────────────────
// キオスクで来訪者が選んだ訪問先担当者(reception_logs.staff)ごとに宛先を割り当てる。
// 設定の無い担当者は従来どおりテナント共通の通知先だけに通知される。
const ESCALATE_CHOICES = [
  { sec: 30, label: "30秒" },
  { sec: 60, label: "1分" },
  { sec: 120, label: "2分" },
  { sec: 180, label: "3分" },
  { sec: 300, label: "5分" },
  { sec: 600, label: "10分" },
];

// API の認可エラーをそのまま見せても利用者は次に何をすべきか判断できないため、
// この設定に必要な権限と具体的な対処を案内する。ほかのエラーは従来の詳細を保つ。
function staffRoutesErrorMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : "";
  if (message === "Insufficient permissions") {
    return "この設定を変更できるのはテナント管理者です。管理者アカウントでログインし直すか、テナント管理者に設定を依頼してください。";
  }
  return message || fallback;
}

const selectStyle: React.CSSProperties = {
  width: "100%", height: 34, border: "1px solid #d8d3c7", borderRadius: 7,
  background: "#fffefb", padding: "0 8px", fontSize: 12.5, color: "#2d2a24",
  fontFamily: '"Noto Sans JP", system-ui, sans-serif',
};

function testBtnStyle(busy: boolean): React.CSSProperties {
  return {
    padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6,
    cursor: busy ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559",
    opacity: busy ? 0.6 : 1,
  };
}

/** Chatwork のルーム選択。手入力（数字ID）とAPIから取った一覧からの選択を両方許す
 * （一覧取得が失敗してもIDが分かっていれば手入力で設定できるようにする）。
 * `apiTokenDraft` は今入力中の(まだ保存していない)トークン。空なら保存済みの共通
 * トークンで取得する（issue #1 追記分：「ルーム一覧を取得して選択する形式」）。 */
function ChatworkRoomPicker({
  authToken, apiTokenDraft = "", connected, disabled = false, value, onChange, placeholder,
}: {
  authToken: string;
  apiTokenDraft?: string;
  connected: boolean;
  disabled?: boolean;
  value: string;
  onChange: (roomId: string, roomName: string) => void;
  placeholder?: string;
}) {
  const [rooms, setRooms] = useState<{ room_id: string; name: string; type: string }[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const canFetch = connected || apiTokenDraft.trim() !== "";

  const load = async () => {
    if (!canFetch) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.getChatworkRooms(authToken, apiTokenDraft.trim());
      setRooms(res.rooms);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "ルーム一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  if (rooms === null) {
    return (
      <div>
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <TextInput
              placeholder={disabled ? "Chatwork未連携" : placeholder}
              mono
              value={value}
              onChange={(v) => onChange(v.replace(/[^0-9]/g, ""), "")}
            />
          </div>
          <button
            type="button"
            onClick={load}
            disabled={disabled || !canFetch || loading}
            style={testBtnStyle(loading || disabled || !canFetch)}
          >
            {loading ? "取得中…" : "ルームを選択"}
          </button>
        </div>
        {error && <div style={{ fontSize: 11, color: "#a84238", marginTop: 4 }}>{error}</div>}
      </div>
    );
  }

  return (
    <div>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const r = rooms.find((x) => x.room_id === e.target.value);
          onChange(e.target.value, r?.name ?? "");
        }}
        style={selectStyle}
      >
        <option value="">指定しない</option>
        {value && !rooms.some((r) => r.room_id === value) && (
          <option value={value}>{value}</option>
        )}
        {rooms.map((r) => (
          <option key={r.room_id} value={r.room_id}>{r.type === "direct" ? "DM・" : ""}{r.name}</option>
        ))}
      </select>
      <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
        <button type="button" onClick={load} disabled={loading} style={{ fontSize: 11, border: "none", background: "transparent", color: "#6b6559", cursor: "pointer", padding: 0 }}>
          {loading ? "更新中…" : "再読み込み"}
        </button>
        <button type="button" onClick={() => setRooms(null)} style={{ fontSize: 11, border: "none", background: "transparent", color: "#6b6559", cursor: "pointer", padding: 0 }}>
          数字で入力する
        </button>
      </div>
    </div>
  );
}

function channelLabel(channel: string): string {
  return channel === "slack" ? "Slack" : channel === "email" ? "メール" : "Webhook";
}

function formatEscalate(sec: number): string {
  return sec % 60 === 0 ? `${sec / 60}分` : `${sec}秒`;
}

type RouteDraft = {
  slack_channel_id: string;
  /** DM先のSlackユーザーID（channel_idと排他。指定時はchannel_idを無視する）。 */
  slack_user_id: string;
  slack_display_name: string;
  /** Chatwork のルーム ID。APIトークンはテナント共通のものを使い回す。 */
  chatwork_room_id: string;
  chatwork_room_name: string;
  /** プッシュを届ける管理ユーザー（""=共通の購読へ）。 */
  push_user_id: string;
  email: string;
  /** null=変更しない（既存を維持）、""=解除、URL=差し替え。URL自体はサーバから返らない。 */
  webhook_url: string | null;
  include_default: boolean;
  fallback_staff_name: string;
  escalate_after_sec: number;
};

function draftFrom(route: StaffNotificationRoute | undefined, defaultSec: number): RouteDraft {
  return {
    slack_channel_id: route?.slack_channel_id ?? "",
    slack_user_id: "",
    slack_display_name: "",
    chatwork_room_id: route?.chatwork_room_id ?? "",
    chatwork_room_name: route?.chatwork_room_name ?? "",
    push_user_id: route?.push_user_id ?? "",
    email: route?.email ?? "",
    webhook_url: null,
    include_default: route?.include_default ?? true,
    fallback_staff_name: route?.fallback_staff_name ?? "",
    escalate_after_sec: route?.escalate_after_sec ?? defaultSec,
  };
}

function routeSummary(
  route: StaffNotificationRoute | undefined,
  users: StaffPushUser[] = [],
): string {
  if (!route) return `未設定（${DEFAULT_CARDS}カードの宛先のみ）`;
  const parts: string[] = [];
  if (route.slack_channel_name || route.slack_channel_id) {
    parts.push(`Slack ${route.slack_channel_name || route.slack_channel_id}`);
  }
  if (route.chatwork_room_id) parts.push(`Chatwork ${route.chatwork_room_name || `ルーム${route.chatwork_room_id}`}`);
  if (route.email) parts.push(`メール ${route.email}`);
  if (SHOW_CUSTOM_WEBHOOK && route.webhook_configured) parts.push("Webhook");
  if (route.push_user_id) {
    const u = users.find((x) => x.id === route.push_user_id);
    parts.push(`プッシュ ${u ? u.name : "指定ユーザー"}`);
  }
  if (parts.length === 0) parts.push("個別の宛先なし");
  if (route.include_default) parts.push(`${DEFAULT_CARDS}カードにも送る`);
  return parts.join(" ・ ");
}

/** 担当者マスターの編集（追加・名前変更・削除・並べ替え）。
 *
 * 実体は `tenants.staff_list`（キオスクの訪問先リストと同じもの）。以前は「受付設定」でしか
 * 編集できず、この画面は読むだけだった。通知の宛先を決める場所と担当者を足す場所が
 * 別なのは分かりにくいので、編集をここへ集約した（受付設定側は読み取り専用）。
 */
function StaffMasterEditor({
  authToken, names, version, onChanged, onError,
}: {
  authToken: string;
  names: string[];
  /** 最後に読んだ担当者リストの版。更新時に送り返して、他の人の変更を巻き込まない。 */
  version: string;
  onChanged: () => Promise<void> | void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");
  // 削除は取り消せないので2段階にする（JSダイアログは使わない方針）。
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    onError("");
    try {
      await fn();
      await onChanged();
      return true;
    } catch (e: unknown) {
      onError(staffRoutesErrorMessage(e, "担当者の更新に失敗しました"));
      // 失敗時も読み直す。ほかの人が変更していて 409 になった場合、画面が古い
      // ままだと同じ操作を繰り返して同じところで止まるため、最新の内容を見せる。
      await onChanged();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    const name = adding.trim();
    if (!name) return;
    if (names.includes(name)) {
      onError("同じ名前の担当者がすでに居ます");
      return;
    }
    if (await run(() => api.replaceStaffList(authToken, [...names, name], version))) setAdding("");
  };

  const remove = async (name: string) => {
    setConfirmRemove(null);
    await run(() => api.replaceStaffList(authToken, names.filter((n) => n !== name), version));
  };

  const move = async (name: string, delta: number) => {
    const i = names.indexOf(name);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= names.length) return;
    const next = [...names];
    [next[i], next[j]] = [next[j], next[i]];
    await run(() => api.replaceStaffList(authToken, next, version));
  };

  const rename = async () => {
    const from = renaming;
    const to = renameTo.trim();
    if (!from || !to || from === to) { setRenaming(null); return; }
    if (await run(() => api.renameStaff(authToken, from, to, version))) setRenaming(null);
  };

  return (
    <div style={{ border: "1px solid #efece5", borderRadius: 9, background: "#fffefb", marginBottom: 16, overflow: "hidden" }}>
      <div className="adm-toolbar" style={{ padding: "12px 14px", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15" }}>担当者（訪問先リスト）</div>
          <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3 }}>
            {names.length ? `${names.length}名・キオスクにはこの順で表示されます` : "未登録"}
          </div>
        </div>
        <MkBtn size="sm" onClick={() => { setOpen(!open); setRenaming(null); setConfirmRemove(null); }}>
          {open ? "閉じる" : "担当者を管理"}
        </MkBtn>
      </div>

      {open && (
        <div style={{ borderTop: "1px solid #efece5", padding: "14px", background: "#fdfcf9" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <TextInput placeholder="担当者名（例: 田中 太郎）" value={adding} onChange={setAdding} />
            </div>
            <MkBtn variant="primary" size="sm" onClick={add}>{busy ? "…" : "追加"}</MkBtn>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {names.map((name, i) => (
              <div key={name} style={{ border: "1px solid #efece5", borderRadius: 8, background: "#fff", padding: "8px 10px" }}>
                {renaming === name ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <TextInput value={renameTo} onChange={setRenameTo} />
                    </div>
                    <MkBtn variant="primary" size="sm" onClick={rename}>保存</MkBtn>
                    <MkBtn size="sm" onClick={() => setRenaming(null)}>やめる</MkBtn>
                  </div>
                ) : confirmRemove === name ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: 180, fontSize: 12, color: "#a84238" }}>
                      「{name}」を削除すると、この担当者の通知先設定も消えます。
                    </div>
                    <MkBtn variant="danger" size="sm" onClick={() => remove(name)}>削除する</MkBtn>
                    <MkBtn size="sm" onClick={() => setConfirmRemove(null)}>やめる</MkBtn>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: 140, fontSize: 13, color: "#1d1a15" }}>{name}</div>
                    <MkBtn size="sm" onClick={() => move(name, -1)} disabled={i === 0}>↑</MkBtn>
                    <MkBtn size="sm" onClick={() => move(name, 1)} disabled={i === names.length - 1}>↓</MkBtn>
                    <MkBtn size="sm" onClick={() => { setRenaming(name); setRenameTo(name); setConfirmRemove(null); }}>
                      名前を変更
                    </MkBtn>
                    <MkBtn size="sm" onClick={() => { setConfirmRemove(name); setRenaming(null); }}>削除</MkBtn>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 12, lineHeight: 1.8 }}>
            名前を変更すると、通知先の設定・代理通知先・まだ応答していない受付も一緒に追随します。
            過去の受付ログは当時の記録のまま残ります。
          </div>
        </div>
      )}
    </div>
  );
}

function StaffRoutesPanel({ authToken, refreshSignal }: { authToken: string; refreshSignal: number }) {
  const [data, setData] = useState<StaffNotificationRoutesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<RouteDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState("");
  const [testResult, setTestResult] = useState<{ staff: string; result: StaffRouteTestResult } | null>(null);
  const [channels, setChannels] = useState<{ id: string; name: string; is_private: boolean }[] | null>(null);
  const [slackUsers, setSlackUsers] = useState<{ id: string; name: string }[] | null>(null);
  // 解除は取り消せないので2段階にする（Slack連携解除と同じ方式。JSダイアログは使わない）。
  const [confirmClear, setConfirmClear] = useState<string | null>(null);

  // quiet=true は「読み込み中…」に落とさずデータだけ差し替える。担当者の追加・
  // 並べ替えのたびにパネル全体がアンマウントされ、開いていた編集欄が閉じるのを防ぐ。
  const reload = useCallback(async (quiet = false) => {
    if (!authToken) return;
    if (!quiet) setLoading(true);
    try {
      setData(await api.getStaffRoutes(authToken));
    } catch (e: unknown) {
      setError(staffRoutesErrorMessage(e, "設定の読み込みに失敗しました"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [authToken]);

  useEffect(() => { reload(); }, [reload]);

  // 上の「Chatwork」でトークンを保存したり「Slackに追加」の連携を解除したりしても、
  // ここは初回読み込み時のデータを持ったまま変わらない（別コンポーネント・別フェッチ）。
  // 「連携したのに未連携のまま」に見える食い違いを防ぐため、親から合図を受けて読み直す
  // （refreshSignal は親が持つ単調増加カウンタ。0=初回マウントなので無視する）。
  useEffect(() => {
    if (refreshSignal === 0) return;
    reload(true);
  }, [refreshSignal, reload]);

  // チャンネル一覧・メンバー一覧は編集を開いた時にだけ取りに行く（Slack API の往復を
  // 無駄に増やさない）。メンバー一覧はDM先の選択肢(issue #1追記分)。
  const openEditor = async (staff: string) => {
    const route = data?.routes.find((r) => r.staff_name === staff);
    setDraft(draftFrom(route, data?.default_escalate_sec ?? 60));
    setEditing(staff);
    setTestResult(null);
    setConfirmClear(null);
    setError("");
    if (data?.slack.bot_connected) {
      if (channels === null) {
        try {
          setChannels((await api.getSlackChannels(authToken)).channels);
        } catch {
          setChannels([]); // 取得できなくても既存の選択は保持したまま編集を続けられる
        }
      }
      if (slackUsers === null) {
        try {
          setSlackUsers((await api.getSlackUsers(authToken)).users);
        } catch {
          setSlackUsers([]); // 旧スコープのトークンは失敗する。DM以外の編集は続けられる
        }
      }
    }
  };

  const save = async () => {
    if (!editing || !draft) return;
    setSaving(true);
    setError("");
    try {
      await api.saveStaffRoute(authToken, { staff_name: editing, ...draft });
      setEditing(null);
      setDraft(null);
      await reload();
    } catch (e: unknown) {
      setError(staffRoutesErrorMessage(e, "保存に失敗しました"));
    } finally {
      setSaving(false);
    }
  };

  const clearRoute = async (routeId: string) => {
    setSaving(true);
    setError("");
    try {
      await api.deleteStaffRoute(authToken, routeId);
      setEditing(null);
      setDraft(null);
      setConfirmClear(null);
      await reload();
    } catch (e: unknown) {
      setError(staffRoutesErrorMessage(e, "解除に失敗しました"));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (staff: string, stage: "primary" | "fallback") => {
    setTesting(`${staff}:${stage}`);
    setError("");
    setTestResult(null);
    try {
      setTestResult({ staff, result: await api.testStaffRoute(authToken, staff, stage) });
    } catch (e: unknown) {
      setError(staffRoutesErrorMessage(e, "テスト送信に失敗しました"));
    } finally {
      setTesting("");
    }
  };

  if (loading) {
    return <div style={{ padding: "20px 0", color: "#a8a198", fontSize: 13 }}>読み込み中…</div>;
  }
  if (!data) {
    return <div style={{ padding: "20px 0", color: "#a84238", fontSize: 13 }}>{error || "設定を読み込めませんでした"}</div>;
  }

  // 担当者リスト＋（リストから消えたが設定だけ残っている担当者）を並べる。
  const orphans = data.routes.filter((r) => r.orphan).map((r) => r.staff_name);
  const names = [...data.staff_list, ...orphans];

  return (
    <div>
      <div style={{ padding: "12px 14px", background: "#f4f1ea", border: "1px solid #efece5", borderRadius: 8, fontSize: 11.5, color: "#6b6559", lineHeight: 1.8, marginBottom: 16 }}>
        担当者の登録と、担当者ごとの通知の届け先をここで管理します。ここで登録した担当者が、そのままキオスクの訪問先リストになります。
        設定していない担当者あての受付は、{DEFAULT_CARDS}の各カードの宛先だけに届きます。応答が無いときは、指定した代理担当者の通知先へ自動で転送します。
      </div>

      <StaffMasterEditor
        authToken={authToken}
        names={data.staff_list}
        version={data.staff_list_version}
        onChanged={() => reload(true)}
        onError={setError}
      />

      {names.length === 0 && (
        <div style={{ padding: "16px 18px", background: "#f4f1ea", border: "1px solid #efece5", borderRadius: 8, fontSize: 12.5, color: "#6b6559", lineHeight: 1.8 }}>
          担当者がまだ居ません。上の欄から追加すると、担当者ごとの通知先を設定できます。
        </div>
      )}

      {!data.slack.bot_connected && (
        <div style={{ padding: "10px 14px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.25)", borderRadius: 8, color: "#7a5c00", fontSize: 12, marginBottom: 14 }}>
          Slackが未連携のため、担当者ごとのチャンネル指定は使えません。上の「Slack」カードの「Slackに追加」で連携してください。
        </div>
      )}
      {!data.smtp_enabled && (
        <div style={{ padding: "10px 14px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.25)", borderRadius: 8, color: "#7a5c00", fontSize: 12, marginBottom: 14 }}>
          メール送信(SMTP)が未設定のため、メール宛先を登録しても送信されません。運営にSMTPの設定をご依頼ください。
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {names.map((staff) => {
          const route = data.routes.find((r) => r.staff_name === staff);
          const isEditing = editing === staff;
          const others = names.filter((n) => n !== staff);
          return (
            <div key={staff} style={{ border: "1px solid #efece5", borderRadius: 9, background: "#fffefb", overflow: "hidden" }}>
              <div className="adm-toolbar" style={{ padding: "12px 14px", alignItems: "center", gap: 10 }}>
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {staff}
                    {route?.orphan && <MkPill tone="warn" dot={false}>受付設定に無い担当者</MkPill>}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3, wordBreak: "break-all" }}>{routeSummary(route, data.users)}</div>
                  {route?.fallback_staff_name && route.escalate_after_sec > 0 && (
                    <div style={{ fontSize: 11.5, color: "#6b6559", marginTop: 3 }}>
                      応答が無ければ {formatEscalate(route.escalate_after_sec)}後に「{route.fallback_staff_name}」へ代理通知
                    </div>
                  )}
                </div>
                <MkPill tone={route ? "live" : "off"}>{route ? "設定済" : "未設定"}</MkPill>
                <MkBtn size="sm" onClick={() => (isEditing ? setEditing(null) : openEditor(staff))}>
                  {isEditing ? "閉じる" : "編集"}
                </MkBtn>
              </div>

              {isEditing && draft && (
                <div style={{ borderTop: "1px solid #efece5", padding: "16px 14px", background: "#fdfcf9" }}>
                  <div className="adm-cols-2">
                    <Field label="Slackチャンネル / DM" hint={data.slack.bot_connected ? "この担当者宛の受付をこのチャンネル、または個人あてのDMへ送ります" : "Slack連携後に選択できます"}>
                      <select
                        value={draft.slack_user_id ? `user:${draft.slack_user_id}` : draft.slack_channel_id}
                        disabled={!data.slack.bot_connected}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v.startsWith("user:")) {
                            const id = v.slice(5);
                            const u = (slackUsers ?? []).find((x) => x.id === id);
                            setDraft({ ...draft, slack_channel_id: "", slack_user_id: id, slack_display_name: u?.name ?? "" });
                          } else {
                            setDraft({ ...draft, slack_channel_id: v, slack_user_id: "", slack_display_name: "" });
                          }
                        }}
                        style={selectStyle}
                      >
                        <option value="">送らない</option>
                        {draft.slack_channel_id && !draft.slack_user_id && !(channels ?? []).some((c) => c.id === draft.slack_channel_id) && (
                          <option value={draft.slack_channel_id}>{route?.slack_channel_name || draft.slack_channel_id}</option>
                        )}
                        <optgroup label="チャンネル">
                          {(channels ?? []).map((c) => (
                            <option key={c.id} value={c.id}>{c.is_private ? "🔒 " : "# "}{c.name}</option>
                          ))}
                        </optgroup>
                        <optgroup label="ダイレクトメッセージ（個人）">
                          {(slackUsers ?? []).map((u) => (
                            <option key={u.id} value={`user:${u.id}`}>@ {u.name}</option>
                          ))}
                        </optgroup>
                      </select>
                      {slackUsers !== null && slackUsers.length === 0 && (
                        <div style={{ fontSize: 11, color: "#a8a198", marginTop: 5 }}>
                          DM先の取得に失敗しました。権限が足りない場合は「Slackに追加」で再連携してください。
                        </div>
                      )}
                    </Field>
                    <Field
                      label="Chatworkルーム / DM"
                      hint={
                        data.chatwork.connected
                          ? "この担当者宛の受付をこのルームへ送ります。受付通知がChatworkへ届くのは、ここにルームを設定した担当者だけです（Chatworkは1:1の会話もルームとして選べます）"
                          : "上の「Chatwork」でAPIトークンを登録すると使えます"
                      }
                    >
                      <ChatworkRoomPicker
                        authToken={authToken}
                        connected={data.chatwork.connected}
                        disabled={!data.chatwork.connected}
                        value={draft.chatwork_room_id}
                        onChange={(id, name) => setDraft({ ...draft, chatwork_room_id: id, chatwork_room_name: name })}
                        placeholder="例: 312648719"
                      />
                    </Field>
                    <Field
                      label="プッシュ通知の宛先"
                      hint={`プッシュはブラウザ（ログインした人）に届きます。指定すると、この担当者あてはその人の端末だけに送ります。その人がまだプッシュを許可していないときは、下のチェック『${INCLUDE_DEFAULT_LABEL}』がONなら、上の「プッシュ通知」で登録した全端末へ送ります`}
                    >
                      <select
                        value={draft.push_user_id}
                        onChange={(e) => setDraft({ ...draft, push_user_id: e.target.value })}
                        style={selectStyle}
                      >
                        <option value="">指定しない（下のチェックがONなら、上の「プッシュ通知」で登録した全端末へ）</option>
                        {data.users.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name}{u.has_push ? "" : "（未許可）"}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="メール" hint="複数はカンマ区切り（最大5件）">
                      <TextInput
                        placeholder="tanaka@example.co.jp"
                        value={draft.email}
                        onChange={(v) => setDraft({ ...draft, email: v })}
                      />
                    </Field>
                    {SHOW_CUSTOM_WEBHOOK && (
                      <Field
                        label="Webhook URL"
                        hint={
                          route?.webhook_configured
                            ? draft.webhook_url === null
                              ? "設定済み。URLは安全のため表示しません（変更するときだけ入力）"
                              : draft.webhook_url === ""
                                ? "保存すると解除されます"
                                : "保存すると新しいURLに差し替わります"
                            : "この担当者宛の受付だけを外部システムへPOSTします（任意）"
                        }
                      >
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <TextInput
                              placeholder={route?.webhook_configured ? "設定済み（変更するときだけ入力）" : "https://hooks.example.com/..."}
                              mono
                              value={draft.webhook_url ?? ""}
                              onChange={(v) => setDraft({ ...draft, webhook_url: v })}
                            />
                          </div>
                          {route?.webhook_configured && (
                            <button
                              type="button"
                              onClick={() => setDraft({ ...draft, webhook_url: draft.webhook_url === null ? "" : null })}
                              style={testBtnStyle(false)}
                            >
                              {draft.webhook_url === null ? "解除" : "取り消し"}
                            </button>
                          )}
                        </div>
                      </Field>
                    )}
                    <Field label="代理通知先（応答が無いとき）" hint="別の担当者を指定します。転送は1段のみで、代理の代理は辿りません">
                      <select
                        value={draft.fallback_staff_name}
                        onChange={(e) => setDraft({ ...draft, fallback_staff_name: e.target.value })}
                        style={selectStyle}
                      >
                        <option value="">代理通知しない</option>
                        {others.map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </Field>
                    {draft.fallback_staff_name !== "" && (
                      <Field label="代理通知までの時間" hint="この時間を過ぎても 受付/電話/お断り の応答が無ければ代理へ送ります">
                        <select
                          value={String(draft.escalate_after_sec)}
                          onChange={(e) => setDraft({ ...draft, escalate_after_sec: Number(e.target.value) })}
                          style={selectStyle}
                        >
                          {ESCALATE_CHOICES.map((c) => <option key={c.sec} value={c.sec}>{c.label}</option>)}
                        </select>
                      </Field>
                    )}
                  </div>

                  <label style={{ display: "flex", alignItems: "flex-start", gap: 9, marginTop: 14, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={draft.include_default}
                      onChange={(e) => setDraft({ ...draft, include_default: e.target.checked })}
                      style={{ marginTop: 2 }}
                    />
                    <span style={{ fontSize: 12.5, color: "#2d2a24", lineHeight: 1.7 }}>
                      {INCLUDE_DEFAULT_LABEL}
                      <span style={{ display: "block", fontSize: 11, color: "#a8a198" }}>
                        OFF にすると、この担当者宛の受付の最初の通知は、ここで指定した宛先にだけ届きます（上の「Slack」カードのチャンネル・{SHOW_CUSTOM_WEBHOOK && "下の「カスタムWebhook」カードのURL・"}上の「プッシュ通知」で登録した全端末へは送りません）。応答が無く代理担当者へ転送するときは、誰にも届かないことを防ぐため、これらへ送ることがあります
                      </span>
                    </span>
                  </label>

                  <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <MkBtn variant="primary" size="sm" onClick={save} disabled={saving}>
                      {saving ? "保存中…" : "保存"}
                    </MkBtn>
                    {route && (
                      <>
                        <button
                          onClick={() => runTest(staff, "primary")}
                          disabled={testing !== ""}
                          style={testBtnStyle(testing !== "")}
                        >
                          {testing === `${staff}:primary` ? "送信中…" : "テスト送信"}
                        </button>
                        {route.fallback_staff_name && route.escalate_after_sec > 0 && (
                          <button
                            onClick={() => runTest(staff, "fallback")}
                            disabled={testing !== ""}
                            style={testBtnStyle(testing !== "")}
                          >
                            {testing === `${staff}:fallback` ? "送信中…" : "代理通知をテスト"}
                          </button>
                        )}
                        {confirmClear === route.id ? (
                          <>
                            <span style={{ fontSize: 12, color: "#a84238" }}>
                              この担当者の個別設定を解除します（以後この担当者あての受付は、{DEFAULT_CARDS}の各カードの宛先だけに届きます）
                            </span>
                            <MkBtn variant="danger" size="sm" onClick={() => clearRoute(route.id)} disabled={saving}>
                              {saving ? "解除中…" : "解除する"}
                            </MkBtn>
                            <MkBtn size="sm" onClick={() => setConfirmClear(null)} disabled={saving}>
                              やめる
                            </MkBtn>
                          </>
                        ) : (
                          <MkBtn variant="danger" size="sm" onClick={() => setConfirmClear(route.id)} disabled={saving}>
                            設定を解除
                          </MkBtn>
                        )}
                      </>
                    )}
                  </div>

                  {testResult?.staff === staff && (
                    <div style={{ marginTop: 12, padding: "10px 14px", background: testResult.result.ok ? "#eaf0e8" : "#f6e0dc", border: `1px solid ${testResult.result.ok ? "rgba(74,124,78,0.25)" : "rgba(168,66,56,0.3)"}`, borderRadius: 8, fontSize: 12, color: testResult.result.ok ? "#3a6240" : "#a84238" }}>
                      {testResult.result.results.map((r, i) => (
                        <div key={i} style={{ lineHeight: 1.8 }}>
                          {r.ok ? "✓" : "×"} {channelLabel(r.channel)}：{r.target}{r.error ? `（${r.error}）` : ""}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {error && (
        <div style={{ marginTop: 12, padding: "10px 14px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 8, color: "#a84238", fontSize: 12 }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────
export default function AdminNotifyPage() {
  const params = useParams<{ tenant: string }>();
  const [authToken, setAuthToken] = useState("");

  // Slack OAuth ("Slackに追加"), Bot Token + chat.postMessage. No manual token input —
  // after OAuth the admin picks a channel (conversations.list) which we save server-side.
  const [slackStatus, setSlackStatus] = useState<{ enabled: boolean; connected: boolean; channel_configured: boolean; team_name: string; channel_name: string; channel_id: string } | null>(null);
  const [slackConnecting, setSlackConnecting] = useState(false);
  const [slackTesting, setSlackTesting] = useState(false);
  const [slackDisconnecting, setSlackDisconnecting] = useState(false);
  const [slackConfirmDisconnect, setSlackConfirmDisconnect] = useState(false);
  const [slackError, setSlackError] = useState("");
  const [slackTested, setSlackTested] = useState(false);
  const [slackNotice, setSlackNotice] = useState<"" | "connected" | "denied" | "error">("");
  // Channel picker (shown after OAuth or via "チャンネル変更").
  const [slackChannels, setSlackChannels] = useState<{ id: string; name: string; is_private: boolean; is_member: boolean }[] | null>(null);
  const [slackChannelId, setSlackChannelId] = useState("");
  const [slackChannelsLoading, setSlackChannelsLoading] = useState(false);
  const [slackSavingChannel, setSlackSavingChannel] = useState(false);
  const [slackShowPicker, setSlackShowPicker] = useState(false);
  // DM先(issue #1追記分)。チャンネルと同じ<select>に「ダイレクトメッセージ」optgroupで出す。
  const [slackUsers, setSlackUsers] = useState<{ id: string; name: string }[] | null>(null);
  const [slackUsersError, setSlackUsersError] = useState("");

  const [cwApiToken, setCwApiToken] = useState("");
  const [cwRoomId, setCwRoomId] = useState("");
  const [cwConfigured, setCwConfigured] = useState(false);
  const [cwSaving, setCwSaving] = useState(false);
  const [cwTesting, setCwTesting] = useState(false);
  const [cwError, setCwError] = useState("");
  const [cwTested, setCwTested] = useState(false);

  const [slackNotificationsEnabled, setSlackNotificationsEnabled] = useState(true);
  const [chatworkNotificationsEnabled, setChatworkNotificationsEnabled] = useState(true);
  const [pushNotificationsEnabled, setPushNotificationsEnabled] = useState(true);
  const [channelToggleSaving, setChannelToggleSaving] = useState<"" | "slack" | "chatwork" | "push">("");
  const [channelToggleError, setChannelToggleError] = useState<{ channel: "slack" | "chatwork" | "push"; message: string } | null>(null);
  const [notificationHealth, setNotificationHealth] = useState<NotificationHealth | null>(null);

  // 「担当者ごとの通知先」パネルは別フェッチなので、ここでの連携/解除/保存を伝えて
  // 読み直させる合図（単調増加カウンタ。0=初回マウント扱いで無視される）。
  const [staffRoutesRefresh, setStaffRoutesRefresh] = useState(0);
  const bumpStaffRoutesRefresh = () => setStaffRoutesRefresh((n) => n + 1);

  const [customWebhookUrl, setCustomWebhookUrl] = useState("");
  const [customWebhookConfigured, setCustomWebhookConfigured] = useState(false);
  const [customWebhookSaving, setCustomWebhookSaving] = useState(false);
  const [customWebhookTesting, setCustomWebhookTesting] = useState(false);
  const [customWebhookError, setCustomWebhookError] = useState("");
  const [customWebhookTested, setCustomWebhookTested] = useState(false);

  // ── Delivery (荷物の配達/呼び出し) destinations ──────────────────────────
  // Slack: 共通の連携(Bot Token)を使い回し、ここではチャンネルだけ上書きできる
  // （2026-10-24: 配達専用に別のSlack連携を結ばせていたのを廃止。無駄な二重連携の解消）。
  const [dlSlackOverrideChannelId, setDlSlackOverrideChannelId] = useState("");
  const [dlSlackOverrideChannelName, setDlSlackOverrideChannelName] = useState("");
  const [dlSlackLegacyWebhook, setDlSlackLegacyWebhook] = useState(false);
  const [dlSlackShowPicker, setDlSlackShowPicker] = useState(false);
  const [dlSlackChannelId, setDlSlackChannelId] = useState(""); // ピッカーでの選択中の値
  const [dlSlackSaving, setDlSlackSaving] = useState(false);
  const [dlSlackResetting, setDlSlackResetting] = useState(false);
  const [dlSlackTesting, setDlSlackTesting] = useState(false);
  const [dlSlackError, setDlSlackError] = useState("");
  const [dlSlackTested, setDlSlackTested] = useState(false);

  const [dlWebhookUrl, setDlWebhookUrl] = useState("");
  const [dlWebhookConfigured, setDlWebhookConfigured] = useState(false);
  const [dlWebhookSaving, setDlWebhookSaving] = useState(false);
  const [dlWebhookTesting, setDlWebhookTesting] = useState(false);
  const [dlWebhookError, setDlWebhookError] = useState("");
  const [dlWebhookTested, setDlWebhookTested] = useState(false);

  // Delivery push (荷物の配達/呼び出し) — ON by default; targets registered push devices
  const [dlPushEnabled, setDlPushEnabled] = useState(true);
  const [dlPushSaving, setDlPushSaving] = useState(false);
  const [dlPushTesting, setDlPushTesting] = useState(false);
  const [dlPushError, setDlPushError] = useState("");
  const [dlPushTested, setDlPushTested] = useState(false);

  useEffect(() => {
    setAuthToken(getAccessToken() ?? "");
  }, []);

  const loadSlack = useCallback(async () => {
    if (!authToken) return;
    try {
      setSlackStatus(await api.getSlackStatus(authToken));
    } catch {
      /* leave previous status */
    }
  }, [authToken]);

  useEffect(() => { loadSlack(); }, [loadSlack]);

  const loadSlackChannels = useCallback(async () => {
    if (!authToken) return;
    setSlackChannelsLoading(true);
    setSlackError("");
    try {
      const res = await api.getSlackChannels(authToken);
      setSlackChannels(res.channels);
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "チャンネル一覧の取得に失敗しました");
    } finally {
      setSlackChannelsLoading(false);
    }
  }, [authToken]);

  // DM先一覧(issue #1追記分)。users:read スコープが無い旧トークンは失敗する —
  // チャンネル選択自体は続けられるよう、エラーはこの欄だけに留める。
  const loadSlackUsers = useCallback(async () => {
    if (!authToken) return;
    setSlackUsersError("");
    try {
      const res = await api.getSlackUsers(authToken);
      setSlackUsers(res.users);
    } catch (e: unknown) {
      setSlackUsers([]);
      setSlackUsersError(e instanceof Error ? e.message : "DM先の取得に失敗しました");
    }
  }, [authToken]);

  // Auto-load the channel/user list once when connected but no channel is chosen yet.
  useEffect(() => {
    if (slackStatus?.connected && !slackStatus?.channel_configured && slackChannels === null) {
      loadSlackChannels();
      loadSlackUsers();
    }
  }, [slackStatus?.connected, slackStatus?.channel_configured, slackChannels, loadSlackChannels, loadSlackUsers]);

  // Read the ?slack=connected|denied|error flag set by the OAuth callback redirect,
  // then strip it from the URL so a refresh doesn't re-show the banner.
  useEffect(() => {
    const url = new URL(window.location.href);
    const flag = url.searchParams.get("slack");
    if (flag === "connected" || flag === "denied" || flag === "error") {
      setSlackNotice(flag);
      url.searchParams.delete("slack"); // strip only ?slack, keep any other params
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  }, []);

  const reloadNotificationSettings = useCallback(async () => {
    if (!authToken) return;
    try {
      const settings = await api.getNotificationSettings(authToken);
      const health = await api.getNotificationHealth(authToken).catch(() => null);
      if (health) setNotificationHealth(health);
      const cw = settings["chatwork"] ?? {};
      const wh = settings["webhook"] ?? {};
      if (cw["api_token"]) setCwConfigured(true);
      if (wh["webhook_url"]) setCustomWebhookConfigured(true);

      const dlSlack = settings["slack_delivery"] ?? {};
      const dlWh = settings["webhook_delivery"] ?? {};
      setDlSlackLegacyWebhook(Boolean(dlSlack["webhook_url"]));
      setDlSlackOverrideChannelId(typeof dlSlack["channel_id"] === "string" ? dlSlack["channel_id"] : "");
      setDlSlackOverrideChannelName(typeof dlSlack["channel_name"] === "string" ? dlSlack["channel_name"] : "");
      if (dlWh["webhook_url"]) setDlWebhookConfigured(true);

      // push_delivery stores { enabled: bool }; default ON when unset
      const dlPush = (settings["push_delivery"] ?? {}) as Record<string, unknown>;
      setDlPushEnabled(dlPush["enabled"] !== false);

      setSlackNotificationsEnabled(settings["channel_enabled_slack"]?.["enabled"] !== false);
      setChatworkNotificationsEnabled(settings["channel_enabled_chatwork"]?.["enabled"] !== false);
      setPushNotificationsEnabled(settings["channel_enabled_push"]?.["enabled"] !== false);
    } catch {
      /* leave previous state */
    }
  }, [authToken]);

  useEffect(() => { reloadNotificationSettings(); }, [reloadNotificationSettings]);

  const refreshNotificationHealth = useCallback(async () => {
    try {
      setNotificationHealth(await api.getNotificationHealth(authToken));
      window.dispatchEvent(new Event("notification-health-changed"));
    } catch { /* 通知設定そのものの操作は成功扱いのままにする */ }
  }, [authToken]);

  const handleToggleChannel = async (channel: "slack" | "chatwork" | "push", enabled: boolean) => {
    const setters = {
      slack: setSlackNotificationsEnabled,
      chatwork: setChatworkNotificationsEnabled,
      push: setPushNotificationsEnabled,
    };
    const setEnabled = setters[channel];
    setEnabled(enabled);
    setChannelToggleSaving(channel);
    setChannelToggleError(null);
    try {
      await api.updateNotificationChannelEnabled(authToken, channel, enabled);
      setNotificationHealth(await api.getNotificationHealth(authToken));
      window.dispatchEvent(new Event("notification-health-changed"));
    } catch (e: unknown) {
      setEnabled(!enabled);
      setChannelToggleError({ channel, message: e instanceof Error ? e.message : "通知設定の保存に失敗しました" });
    } finally {
      setChannelToggleSaving("");
    }
  };

  const handleConnectSlack = async () => {
    setSlackConnecting(true);
    setSlackError("");
    try {
      const res = await api.getSlackOAuthUrl(authToken);
      if (!res.enabled || !res.authorize_url) {
        setSlackError("Slack連携は現在ご利用いただけません。運営にお問い合わせください。");
        setSlackConnecting(false);
        return;
      }
      // Full-page redirect to Slack's consent screen; we come back to the callback.
      window.location.href = res.authorize_url;
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "接続の開始に失敗しました");
      setSlackConnecting(false);
    }
  };

  const handleDisconnectSlack = async () => {
    setSlackDisconnecting(true);
    setSlackError("");
    try {
      await api.disconnectSlack(authToken);
      setSlackConfirmDisconnect(false);
      setSlackNotice("");
      setSlackShowPicker(false);
      setSlackChannels(null);
      setSlackUsers(null);
      await loadSlack();
      await refreshNotificationHealth();
      bumpStaffRoutesRefresh();
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "連携解除に失敗しました");
    } finally {
      setSlackDisconnecting(false);
    }
  };

  const handleSaveSlackChannel = async () => {
    if (!slackChannelId) return;
    setSlackSavingChannel(true);
    setSlackError("");
    try {
      if (slackChannelId.startsWith("user:")) {
        const id = slackChannelId.slice(5);
        const u = (slackUsers ?? []).find((x) => x.id === id);
        await api.setSlackChannel(authToken, { user_id: id, display_name: u?.name });
      } else {
        await api.setSlackChannel(authToken, { channel_id: slackChannelId });
      }
      setSlackShowPicker(false);
      setSlackChannelId("");
      await loadSlack();
      await refreshNotificationHealth();
      bumpStaffRoutesRefresh();
    } catch (e: unknown) {
      setSlackError(e instanceof Error ? e.message : "チャンネルの保存に失敗しました");
    } finally {
      setSlackSavingChannel(false);
    }
  };

  const handleChangeSlackChannel = () => {
    setSlackError("");
    setSlackChannelId(slackStatus?.channel_id ?? "");
    setSlackShowPicker(true);
    loadSlackChannels();
    loadSlackUsers();
  };

  const handleSaveChatwork = async () => {
    setCwSaving(true);
    setCwError("");
    try {
      await api.updateChatworkSettings(authToken, cwApiToken, cwRoomId);
      setCwConfigured(true);
      setCwApiToken("");
      setCwRoomId("");
      await refreshNotificationHealth();
      bumpStaffRoutesRefresh();
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

  // ── Delivery destination handlers ──────────────────────────────────────
  // Slack(配達): 共通の連携(Bot Token)を使い回し、チャンネルだけ上書きする
  // （setSlackChannel の target="slack_delivery"。2026-10-24: 専用のWebhook URL入力は廃止）。
  const openDlSlackPicker = () => {
    setDlSlackError("");
    setDlSlackChannelId(dlSlackOverrideChannelId);
    setDlSlackShowPicker(true);
    if (slackChannels === null) loadSlackChannels();
    if (slackUsers === null) loadSlackUsers();
  };

  const handleSaveDlSlackChannel = async () => {
    if (!dlSlackChannelId) return;
    setDlSlackSaving(true);
    setDlSlackError("");
    try {
      if (dlSlackChannelId.startsWith("user:")) {
        const id = dlSlackChannelId.slice(5);
        const u = (slackUsers ?? []).find((x) => x.id === id);
        await api.setSlackChannel(authToken, { user_id: id, display_name: u?.name }, "slack_delivery");
      } else {
        await api.setSlackChannel(authToken, { channel_id: dlSlackChannelId }, "slack_delivery");
      }
      await reloadNotificationSettings();
      setDlSlackShowPicker(false);
    } catch (e: unknown) {
      setDlSlackError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setDlSlackSaving(false);
    }
  };

  const handleResetDlSlackChannel = async () => {
    setDlSlackResetting(true);
    setDlSlackError("");
    try {
      await api.setSlackChannel(authToken, {}, "slack_delivery");
      await reloadNotificationSettings();
      setDlSlackShowPicker(false);
    } catch (e: unknown) {
      setDlSlackError(e instanceof Error ? e.message : "解除に失敗しました");
    } finally {
      setDlSlackResetting(false);
    }
  };

  const handleTestDlSlack = async () => {
    setDlSlackTesting(true);
    setDlSlackError("");
    try {
      const res = await api.testNotification(authToken, "slack_delivery");
      if (res.ok) {
        setDlSlackTested(true);
        setTimeout(() => setDlSlackTested(false), 3000);
      } else {
        setDlSlackError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setDlSlackError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setDlSlackTesting(false);
    }
  };

  const handleSaveDlWebhook = async () => {
    setDlWebhookSaving(true);
    setDlWebhookError("");
    try {
      await api.updateWebhookDelivery(authToken, dlWebhookUrl);
      setDlWebhookConfigured(Boolean(dlWebhookUrl));
      setDlWebhookUrl("");
    } catch (e: unknown) {
      setDlWebhookError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setDlWebhookSaving(false);
    }
  };

  const handleTestDlWebhook = async () => {
    setDlWebhookTesting(true);
    setDlWebhookError("");
    try {
      const res = await api.testNotification(authToken, "webhook_delivery");
      if (res.ok) {
        setDlWebhookTested(true);
        setTimeout(() => setDlWebhookTested(false), 3000);
      } else {
        setDlWebhookError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setDlWebhookError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setDlWebhookTesting(false);
    }
  };

  const handleToggleDlPush = async (next: boolean) => {
    setDlPushEnabled(next); // optimistic
    setDlPushSaving(true);
    setDlPushError("");
    try {
      await api.updatePushDelivery(authToken, next);
    } catch (e: unknown) {
      setDlPushEnabled(!next); // revert on failure
      setDlPushError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setDlPushSaving(false);
    }
  };

  const handleTestDlPush = async () => {
    setDlPushTesting(true);
    setDlPushError("");
    try {
      const res = await api.testNotification(authToken, "push_delivery");
      if (res.ok) {
        setDlPushTested(true);
        setTimeout(() => setDlPushTested(false), 3000);
      } else {
        setDlPushError(res.error ?? "送信に失敗しました");
      }
    } catch (e: unknown) {
      setDlPushError(e instanceof Error ? e.message : "送信に失敗しました");
    } finally {
      setDlPushTesting(false);
    }
  };

  return (
    <AdminShell
      active="notify"
      title="通知設定"
      breadcrumb="ホーム / 設定 / 通知"
      subtitle="Slack · Chatwork · プッシュ通知の連携と受信者管理"
    >
      {notificationHealth?.issues.map((issue) => {
        const label = issue.channel === "slack" ? "Slack" : issue.channel === "chatwork" ? "Chatwork" : "プッシュ通知";
        const action = issue.channel === "push"
          ? "登録端末の通知許可を確認し、必要に応じて端末を登録し直してください。"
          : "通知先が削除・変更されていないか確認し、通知先を設定し直してください。";
        return (
          <div key={issue.channel} style={{ marginBottom: 12, padding: "12px 16px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.3)", borderRadius: 8, color: "#7a5c00", fontSize: 12.5, lineHeight: 1.65 }}>
            <strong>{label}への通知に失敗しました。</strong> {action}
            {issue.target && <div style={{ marginTop: 3 }}>通知先：{issue.target}</div>}
            {issue.failed_at && <div style={{ marginTop: 2, fontSize: 11, opacity: 0.8 }}>検知日時：{new Date(issue.failed_at).toLocaleString("ja-JP")}</div>}
          </div>
        );
      })}
      {notificationHealth?.no_active_channel && (
        <div style={{ marginBottom: 16, padding: "12px 16px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.3)", borderRadius: 8, color: "#7a5c00", fontSize: 12.5, lineHeight: 1.65 }}>
          <strong>通知を受け取れるサービスが設定されていません。</strong><br />
          Slack、Chatwork、またはプッシュ通知のいずれかを連携し、「通知する」に設定することをおすすめします。このままでも運用は続けられます。
        </div>
      )}
      <div className="adm-grid-2" style={{ gap: 20 }}>
        {/* Slack (OAuth: Slackに追加) */}
        <MkCard>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#f7f4ef", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <SlackMark size={22} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>Slack</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>来客の受付通知を送るチャンネル。下の「荷物の配達（呼び出し）通知先」で別のチャンネルを選ばなければ、配達の呼び出しもここへ届きます</div>
            </div>
            <MkPill tone={slackStatus?.connected ? "live" : "off"}>{slackStatus?.connected ? "連携済" : "未連携"}</MkPill>
          </div>

          <NotificationToggle
            enabled={slackNotificationsEnabled}
            saving={channelToggleSaving !== ""}
            error={channelToggleError?.channel === "slack" ? channelToggleError.message : undefined}
            onChange={(enabled) => handleToggleChannel("slack", enabled)}
          />

          {slackNotice === "connected" && (
            <div style={{ marginBottom: 14, padding: "10px 14px", background: "#eaf0e8", border: "1px solid rgba(74,124,78,0.25)", borderRadius: 8, color: "#3a6240", fontSize: 12 }}>
              Slack連携が完了しました。
            </div>
          )}
          {slackNotice === "denied" && (
            <div style={{ marginBottom: 14, padding: "10px 14px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.25)", borderRadius: 8, color: "#7a5c00", fontSize: 12 }}>
              Slack連携がキャンセルされました。
            </div>
          )}
          {slackNotice === "error" && (
            <div style={{ marginBottom: 14, padding: "10px 14px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 8, color: "#a84238", fontSize: 12 }}>
              Slack連携に失敗しました。お手数ですが、もう一度お試しください。
            </div>
          )}

          {slackStatus?.enabled === false ? (
            <div style={{ padding: "14px 16px", background: "#f4f1ea", borderRadius: 8, border: "1px solid #efece5", fontSize: 12.5, color: "#6b6559", lineHeight: 1.6 }}>
              この環境ではSlack連携は現在ご利用いただけません。<br />ご利用をご希望の場合は運営までお問い合わせください。
            </div>
          ) : slackStatus?.connected && slackStatus.channel_configured && !slackShowPicker ? (
            <>
              {/* Connected + channel chosen */}
              <div style={{ padding: "14px 16px", background: "#f4f1ea", borderRadius: 8, border: "1px solid #efece5", display: "flex", flexDirection: "column", gap: 10, marginBottom: 4 }}>
                <div style={{ fontSize: 12.5, color: "#3a6240", fontWeight: 600 }}>連携済みです</div>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <div style={{ fontSize: 11, color: "#a8a198", width: 82, flexShrink: 0 }}>ワークスペース</div>
                  <div style={{ fontSize: 13, color: "#1d1a15", fontWeight: 500 }}>{slackStatus.team_name || "—"}</div>
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <div style={{ fontSize: 11, color: "#a8a198", width: 82, flexShrink: 0 }}>受付通知の送信先</div>
                  <div style={{ fontSize: 13, color: "#1d1a15", fontWeight: 500 }}>{slackStatus.channel_name || "—"}</div>
                </div>
              </div>
              {slackError && (
                <div style={{ marginTop: 12, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                  {slackError}
                </div>
              )}
              <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={handleTestSlack}
                  disabled={slackTesting}
                  style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: slackTesting ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: slackTesting ? 0.6 : 1 }}
                >
                  {slackTesting ? "送信中..." : "通知テスト"}
                </button>
                <button
                  onClick={handleChangeSlackChannel}
                  style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: "pointer", background: "#fffefb", color: "#6b6559" }}
                >
                  チャンネル変更
                </button>
                {slackTested && (
                  <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>テスト通知を送信しました ✓</span>
                )}
                <div style={{ flex: 1 }} />
                {!slackConfirmDisconnect ? (
                  <button
                    onClick={() => { setSlackConfirmDisconnect(true); setSlackError(""); }}
                    style={{ padding: "6px 12px", fontSize: 13, border: "none", borderRadius: 6, cursor: "pointer", background: "transparent", color: "#a84238" }}
                  >
                    連携解除
                  </button>
                ) : (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "#6b6559" }}>連携を解除しますか？</span>
                    <button
                      onClick={handleDisconnectSlack}
                      disabled={slackDisconnecting}
                      style={{ padding: "6px 12px", fontSize: 13, border: "1px solid rgba(168,66,56,0.4)", borderRadius: 6, cursor: slackDisconnecting ? "not-allowed" : "pointer", background: "#a84238", color: "#fffefb", opacity: slackDisconnecting ? 0.6 : 1 }}
                    >
                      {slackDisconnecting ? "解除中…" : "解除する"}
                    </button>
                    <button
                      onClick={() => setSlackConfirmDisconnect(false)}
                      disabled={slackDisconnecting}
                      style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: "pointer", background: "#fffefb", color: "#6b6559" }}
                    >
                      キャンセル
                    </button>
                  </div>
                )}
              </div>
            </>
          ) : slackStatus?.connected ? (
            <>
              {/* Connected via OAuth — pick the notification channel */}
              <div style={{ marginBottom: 12, padding: "10px 14px", background: "#eaf0e8", border: "1px solid rgba(74,124,78,0.2)", borderRadius: 8, fontSize: 12, color: "#3a6240", lineHeight: 1.55 }}>
                {slackStatus.team_name ? `「${slackStatus.team_name}」と連携しました。` : "Slackと連携しました。"}来客の受付通知を送るチャンネルを選択してください。
              </div>
              {slackChannelsLoading ? (
                <div style={{ padding: "10px 0", fontSize: 12.5, color: "#a8a198" }}>チャンネルを読み込み中…</div>
              ) : (
                <>
                  <select
                    value={slackChannelId}
                    onChange={(e) => setSlackChannelId(e.target.value)}
                    style={{ width: "100%", padding: "9px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", color: "#2d2a24" }}
                  >
                    <option value="">チャンネル・DM先を選択…</option>
                    <optgroup label="チャンネル">
                      {(slackChannels ?? []).map((c) => (
                        <option key={c.id} value={c.id}>{c.is_private ? "🔒 " : "# "}{c.name}</option>
                      ))}
                    </optgroup>
                    <optgroup label="ダイレクトメッセージ（個人）">
                      {(slackUsers ?? []).map((u) => (
                        <option key={u.id} value={`user:${u.id}`}>@ {u.name}</option>
                      ))}
                    </optgroup>
                  </select>
                  <div style={{ fontSize: 11, color: "#a8a198", marginTop: 6, lineHeight: 1.55 }}>
                    🔒 非公開チャンネルは、事前に Slack でこの App（Bot）をチャンネルに招待してください。
                  </div>
                  {slackUsersError && (
                    <div style={{ fontSize: 11, color: "#a84238", marginTop: 4, lineHeight: 1.55 }}>
                      DM先の取得に失敗しました（{slackUsersError}）。チャンネルへの通知は続けて設定できます。
                    </div>
                  )}
                </>
              )}
              {slackError && (
                <div style={{ marginTop: 12, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                  {slackError}
                </div>
              )}
              <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={handleSaveSlackChannel}
                  disabled={!slackChannelId || slackSavingChannel}
                  style={{ padding: "8px 16px", fontSize: 13, fontWeight: 600, border: "none", borderRadius: 7, cursor: (!slackChannelId || slackSavingChannel) ? "not-allowed" : "pointer", background: "#1d1a15", color: "#fffefb", opacity: (!slackChannelId || slackSavingChannel) ? 0.5 : 1 }}
                >
                  {slackSavingChannel ? "保存中…" : "このチャンネルに設定"}
                </button>
                <button
                  onClick={loadSlackChannels}
                  disabled={slackChannelsLoading}
                  style={{ padding: "8px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: "pointer", background: "#fffefb", color: "#6b6559" }}
                >
                  再読み込み
                </button>
                {slackShowPicker && (
                  <button
                    onClick={() => { setSlackShowPicker(false); setSlackError(""); }}
                    style={{ padding: "8px 12px", fontSize: 13, border: "none", borderRadius: 6, cursor: "pointer", background: "transparent", color: "#6b6559" }}
                  >
                    キャンセル
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              {/* Not connected */}
              <div style={{ fontSize: 12.5, color: "#6b6559", lineHeight: 1.65, marginBottom: 16 }}>
                「Slackに追加」を押してワークスペースを認可すると、通知先チャンネルを選んで連携できます。<br />Webhook URL やトークンの入力は不要です。
              </div>
              {slackError && (
                <div style={{ marginBottom: 14, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                  {slackError}
                </div>
              )}
              <button
                onClick={handleConnectSlack}
                disabled={slackConnecting}
                style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "10px 16px", fontSize: 14, fontWeight: 600, border: "1px solid #d8d3c7", borderRadius: 8, cursor: slackConnecting ? "not-allowed" : "pointer", background: "#fffefb", color: "#1d1a15", opacity: slackConnecting ? 0.6 : 1 }}
              >
                <SlackMark size={20} />
                {slackConnecting ? "Slackへ移動中…" : "Slackに追加"}
              </button>
            </>
          )}
        </MkCard>

        {/* Chatwork */}
        <MkCard>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#e4eef5", color: "#2e6b8e", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 15, flexShrink: 0 }}>
              CW
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>Chatwork</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>API トークンで連携。担当者ごとの受付通知・配達の呼び出しで使う</div>
            </div>
            <MkPill tone={cwConfigured ? "live" : "off"}>{cwConfigured ? "連携済" : "未連携"}</MkPill>
          </div>
          <NotificationToggle
            enabled={chatworkNotificationsEnabled}
            saving={channelToggleSaving !== ""}
            error={channelToggleError?.channel === "chatwork" ? channelToggleError.message : undefined}
            onChange={(enabled) => handleToggleChannel("chatwork", enabled)}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field
              label="API トークン"
              required={!cwConfigured}
              hint={cwConfigured ? "設定済み。安全のため表示しません（変更するときだけ入力）" : "連携するとテスト送信と「担当者ごとの通知先」のルーム指定が使えます"}
            >
              <TextInput
                placeholder={cwConfigured ? "設定済み（変更するときだけ入力）" : "Chatwork API トークン"}
                mono
                value={cwApiToken}
                onChange={setCwApiToken}
              />
            </Field>
            <Field
              label="配達の呼び出しの通知先ルーム"
              hint={
                "ここで選んだルームへは「配達の呼び出し」だけが届きます（受付の通知先は、下の「担当者ごとの通知先」で担当者ごとに設定します）。" +
                (cwConfigured ? "空欄のままにすると現在の設定を維持します。" : "未設定でも連携・テスト送信はできます。")
              }
            >
              <ChatworkRoomPicker
                authToken={authToken}
                apiTokenDraft={cwApiToken}
                connected={cwConfigured}
                value={cwRoomId}
                onChange={(id) => setCwRoomId(id)}
                placeholder={cwConfigured ? "設定済み（変更するときだけ入力）" : "例: 312648719"}
              />
            </Field>
          </div>
          {cwError && (
            <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
              {cwError}
            </div>
          )}
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
            subtitle="担当者のスマホに、アプリの通知として届けます"
          />
          {authToken ? (
            <PushPanel
              authToken={authToken}
              notificationsEnabled={pushNotificationsEnabled}
              toggleSaving={channelToggleSaving !== ""}
              toggleError={channelToggleError?.channel === "push" ? channelToggleError.message : undefined}
              onToggle={(enabled) => handleToggleChannel("push", enabled)}
              onHealthChanged={() => { void refreshNotificationHealth(); }}
            />
          ) : (
            <div style={{ padding: "20px 0", color: "#a8a198", fontSize: 13 }}>認証が必要です。ページを再読み込みしてください。</div>
          )}
        </MkCard>

        {/* Per-staff notification routes (訪問先担当者ごとの通知先 + 代理通知) */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <MkSectionTitle
            title="担当者ごとの通知先"
            subtitle="訪問先担当者ごとに届け先を分け、応答が無いときは代理担当者へ転送する"
          />
          {authToken ? (
            <StaffRoutesPanel authToken={authToken} refreshSignal={staffRoutesRefresh} />
          ) : (
            <div style={{ padding: "20px 0", color: "#a8a198", fontSize: 13 }}>認証が必要です。ページを再読み込みしてください。</div>
          )}
        </MkCard>

        {/* Custom Webhook */}
        {SHOW_CUSTOM_WEBHOOK && (
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
                <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>来客の受付があった際に指定URLへPOSTリクエストを送信します。下の「荷物の配達（呼び出し）通知先」で別のURLを設定しなければ、配達の呼び出しもここへ届きます</div>
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
    "reception_id": "...",
    "visitor_name": "佐々木 美咲",
    "company": "アルチザン株式会社",
    "staff": "田中 誠",
    "department": "営業部",
    "purpose": "打ち合わせ",
    "method": "form",
    "created_at": "2026-01-01T10:00:00Z"
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
                    <li>応答が無く代理通知された場合は <code>event</code> が <code>reception_escalated</code> になり <code>escalated_from</code>（元の担当者名）が付きます</li>
                  </ul>
                </div>
              </div>
            </div>
            {customWebhookError && (
              <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                {customWebhookError}
              </div>
            )}
            <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
        )}

        {/* Delivery call notification target (荷物の配達/呼び出し) */}
        <MkCard style={{ gridColumn: "span 2" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 8 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#f5ede1", color: "#9a6b2e", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M16 16V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" />
                <path d="M14 9h4l4 4v3a1 1 0 0 1-1 1h-2" />
                <circle cx="7.5" cy="18.5" r="1.5" /><circle cx="17.5" cy="18.5" r="1.5" />
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>荷物の配達（呼び出し）通知先</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>
                {SHOW_CUSTOM_WEBHOOK
                  ? "キオスクの「配達の呼び出し」専用の通知先。Slack・Webhookは、上の「Slack」「カスタムWebhook」カードとは別のチャンネル／URLに切り替えられます。"
                  : "キオスクの「配達の呼び出し」専用の通知先。Slackは、上の「Slack」カードとは別のチャンネルに切り替えられます。"}
              </div>
            </div>
          </div>
          <div style={{ marginBottom: 18, padding: "10px 14px", background: "#fef6e4", border: "1px solid rgba(180,130,0,0.25)", borderRadius: 8, fontSize: 12, color: "#7a5c00", lineHeight: 1.55 }}>
            ここで別の送信先を設定しない場合、Slackは上の「Slack」カード{SHOW_CUSTOM_WEBHOOK && "、Webhookは上の「カスタムWebhook」カード"}の送信先へ届きます（Chatworkは上の「Chatwork」カードで設定したルームがそのまま配達の宛先です）
          </div>

          <div className="adm-autofit-lg">
            {/* Delivery Slack — 共通のSlack連携(Bot Token)を使い回し、チャンネルだけ上書きできる */}
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", flex: 1 }}>Slack（配達）</div>
                <MkPill tone={dlSlackOverrideChannelId || dlSlackLegacyWebhook ? "live" : "off"}>
                  {dlSlackOverrideChannelId || dlSlackLegacyWebhook ? "専用チャンネル" : "「Slack」カードと同じ"}
                </MkPill>
              </div>

              {!slackStatus?.connected ? (
                <div style={{ fontSize: 12, color: "#a8a198", lineHeight: 1.6 }}>
                  上の「Slack」で連携すると、配達の呼び出し専用のチャンネルを選べます（選ばなければ、上の「Slack」カードで選んだチャンネルに届きます）。
                </div>
              ) : dlSlackShowPicker ? (
                <>
                  <select
                    value={dlSlackChannelId}
                    onChange={(e) => setDlSlackChannelId(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">チャンネル・DM先を選択…</option>
                    <optgroup label="チャンネル">
                      {(slackChannels ?? []).map((c) => (
                        <option key={c.id} value={c.id}>{c.is_private ? "🔒 " : "# "}{c.name}</option>
                      ))}
                    </optgroup>
                    <optgroup label="ダイレクトメッセージ（個人）">
                      {(slackUsers ?? []).map((u) => (
                        <option key={u.id} value={`user:${u.id}`}>@ {u.name}</option>
                      ))}
                    </optgroup>
                  </select>
                  <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <MkBtn variant="primary" size="sm" onClick={handleSaveDlSlackChannel} disabled={!dlSlackChannelId || dlSlackSaving}>
                      {dlSlackSaving ? "保存中…" : "このチャンネルに設定"}
                    </MkBtn>
                    <MkBtn size="sm" onClick={() => setDlSlackShowPicker(false)}>キャンセル</MkBtn>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 12.5, color: "#2d2a24", lineHeight: 1.6 }}>
                    {dlSlackLegacyWebhook
                      ? "旧設定（Webhook URL）で送信中です。"
                      : dlSlackOverrideChannelId
                        ? <>専用チャンネル：<strong>{dlSlackOverrideChannelName || dlSlackOverrideChannelId}</strong></>
                        : <>上の「Slack」カードで選んだチャンネル（{slackStatus.channel_name || "未設定"}）に届きます。</>}
                  </div>
                  <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <button onClick={openDlSlackPicker} style={testBtnStyle(false)}>
                      {dlSlackOverrideChannelId || dlSlackLegacyWebhook ? "チャンネルを変更" : "別のチャンネルにする"}
                    </button>
                    {(dlSlackOverrideChannelId || dlSlackLegacyWebhook) && (
                      <button onClick={handleResetDlSlackChannel} disabled={dlSlackResetting} style={testBtnStyle(dlSlackResetting)}>
                        {dlSlackResetting ? "解除中…" : "「Slack」カードと同じに戻す"}
                      </button>
                    )}
                  </div>
                </>
              )}

              {dlSlackError && (
                <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                  {dlSlackError}
                </div>
              )}
              <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={handleTestDlSlack}
                  disabled={dlSlackTesting || (!slackStatus?.connected && !dlSlackLegacyWebhook)}
                  style={testBtnStyle(dlSlackTesting || (!slackStatus?.connected && !dlSlackLegacyWebhook))}
                >
                  {dlSlackTesting ? "送信中..." : "テスト送信"}
                </button>
                {dlSlackTested && (
                  <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
                )}
              </div>
            </div>

            {/* Delivery Webhook */}
            {SHOW_CUSTOM_WEBHOOK && (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", flex: 1 }}>カスタムWebhook（配達）</div>
                  <MkPill tone={dlWebhookConfigured ? "live" : "off"}>{dlWebhookConfigured ? "設定済" : "未設定"}</MkPill>
                </div>
                <Field
                  label="Webhook URL"
                  hint={dlWebhookConfigured
                    ? "配達専用のURLを設定済みです（URLは表示しません）。空欄のまま保存すると解除され、上の「カスタムWebhook」カードのURLへ届くようになります"
                    : "未設定のあいだは、上の「カスタムWebhook」カードのURLへ届きます"}
                >
                  <TextInput
                    placeholder="https://hooks.example.com/..."
                    mono
                    value={dlWebhookUrl}
                    onChange={setDlWebhookUrl}
                  />
                </Field>
                {dlWebhookError && (
                  <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                    {dlWebhookError}
                  </div>
                )}
                <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <MkBtn variant="primary" size="sm" onClick={handleSaveDlWebhook}>
                    {dlWebhookSaving ? "保存中…" : "保存"}
                  </MkBtn>
                  {dlWebhookConfigured && (
                    <button
                      onClick={handleTestDlWebhook}
                      disabled={dlWebhookTesting}
                      style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: dlWebhookTesting ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: dlWebhookTesting ? 0.6 : 1 }}
                    >
                      {dlWebhookTesting ? "送信中..." : "テスト送信"}
                    </button>
                  )}
                  {dlWebhookTested && (
                    <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
                  )}
                </div>
              </div>
            )}

            {/* Delivery Push */}
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", flex: 1 }}>プッシュ通知（配達）</div>
                <MkPill tone={dlPushEnabled ? "live" : "off"}>{dlPushEnabled ? "有効" : "無効"}</MkPill>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                <button
                  role="switch"
                  aria-checked={dlPushEnabled}
                  onClick={() => handleToggleDlPush(!dlPushEnabled)}
                  disabled={dlPushSaving}
                  style={{
                    position: "relative", width: 46, height: 26, borderRadius: 999, flexShrink: 0, padding: 0,
                    background: dlPushEnabled ? "#4a7c4e" : "#d8d3c7", border: "none",
                    cursor: dlPushSaving ? "not-allowed" : "pointer", opacity: dlPushSaving ? 0.6 : 1,
                    transition: "background 0.15s",
                  }}
                >
                  <span style={{
                    position: "absolute", top: 3, left: dlPushEnabled ? 23 : 3, width: 20, height: 20,
                    borderRadius: "50%", background: "#fffefb", boxShadow: "0 1px 2px rgba(29,26,21,0.3)",
                    transition: "left 0.15s",
                  }} />
                </button>
                <div style={{ fontSize: 12, color: "#6b6559", lineHeight: 1.5 }}>
                  配達の呼び出し時に、上の「プッシュ通知」で登録した端末へ通知します。
                </div>
              </div>
              {dlPushError && (
                <div style={{ marginTop: 10, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>
                  {dlPushError}
                </div>
              )}
              <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={handleTestDlPush}
                  disabled={dlPushTesting || !dlPushEnabled}
                  style={{ padding: "6px 12px", fontSize: 13, border: "1px solid #efece5", borderRadius: 6, cursor: (dlPushTesting || !dlPushEnabled) ? "not-allowed" : "pointer", background: "#fffefb", color: "#6b6559", opacity: (dlPushTesting || !dlPushEnabled) ? 0.6 : 1 }}
                >
                  {dlPushTesting ? "送信中..." : "テスト送信"}
                </button>
                {dlPushTested && (
                  <span style={{ fontSize: 12, color: "#4a7c4e", fontWeight: 500 }}>送信しました ✓</span>
                )}
              </div>
            </div>
          </div>
        </MkCard>
      </div>
    </AdminShell>
  );
}
