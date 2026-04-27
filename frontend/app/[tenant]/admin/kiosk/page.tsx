"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Device } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";

export default function AdminKioskPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<{ name: string; token: string; pin_code: string; pin_expires_minutes: number } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<"token" | "url" | null>(null);

  const loadDevices = useCallback(async (token: string) => {
    try {
      setDevices(await api.listDevices(token));
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadDevices(token);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setCreating(true);
    setError("");
    try {
      const created = await api.createDevice(token, newName.trim());
      setDevices((d) => [created, ...d]);
      setNewToken({ name: created.name, token: created.token, pin_code: created.pin_code, pin_expires_minutes: created.pin_expires_minutes });
      setNewName("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`「${name}」を削除すると、そのキオスク端末は使用できなくなります。続けますか？`)) return;
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deleteDevice(token, id);
      setDevices((d) => d.filter((dev) => dev.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  async function handleCopy(text: string, type: "token" | "url") {
    await navigator.clipboard.writeText(text);
    setCopied(type);
    setTimeout(() => setCopied(null), 2000);
  }

  const kioskUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${params.tenant}/kiosk`
    : `/${params.tenant}/kiosk`;

  const isOnline = (d: Device) => !!d.last_seen_at && (Date.now() - new Date(d.last_seen_at).getTime()) < 2 * 60 * 1000;

  const onlineCount = devices.filter(isOnline).length;
  const offlineCount = devices.filter((d) => !!d.last_seen_at && !isOnline(d)).length;
  const pendingCount = devices.filter((d) => !d.last_seen_at).length;

  return (
    <AdminShell
      active="device"
      title="キオスク端末"
      breadcrumb="ホーム / キオスク端末"
      subtitle={`接続済み端末を管理 · ${devices.length} 台`}
      actions={
        <>
          <MkBtn variant="default" size="sm" onClick={() => document.getElementById("add-device-form")?.scrollIntoView({ behavior: "smooth" })}>
            ペアリング
          </MkBtn>
          <MkBtn variant="primary" onClick={() => document.getElementById("add-device-form")?.scrollIntoView({ behavior: "smooth" })}>
            + 端末を追加
          </MkBtn>
        </>
      }
    >
      {/* Summary strip — 4 cards */}
      <div style={{ display: "flex", gap: 14, marginBottom: 22 }}>
        {[
          { label: "稼働中",      value: onlineCount,                  color: "#3a6240" },
          { label: "警告",        value: 0,                            color: "#b8763a" },
          { label: "オフライン",  value: offlineCount,                 color: "#a8a198" },
          { label: "保留・未設定", value: pendingCount,                 color: "#6b6559" },
        ].map(({ label, value, color }) => (
          <MkCard key={label} padding={14} style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: "-0.6px", marginTop: 4 }}>{value}</div>
          </MkCard>
        ))}
      </div>

      {/* Token revealed */}
      {newToken && (
        <div style={{ marginBottom: 20, padding: 20, borderRadius: 10, background: "#f7ecd9", border: "1px solid #b8763a" }}>
          <p style={{ fontWeight: 600, color: "#7a4e10", fontSize: 13, marginBottom: 4 }}>「{newToken.name}」のデバイスが登録されました</p>

          {/* PIN */}
          <div style={{ margin: "16px 0", textAlign: "center" }}>
            <p style={{ fontSize: 11, color: "#7a4e10", marginBottom: 6 }}>ワンタイムPIN（{newToken.pin_expires_minutes}分以内・1回限り）</p>
            <div style={{ display: "inline-flex", gap: 6 }}>
              {newToken.pin_code.split("").map((d, i) => (
                <div key={i} style={{ width: 44, height: 52, borderRadius: 8, background: "#fffefb", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, fontWeight: 700, color: "#1d1a15", fontFamily: "monospace" }}>
                  {d}
                </div>
              ))}
            </div>
            <p style={{ fontSize: 11, color: "#7a4e10", marginTop: 8 }}>
              キオスク端末の画面でこのPINをタップ入力してください
            </p>
          </div>

          {/* Setup URL (SSH provisioning) */}
          <div style={{ borderTop: "1px solid #e8d5b8", paddingTop: 12, marginTop: 4 }}>
            <p style={{ fontSize: 11, color: "#7a4e10", marginBottom: 6 }}>SSHでPiを操作する場合 — セットアップURL</p>
            <div style={{ display: "flex", gap: 8 }}>
              <code style={{ flex: 1, background: "#fffefb", borderRadius: 7, padding: "8px 12px", fontSize: 10, fontFamily: "monospace", color: "#1d1a15", border: "1px solid #efece5", wordBreak: "break-all" }}>
                {kioskUrl}/setup?pin={newToken.pin_code}
              </code>
              <button
                onClick={() => handleCopy(`${kioskUrl}/setup?pin=${newToken.pin_code}`, "url")}
                style={{ flexShrink: 0, padding: "0 12px", borderRadius: 7, background: "#7a4e10", color: "#fffefb", border: "none", fontSize: 11, fontWeight: 500, cursor: "pointer" }}
              >
                {copied === "url" ? "コピー済" : "URLコピー"}
              </button>
            </div>
          </div>

          {/* Long token (hidden, for manual entry) */}
          <details style={{ marginTop: 12 }}>
            <summary style={{ fontSize: 11, color: "#a8a198", cursor: "pointer" }}>デバイストークンを表示（保存推奨）</summary>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <code style={{ flex: 1, background: "#fffefb", borderRadius: 7, padding: "10px 12px", fontSize: 10, fontFamily: "monospace", color: "#1d1a15", border: "1px solid #efece5", wordBreak: "break-all" }}>
                {newToken.token}
              </code>
              <button
                onClick={() => handleCopy(newToken.token, "token")}
                style={{ flexShrink: 0, padding: "0 12px", borderRadius: 7, background: "#4a7c4e", color: "#fffefb", border: "none", fontSize: 11, fontWeight: 500, cursor: "pointer" }}
              >
                {copied === "token" ? "コピー済" : "コピー"}
              </button>
            </div>
            <p style={{ fontSize: 10, color: "#a8a198", marginTop: 4 }}>このトークンは今後表示されません</p>
          </details>

          <button onClick={() => setNewToken(null)} style={{ fontSize: 11, color: "#a8a198", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", marginTop: 12 }}>閉じる</button>
        </div>
      )}

      {/* Device list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
        {loading ? (
          <MkCard><div style={{ textAlign: "center", color: "#a8a198" }}>読み込み中…</div></MkCard>
        ) : devices.length === 0 ? null : (
          devices.map((d) => {
            const online = isOnline(d);
            return (
              <MkCard key={d.id} padding="0">
                <div style={{ display: "flex", alignItems: "stretch" }}>
                  {/* Preview area */}
                  <div
                    style={{
                      width: 150, minHeight: 180, background: "#1d1a15", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      borderRight: "1px solid #efece5",
                      borderRadius: "10px 0 0 10px",
                      backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 8px, transparent 8px 16px)",
                      position: "relative",
                    }}
                  >
                    <div style={{ color: "#fffefb", fontFamily: "monospace", fontSize: 10, opacity: 0.6, textAlign: "center" }}>
                      [ kiosk live<br/>preview ]
                    </div>
                    <div style={{ position: "absolute", top: 10, left: 10 }}>
                      <MkPill tone={online ? "live" : "off"}>{online ? "稼働中" : "オフライン"}</MkPill>
                    </div>
                  </div>

                  {/* Details */}
                  <div style={{ flex: 1, padding: "18px 22px" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                      <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15" }}>{d.name}</div>
                      <div style={{ fontSize: 11, color: "#a8a198", fontFamily: "monospace" }}>{d.id}</div>
                    </div>
                    <div style={{ fontSize: 11.5, color: "#6b6559", marginTop: 3 }}>キオスク端末</div>
                    <div style={{
                      display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16,
                      marginTop: 18, paddingTop: 14, borderTop: "1px solid #efece5",
                    }}>
                      {[
                        { label: "IPアドレス",        value: "—",                    mono: true },
                        { label: "MAC",               value: "—",                    mono: true },
                        { label: "バージョン",         value: "—",                    mono: true },
                        { label: "最終同期",           value: d.last_seen_at ? formatRelative(d.last_seen_at) : "未接続", mono: false },
                        { label: "連続稼働",           value: "—",                    mono: false },
                        { label: "現在のプレイリスト", value: "—",                    mono: false },
                        { label: "配信スロット",       value: "—",                    mono: true },
                        { label: "発行日",             value: formatDate(d.created_at), mono: false },
                      ].map(({ label, value, mono }) => (
                        <div key={label}>
                          <div style={{ fontSize: 10, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase", fontFamily: "monospace" }}>{label}</div>
                          <div style={{ fontSize: 12, color: "#2d2a24", marginTop: 3, fontWeight: 500, fontFamily: mono ? "monospace" : undefined }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div style={{
                    width: 180, padding: 18, borderLeft: "1px solid #efece5",
                    display: "flex", flexDirection: "column", gap: 8,
                    background: "#f4f1ea", borderRadius: "0 10px 10px 0",
                  }}>
                    <MkBtn size="sm" variant="default" onClick={() => window.open(kioskUrl, "_blank")}>
                      画面プレビュー
                    </MkBtn>
                    <MkBtn size="sm" variant="default">
                      再起動
                    </MkBtn>
                    <MkBtn size="sm" variant="default">
                      端末設定
                    </MkBtn>
                    <MkBtn size="sm" variant="ghost" onClick={() => handleDelete(d.id, d.name)}>
                      削除
                    </MkBtn>
                  </div>
                </div>
              </MkCard>
            );
          })
        )}

        {/* Pending slot */}
        {!loading && (
          <MkCard padding="22px" style={{ borderStyle: "dashed", background: "#f4f1ea" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ width: 48, height: 48, borderRadius: 7, background: "#fffefb", border: "1px dashed #d8d3c7", display: "flex", alignItems: "center", justifyContent: "center", color: "#a8a198", flexShrink: 0 }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#2d2a24" }}>ペアリング待機中の端末 · {pendingCount} 台</div>
                <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3 }}>新しい端末で QR コードをスキャンすると、この場所に表示されます</div>
              </div>
              <MkBtn size="sm" variant="default" onClick={() => document.getElementById("add-device-form")?.scrollIntoView({ behavior: "smooth" })}>
                QRを表示
              </MkBtn>
            </div>
          </MkCard>
        )}
      </div>

      {/* Add form */}
      <MkCard id="add-device-form">
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 6 }}>キオスク端末を追加</div>
        <div style={{ fontSize: 12, color: "#a8a198", marginBottom: 16 }}>端末ごとに6桁のワンタイムPINを発行します。キオスク画面のテンキーで入力してください。</div>
        <form onSubmit={handleCreate} style={{ display: "flex", gap: 10 }}>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="例: 受付1F、ショールーム"
            style={{ flex: 1, border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, fontSize: 12.5, color: "#2d2a24", outline: "none", background: "#fffefb" }}
            required
          />
          <MkBtn type="submit" variant="primary" disabled={creating || !newName.trim()}>
            {creating ? "発行中…" : "トークン発行"}
          </MkBtn>
        </form>
        {error && <p style={{ marginTop: 10, fontSize: 12, color: "#a84238" }}>{error}</p>}
      </MkCard>

      {/* Setup instructions */}
      <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559" }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>セットアップ手順</div>
        <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          <li>「トークン発行」で端末名を入力 → 6桁PINが表示される</li>
          <li>キオスク端末のブラウザで <span style={{ fontFamily: "monospace", fontSize: 11 }}>{kioskUrl}/setup</span> を開く</li>
          <li>タッチテンキーでPINを入力（キーボード不要）</li>
          <li>以降は自動的にキオスク待機画面が表示される</li>
          <li style={{ color: "#7a4e10" }}>SSH/リモート操作の場合は「URLコピー」でセットアップURLを使用</li>
        </ol>
      </div>
    </AdminShell>
  );
}

function formatDate(value: string) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatRelative(value: string) {
  const diff = Date.now() - new Date(value).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}時間前`;
  return `${Math.floor(hr / 24)}日前`;
}
