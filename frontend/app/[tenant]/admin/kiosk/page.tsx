"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Device } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";

function ConfirmDialog({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#fffefb", borderRadius: 12, padding: 28, maxWidth: 400, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}>
        <p style={{ fontSize: 14, color: "#2d2a24", marginBottom: 20 }}>{message}</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={{ padding: "8px 16px", borderRadius: 7, background: "#f4f1ea", border: "1px solid #d8d3c7", color: "#6b6559", cursor: "pointer", fontSize: 13 }}>キャンセル</button>
          <button onClick={onConfirm} style={{ padding: "8px 16px", borderRadius: 7, background: "#a84238", border: "none", color: "#fffefb", cursor: "pointer", fontSize: 13, fontWeight: 500 }}>削除</button>
        </div>
      </div>
    </div>
  );
}

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
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);
  const [forcePushing, setForcePushing] = useState(false);
  const [forcePushMsg, setForcePushMsg] = useState("");
  const [refreshingDeviceId, setRefreshingDeviceId] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState("");
  const [editingDeviceId, setEditingDeviceId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [editingLocationId, setEditingLocationId] = useState<string | null>(null);
  const [editingLocation, setEditingLocation] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [regenPin, setRegenPin] = useState<Record<string, { pin_code: string; expires_minutes: number; copiedPin: boolean }>>({});
  const [regenPinLoading, setRegenPinLoading] = useState<string | null>(null);

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

  function handleDelete(id: string, name: string) {
    setConfirmTarget({ id, name });
  }

  async function doDelete() {
    if (!confirmTarget) return;
    const { id } = confirmTarget;
    setConfirmTarget(null);
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deleteDevice(token, id);
      setDevices((d) => d.filter((dev) => dev.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  async function handleForceRefreshDevice(deviceId: string, deviceName: string) {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setRefreshingDeviceId(deviceId);
    setRefreshMsg("");
    try {
      await api.forceRefreshDevice(token, deviceId);
      setRefreshMsg(`「${deviceName}」に更新信号を送信しました`);
      setTimeout(() => setRefreshMsg(""), 5000);
    } catch (err: unknown) {
      setRefreshMsg(err instanceof Error ? err.message : "強制更新に失敗しました");
    } finally {
      setRefreshingDeviceId(null);
    }
  }

  async function handleForcePush() {
    if (!window.confirm("すべてのデバイスに強制配信します。キオスクは次の待機画面で自動更新されます。続けますか？")) return;
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setForcePushing(true);
    setForcePushMsg("");
    try {
      await api.forceKioskUpdate(token);
      setForcePushMsg("強制配信を設定しました。デバイスは次回の待機状態で更新されます。");
      setTimeout(() => setForcePushMsg(""), 6000);
    } catch (err: unknown) {
      setForcePushMsg(err instanceof Error ? err.message : "強制配信に失敗しました");
    } finally {
      setForcePushing(false);
    }
  }

  async function handleSaveDeviceName(deviceId: string) {
    const t = getAccessToken();
    if (!t) { router.push("/login"); return; }
    try {
      const updated = await api.updateDevice(t, deviceId, editingName.trim());
      setDevices((d) => d.map((dev) => dev.id === deviceId ? { ...dev, name: updated.name } : dev));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "名前の更新に失敗しました");
    }
    setEditingDeviceId(null);
    setEditingName("");
  }

  async function handleSaveDeviceLocation(deviceId: string) {
    const t = getAccessToken();
    if (!t) { router.push("/login"); return; }
    try {
      const loc = editingLocation.trim() || null;
      const updated = await api.updateDeviceLocation(t, deviceId, loc);
      setDevices((d) => d.map((dev) => dev.id === deviceId ? { ...dev, location: updated.location } : dev));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "場所の更新に失敗しました");
    }
    setEditingLocationId(null);
    setEditingLocation("");
  }

  async function handleCopy(text: string, type: "token" | "url") {
    await navigator.clipboard.writeText(text);
    setCopied(type);
    setTimeout(() => setCopied(null), 2000);
  }

  async function handleRegeneratePin(deviceId: string) {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setRegenPinLoading(deviceId);
    try {
      const result = await api.regenerateDevicePin(token, deviceId);
      setRegenPin((prev) => ({ ...prev, [deviceId]: { ...result, copiedPin: false } }));
      // Auto-hide after 60 seconds
      setTimeout(() => {
        setRegenPin((prev) => {
          const next = { ...prev };
          delete next[deviceId];
          return next;
        });
      }, 60000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "PINの再発行に失敗しました");
    } finally {
      setRegenPinLoading(null);
    }
  }

  async function handleCopyRegenPin(deviceId: string, pinCode: string) {
    await navigator.clipboard.writeText(pinCode);
    setRegenPin((prev) => prev[deviceId] ? { ...prev, [deviceId]: { ...prev[deviceId], copiedPin: true } } : prev);
    setTimeout(() => {
      setRegenPin((prev) => prev[deviceId] ? { ...prev, [deviceId]: { ...prev[deviceId], copiedPin: false } } : prev);
    }, 2000);
  }

  const kioskUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${params.tenant}/kiosk`
    : `/${params.tenant}/kiosk`;

  const isOnline = (d: Device) => !!d.last_seen_at && (Date.now() - utcDate(d.last_seen_at).getTime()) < 3 * 60 * 1000;

  const filtered = useMemo(() => {
    let list = [...devices];
    if (search.trim()) list = list.filter(d =>
      d.name.toLowerCase().includes(search.trim().toLowerCase()) ||
      (d.location ?? "").toLowerCase().includes(search.trim().toLowerCase())
    );
    if (statusFilter === "online") list = list.filter(d => isOnline(d));
    if (statusFilter === "offline") list = list.filter(d => !isOnline(d));
    // オフライン（要対応）を先頭に、次にオンライン、未接続を末尾に
    list.sort((a, b) => {
      const score = (d: Device) => !d.last_seen_at ? 2 : isOnline(d) ? 1 : 0;
      return score(a) - score(b);
    });
    return list;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices, search, statusFilter]);

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
        <MkBtn variant="default" size="sm" onClick={handleForcePush} disabled={forcePushing}>
          {forcePushing ? "配信中…" : "強制配信"}
        </MkBtn>
      }
    >
      {forcePushMsg && (
        <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#eaf4eb", border: "1px solid #4a7c4e", fontSize: 12.5, color: "#2d4e30" }}>
          {forcePushMsg}
        </div>
      )}
      {refreshMsg && (
        <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#fdf6e8", border: "1px solid #c8a96e", fontSize: 12.5, color: "#7a5a1e" }}>
          {refreshMsg}
        </div>
      )}
      {offlineCount > 0 && (
        <div style={{ marginBottom: 14, padding: "10px 14px", borderRadius: 8, background: "#fef3cd", border: "1px solid #d4a017", fontSize: 12.5, color: "#7a5000", display: "flex", alignItems: "center", gap: 8 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d4a017" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <strong>{offlineCount} 台</strong>がオフラインです。接続状況を確認してください。
        </div>
      )}
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
          <div style={{ margin: "16px 0", display: "flex", gap: 24, alignItems: "flex-start", justifyContent: "center", flexWrap: "wrap" }}>
            <div style={{ textAlign: "center" }}>
              <p style={{ fontSize: 11, color: "#7a4e10", marginBottom: 6 }}>ワンタイムPIN（{newToken.pin_expires_minutes}分以内・1回限り）</p>
              <div style={{ display: "inline-flex", gap: 6 }}>
                {newToken.pin_code.split("").map((d, i) => (
                  <div key={i} style={{ width: 44, height: 52, borderRadius: 8, background: "#fffefb", border: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, fontWeight: 700, color: "#1d1a15", fontFamily: "monospace" }}>
                    {d}
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10 }}>
                <button
                  onClick={() => handleCopy(newToken.pin_code, "token")}
                  style={{ padding: "5px 14px", borderRadius: 6, background: "#7a4e10", color: "#fffefb", border: "none", fontSize: 11, fontWeight: 500, cursor: "pointer" }}
                >
                  {copied === "token" ? "コピー済" : "PINをコピー"}
                </button>
              </div>
            </div>
            <div style={{ textAlign: "center" }}>
              <p style={{ fontSize: 11, color: "#7a4e10", marginBottom: 6 }}>QRコードをスキャンしてデバイスを設定してください</p>
              <img
                src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(newToken.pin_code)}&format=png&bgcolor=fffefb&color=1d1a15`}
                alt="QR Code"
                style={{ width: 160, height: 160, borderRadius: 8, border: "1px solid #efece5", display: "block" }}
              />
            </div>
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

      {/* Search / filter toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="端末名・場所で検索"
          style={{ height: 32, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#2d2a24", outline: "none", minWidth: 200 }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ height: 32, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#2d2a24", outline: "none", cursor: "pointer" }}
        >
          <option value="">全て</option>
          <option value="online">オンライン</option>
          <option value="offline">オフライン</option>
        </select>
        <span style={{ fontSize: 12, color: "#a8a198", marginLeft: "auto" }}>{filtered.length} 台</span>
      </div>

      {/* Device list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
        {loading ? (
          <MkCard><div style={{ textAlign: "center", color: "#a8a198" }}>読み込み中…</div></MkCard>
        ) : filtered.length === 0 ? null : (
          filtered.map((d) => {
            const online = isOnline(d);
            return (
              <MkCard key={d.id} padding="0" style={!online && d.last_seen_at ? { borderLeft: "3px solid #d4a017" } : undefined}>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      {editingDeviceId === d.id ? (
                        <>
                          <input
                            value={editingName}
                            onChange={(e) => setEditingName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") { void handleSaveDeviceName(d.id); }
                              if (e.key === "Escape") { setEditingDeviceId(null); setEditingName(""); }
                            }}
                            autoFocus
                            style={{ border: "1px solid #c8a96e", borderRadius: 4, padding: "3px 8px", fontSize: 13, color: "#1d1a15", background: "#fffefb" }}
                          />
                          <button
                            onClick={() => void handleSaveDeviceName(d.id)}
                            style={{ padding: "3px 8px", fontSize: 11, borderRadius: 4, background: "#4a7c4e", color: "#fffefb", border: "none", cursor: "pointer" }}
                          >
                            保存
                          </button>
                          <button
                            onClick={() => { setEditingDeviceId(null); setEditingName(""); }}
                            style={{ padding: "3px 6px", fontSize: 11, borderRadius: 4, background: "#f4f1ea", color: "#6b6559", border: "1px solid #d8d3c7", cursor: "pointer" }}
                          >
                            ×
                          </button>
                        </>
                      ) : (
                        <div
                          onDoubleClick={() => { setEditingDeviceId(d.id); setEditingName(d.name); }}
                          title="ダブルクリックで編集"
                          style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", cursor: "text" }}
                        >
                          {d.name}
                        </div>
                      )}
                      <div style={{ fontSize: 11, color: "#a8a198", fontFamily: "monospace" }}>{d.id}</div>
                    </div>
                    <div style={{ fontSize: 11.5, color: "#6b6559", marginTop: 3 }}>
                      {editingLocationId === d.id ? (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                          <input
                            value={editingLocation}
                            onChange={(e) => setEditingLocation(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") { void handleSaveDeviceLocation(d.id); }
                              if (e.key === "Escape") { setEditingLocationId(null); setEditingLocation(""); }
                            }}
                            placeholder="例: 1F受付デスク"
                            autoFocus
                            style={{ border: "1px solid #c8a96e", borderRadius: 4, padding: "2px 8px", fontSize: 12, color: "#1d1a15", background: "#fffefb", width: 180 }}
                          />
                          <button
                            onClick={() => void handleSaveDeviceLocation(d.id)}
                            style={{ padding: "2px 8px", fontSize: 11, borderRadius: 4, background: "#4a7c4e", color: "#fffefb", border: "none", cursor: "pointer" }}
                          >保存</button>
                          <button
                            onClick={() => { setEditingLocationId(null); setEditingLocation(""); }}
                            style={{ padding: "2px 6px", fontSize: 11, borderRadius: 4, background: "#f4f1ea", color: "#6b6559", border: "1px solid #d8d3c7", cursor: "pointer" }}
                          >×</button>
                        </span>
                      ) : (
                        <span
                          onDoubleClick={() => { setEditingLocationId(d.id); setEditingLocation(d.location ?? ""); }}
                          title="ダブルクリックで場所を編集"
                          style={{ cursor: "text", color: d.location ? "#6b6559" : "#a8a198" }}
                        >
                          {d.location ?? "場所未設定"}
                        </span>
                      )}
                    </div>
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
                    <button
                      onClick={() => handleForceRefreshDevice(d.id, d.name)}
                      disabled={refreshingDeviceId === d.id}
                      style={{
                        border: "1px solid #c8a96e",
                        color: refreshingDeviceId === d.id ? "#a8a198" : "#b88b44",
                        background: "transparent",
                        padding: "4px 10px",
                        borderRadius: 6,
                        fontSize: 11,
                        cursor: refreshingDeviceId === d.id ? "default" : "pointer",
                        textAlign: "center",
                      }}
                    >
                      {refreshingDeviceId === d.id ? "送信中…" : "強制更新"}
                    </button>
                    <button
                      onClick={() => void handleRegeneratePin(d.id)}
                      disabled={regenPinLoading === d.id}
                      style={{
                        border: "1px solid #a78060",
                        color: regenPinLoading === d.id ? "#a8a198" : "#7a4e10",
                        background: "transparent",
                        padding: "4px 10px",
                        borderRadius: 6,
                        fontSize: 11,
                        cursor: regenPinLoading === d.id ? "default" : "pointer",
                        textAlign: "center",
                      }}
                    >
                      {regenPinLoading === d.id ? "発行中…" : "PINを再発行"}
                    </button>
                    <MkBtn size="sm" variant="ghost" onClick={() => handleDelete(d.id, d.name)}>
                      削除
                    </MkBtn>
                  </div>
                </div>
                {regenPin[d.id] && (
                  <div style={{
                    margin: "0 18px 14px",
                    padding: "12px 16px",
                    borderRadius: 8,
                    background: "#fef9c3",
                    border: "1px solid #d4b946",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    flexWrap: "wrap",
                  }}>
                    <span style={{ fontSize: 11, color: "#7a6010", fontWeight: 600, flexShrink: 0 }}>新しいPIN</span>
                    <span style={{ fontFamily: "monospace", fontSize: 22, fontWeight: 700, letterSpacing: "0.15em", color: "#1d1a15" }}>
                      {regenPin[d.id].pin_code}
                    </span>
                    <span style={{ fontSize: 11, color: "#7a6010", flexShrink: 0 }}>
                      {regenPin[d.id].expires_minutes}分間有効
                    </span>
                    <button
                      onClick={() => void handleCopyRegenPin(d.id, regenPin[d.id].pin_code)}
                      style={{
                        padding: "4px 12px",
                        borderRadius: 6,
                        background: "#7a4e10",
                        color: "#fffefb",
                        border: "none",
                        fontSize: 11,
                        fontWeight: 500,
                        cursor: "pointer",
                        flexShrink: 0,
                      }}
                    >
                      {regenPin[d.id].copiedPin ? "コピー済" : "コピー"}
                    </button>
                    <button
                      onClick={() => setRegenPin((prev) => { const next = { ...prev }; delete next[d.id]; return next; })}
                      style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#a8a198", textDecoration: "underline", flexShrink: 0 }}
                    >
                      閉じる
                    </button>
                  </div>
                )}
              </MkCard>
            );
          })
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
      {confirmTarget && (
        <ConfirmDialog
          message={`「${confirmTarget.name}」を削除すると、そのキオスク端末は使用できなくなります。続けますか？`}
          onConfirm={doDelete}
          onCancel={() => setConfirmTarget(null)}
        />
      )}
    </AdminShell>
  );
}

function utcDate(value: string): Date {
  // Append "Z" if no timezone info to force UTC parsing
  return new Date(/[Z+]/.test(value) ? value : value + "Z");
}

function formatDate(value: string) {
  if (!value) return "—";
  return utcDate(value).toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatRelative(value: string) {
  const diff = Date.now() - utcDate(value).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 5) return "たった今";
  if (sec < 60) return `${sec}秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}時間前`;
  return `${Math.floor(hr / 24)}日前`;
}
