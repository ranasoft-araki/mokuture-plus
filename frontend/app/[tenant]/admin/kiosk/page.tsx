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
  const [newToken, setNewToken] = useState<{ name: string; token: string } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const loadDevices = useCallback(async (token: string) => {
    try {
      setDevices(await api.listDevices(token));
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadDevices(token);
  }, [loadDevices, router]);

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
      setNewToken({ name: created.name, token: created.token });
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

  async function handleCopy(token: string) {
    await navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const kioskUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${params.tenant}/kiosk`
    : `/${params.tenant}/kiosk`;

  // Summary counts
  const online = devices.filter((d) => {
    if (!d.last_seen_at) return false;
    return (Date.now() - new Date(d.last_seen_at).getTime()) < 2 * 60 * 1000;
  }).length;

  return (
    <AdminShell
      active="device"
      title="キオスク端末"
      breadcrumb="ホーム / キオスク端末"
      subtitle={`接続済み端末を管理 · ${devices.length} 台`}
      actions={
        <MkBtn variant="primary" onClick={() => document.getElementById("add-device-form")?.scrollIntoView({ behavior: "smooth" })}>
          + 端末を追加
        </MkBtn>
      }
    >
      {/* Summary strip */}
      <div style={{ display: "flex", gap: 14, marginBottom: 22 }}>
        {[
          { label: "稼働中", value: online, color: "#3a6240" },
          { label: "オフライン", value: devices.length - online, color: "#a8a198" },
          { label: "合計", value: devices.length, color: "#2d2a24" },
        ].map(({ label, value, color }) => (
          <MkCard key={label} padding="14px" style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: "-0.6px", marginTop: 4 }}>{value}</div>
          </MkCard>
        ))}
      </div>

      {/* Token revealed */}
      {newToken && (
        <div style={{ marginBottom: 20, padding: 20, borderRadius: 10, background: "#f7ecd9", border: "1px solid #b8763a" }}>
          <p style={{ fontWeight: 600, color: "#7a4e10", fontSize: 13, marginBottom: 4 }}>「{newToken.name}」のトークンが発行されました</p>
          <p style={{ fontSize: 12, color: "#7a4e10", marginBottom: 12 }}>このトークンは今後表示されません。キオスク端末のセットアップ画面に入力してください。</p>
          <div style={{ display: "flex", gap: 8 }}>
            <code style={{ flex: 1, background: "#fffefb", borderRadius: 7, padding: "12px 14px", fontSize: 12, fontFamily: "monospace", color: "#1d1a15", border: "1px solid #efece5", wordBreak: "break-all" }}>
              {newToken.token}
            </code>
            <button
              onClick={() => handleCopy(newToken.token)}
              style={{ flexShrink: 0, padding: "0 16px", borderRadius: 7, background: "#4a7c4e", color: "#fffefb", border: "none", fontSize: 12, fontWeight: 500, cursor: "pointer" }}
            >
              {copied ? "コピー済" : "コピー"}
            </button>
          </div>
          <p style={{ fontSize: 11, color: "#7a4e10", marginTop: 10 }}>
            セットアップ URL: <span style={{ fontFamily: "monospace" }}>{kioskUrl}/setup</span>
          </p>
          <button onClick={() => setNewToken(null)} style={{ fontSize: 11, color: "#a8a198", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", marginTop: 8 }}>閉じる</button>
        </div>
      )}

      {/* Device list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
        {loading ? (
          <MkCard><div style={{ textAlign: "center", color: "#a8a198" }}>読み込み中…</div></MkCard>
        ) : devices.length === 0 ? null : (
          devices.map((d) => {
            const isOnline = d.last_seen_at && (Date.now() - new Date(d.last_seen_at).getTime()) < 2 * 60 * 1000;
            return (
              <MkCard key={d.id} padding="0">
                <div style={{ display: "flex", alignItems: "stretch" }}>
                  {/* Preview area */}
                  <div
                    style={{
                      width: 140, minHeight: 160, background: "#1d1a15", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      borderRight: "1px solid #efece5",
                      borderRadius: "10px 0 0 10px",
                      backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 8px, transparent 8px 16px)",
                      position: "relative",
                    }}
                  >
                    <div style={{ color: "#fffefb", fontFamily: "monospace", fontSize: 9, opacity: 0.5, textAlign: "center" }}>
                      [ kiosk<br/>preview ]
                    </div>
                    <div style={{ position: "absolute", top: 10, left: 10 }}>
                      <MkPill tone={isOnline ? "live" : "off"}>{isOnline ? "稼働中" : "オフライン"}</MkPill>
                    </div>
                  </div>

                  {/* Details */}
                  <div style={{ flex: 1, padding: "18px 22px" }}>
                    <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15" }}>{d.name}</div>
                    <div style={{ fontSize: 11, color: "#a8a198", fontFamily: "monospace", marginTop: 3 }}>{d.id}</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 16, paddingTop: 14, borderTop: "1px solid #efece5" }}>
                      {[
                        { label: "発行日", value: formatDate(d.created_at) },
                        { label: "最終接続", value: d.last_seen_at ? formatDate(d.last_seen_at) : "未接続" },
                        { label: "状態", value: isOnline ? "稼働中" : "オフライン" },
                      ].map(({ label, value }) => (
                        <div key={label}>
                          <div style={{ fontSize: 10, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase", fontFamily: "monospace" }}>{label}</div>
                          <div style={{ fontSize: 12, color: "#2d2a24", marginTop: 3, fontWeight: 500 }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div style={{ width: 160, padding: 16, borderLeft: "1px solid #efece5", display: "flex", flexDirection: "column", gap: 8, background: "#f4f1ea", borderRadius: "0 10px 10px 0" }}>
                    <MkBtn size="sm" variant="default" onClick={() => window.open(`${kioskUrl}`, "_blank")}>
                      画面を開く
                    </MkBtn>
                    <MkBtn size="sm" variant="danger" onClick={() => handleDelete(d.id, d.name)}>
                      削除
                    </MkBtn>
                  </div>
                </div>
              </MkCard>
            );
          })
        )}

        {/* Pending slot (always shown if less than 3 devices) */}
        {!loading && devices.length < 3 && (
          <MkCard padding="22px" style={{ borderStyle: "dashed", background: "#f4f1ea" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ width: 48, height: 48, borderRadius: 7, background: "#fffefb", border: "1px dashed #d8d3c7", display: "flex", alignItems: "center", justifyContent: "center", color: "#a8a198", flexShrink: 0 }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              </div>
              <div style={{ flex: 1, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#2d2a24" }}>端末を追加する</div>
                <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3 }}>下のフォームから端末名を入力してトークンを発行できます</div>
              </div>
            </div>
          </MkCard>
        )}
      </div>

      {/* Add form */}
      <MkCard id="add-device-form">
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 6 }}>キオスク端末を追加</div>
        <div style={{ fontSize: 12, color: "#a8a198", marginBottom: 16 }}>端末ごとに固有のトークンを発行します。トークンはセットアップ時に一度だけ表示されます。</div>
        <form onSubmit={handleCreate} style={{ display: "flex", gap: 10 }}>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="例: 受付1F、ショールーム"
            style={{ flex: 1, border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, fontSize: 12.5, color: "#2d2a24", fontFamily: '"Noto Sans JP", system-ui, sans-serif', outline: "none" }}
            required
          />
          <MkBtn type="submit" variant="primary" disabled={creating || !newName.trim()}>
            {creating ? "発行中…" : "トークン発行"}
          </MkBtn>
        </form>
        {error && <p style={{ marginTop: 10, fontSize: 12, color: "#a84238" }}>{error}</p>}
      </MkCard>

      {/* Setup instructions */}
      <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>セットアップ手順</div>
        <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          <li>「トークン発行」で端末名を入力して発行</li>
          <li>キオスク端末のブラウザで <span style={{ fontFamily: "monospace", fontSize: 11 }}>{kioskUrl}/setup</span> を開く</li>
          <li>表示されたトークンを入力して「設定を保存」</li>
          <li>以降は自動的にキオスク待機画面が表示される</li>
        </ol>
      </div>
    </AdminShell>
  );
}

function formatDate(value: string) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
