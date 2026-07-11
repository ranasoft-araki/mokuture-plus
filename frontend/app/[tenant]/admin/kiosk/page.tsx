"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Device } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";
import { ConfirmModal } from "@/components/ConfirmModal";

export default function AdminKioskPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{ id: string; name: string } | null>(null);
  const [forcePushing, setForcePushing] = useState(false);
  const [forcePushMsg, setForcePushMsg] = useState("");
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [refreshingDeviceId, setRefreshingDeviceId] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState("");
  const [editingDeviceId, setEditingDeviceId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [editingLocationId, setEditingLocationId] = useState<string | null>(null);
  const [editingLocation, setEditingLocation] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [modal, setModal] = useState<{ msg: string; confirmLabel?: string; action: () => Promise<void> } | null>(null);

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
    // 承認待ち端末が接続してくるのを検知するため、一定間隔で自動更新する。
    const timer = setInterval(() => {
      const t = getAccessToken();
      if (t) void loadDevices(t);
    }, 15000);
    return () => clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  async function handleApprove(deviceId: string) {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setApprovingId(deviceId);
    setError("");
    try {
      const updated = await api.approveDevice(token, deviceId);
      setDevices((d) => d.map((dev) => dev.id === deviceId ? { ...dev, status: updated.status } : dev));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "承認に失敗しました");
    } finally {
      setApprovingId(null);
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

  function handleForcePush() {
    setModal({
      msg: "すべてのデバイスに強制配信します。キオスクは次の待機画面で自動更新されます。続けますか？",
      confirmLabel: "配信する",
      action: async () => {
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
      },
    });
  }

  async function handleSaveDeviceName(deviceId: string) {
    const t = getAccessToken();
    if (!t) { router.push("/login"); return; }
    const name = editingName.trim();
    if (!name) { setEditingDeviceId(null); setEditingName(""); return; }
    try {
      const updated = await api.updateDevice(t, deviceId, name);
      setDevices((d) => d.map((dev) => dev.id === deviceId ? { ...dev, name: updated.name } : dev));
      setError("");
      setEditingDeviceId(null);
      setEditingName("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "名前の更新に失敗しました");
    }
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

  const kioskUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${params.tenant}/kiosk`
    : `/${params.tenant}/kiosk`;

  const isPending = (d: Device) => d.status === "pending";
  const isOnline = (d: Device) => !isPending(d) && !!d.last_seen_at && (Date.now() - utcDate(d.last_seen_at).getTime()) < 3 * 60 * 1000;

  const pendingDevices = useMemo(() => devices.filter(isPending), [devices]);
  const activeDevices = useMemo(() => devices.filter((d) => !isPending(d)), [devices]);

  const filtered = useMemo(() => {
    let list = [...activeDevices];
    if (search.trim()) list = list.filter(d =>
      d.name.toLowerCase().includes(search.trim().toLowerCase()) ||
      (d.location ?? "").toLowerCase().includes(search.trim().toLowerCase())
    );
    if (statusFilter === "online") list = list.filter(d => isOnline(d));
    if (statusFilter === "offline") list = list.filter(d => !isOnline(d));
    list.sort((a, b) => {
      const score = (d: Device) => !d.last_seen_at ? 2 : isOnline(d) ? 1 : 0;
      return score(a) - score(b);
    });
    return list;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDevices, search, statusFilter]);

  const onlineCount = activeDevices.filter(isOnline).length;
  const offlineCount = activeDevices.filter((d) => !!d.last_seen_at && !isOnline(d)).length;
  const pendingCount = pendingDevices.length;

  return (
    <AdminShell
      active="device"
      title="キオスク端末"
      breadcrumb="ホーム / キオスク端末"
      subtitle={`接続済み端末を管理 · ${activeDevices.length} 台`}
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
      {error && (
        <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#f9e6e4", border: "1px solid #a84238", fontSize: 12.5, color: "#7a2820" }}>
          {error}
        </div>
      )}
      {offlineCount > 0 && (
        <div style={{ marginBottom: 14, padding: "10px 14px", borderRadius: 8, background: "#fef3cd", border: "1px solid #d4a017", fontSize: 12.5, color: "#7a5000", display: "flex", alignItems: "center", gap: 8 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d4a017" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <strong>{offlineCount} 台</strong>がオフラインです。接続状況を確認してください。
        </div>
      )}
      {/* Summary strip — 4 cards */}
      <div className="adm-autofit-sm" style={{ marginBottom: 22 }}>
        {[
          { label: "稼働中",      value: onlineCount,   color: "#3a6240" },
          { label: "承認待ち",    value: pendingCount,  color: pendingCount > 0 ? "#b8763a" : "#a8a198" },
          { label: "オフライン",  value: offlineCount,  color: "#a8a198" },
          { label: "登録済み",    value: activeDevices.length, color: "#6b6559" },
        ].map(({ label, value, color }) => (
          <MkCard key={label} padding={14} style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: "-0.6px", marginTop: 4 }}>{value}</div>
          </MkCard>
        ))}
      </div>

      {/* Pending approvals */}
      {pendingDevices.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "#7a4e10" }}>承認待ちの端末</span>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#fffefb", background: "#b8763a", borderRadius: 999, padding: "2px 10px" }}>{pendingDevices.length}</span>
          </div>
          <div style={{ fontSize: 12, color: "#a8a198", marginBottom: 14 }}>
            新しく接続した端末です。承認するとキオスク画面が起動します。不要な端末は削除してください。
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {pendingDevices.map((d) => (
              <MkCard key={d.id} padding="0" style={{ borderLeft: "3px solid #b8763a" }}>
                <div style={{ display: "flex", alignItems: "center", padding: "16px 22px", gap: 16, flexWrap: "wrap" }}>
                  <div style={{ flexShrink: 0 }}>
                    <MkPill tone="off">承認待ち</MkPill>
                  </div>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15" }}>{d.name}</div>
                    <div style={{ fontSize: 11.5, color: "#6b6559", marginTop: 3 }}>
                      {d.location ?? "場所未設定"} · 接続 {d.last_seen_at ? formatRelative(d.last_seen_at) : "—"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    <button
                      onClick={() => void handleApprove(d.id)}
                      disabled={approvingId === d.id}
                      style={{
                        border: "none", background: "#4a7c4e", color: "#fffefb",
                        padding: "8px 22px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                        cursor: approvingId === d.id ? "default" : "pointer", opacity: approvingId === d.id ? 0.6 : 1,
                      }}
                    >
                      {approvingId === d.id ? "承認中…" : "承認する"}
                    </button>
                    <MkBtn size="sm" variant="ghost" onClick={() => handleDelete(d.id, d.name)}>
                      削除
                    </MkBtn>
                  </div>
                </div>
              </MkCard>
            ))}
          </div>
        </div>
      )}

      {/* Search / filter toolbar */}
      <div className="adm-toolbar" style={{ marginBottom: 14 }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="端末名・場所で検索"
          style={{ height: 32, border: "1px solid #efece5", borderRadius: 6, fontSize: 13, padding: "0 10px", background: "#fffefb", color: "#2d2a24", outline: "none", flex: "1 1 200px", minWidth: 0 }}
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
        ) : filtered.length === 0 ? (
          activeDevices.length === 0 && pendingDevices.length === 0 ? (
            <MkCard><div style={{ textAlign: "center", color: "#a8a198", padding: "12px 0" }}>接続済みの端末はまだありません。キオスク端末で受付画面を開くと、ここに承認待ちとして表示されます。</div></MkCard>
          ) : null
        ) : (
          filtered.map((d) => {
            const online = isOnline(d);
            return (
              <MkCard key={d.id} padding="0" style={!online && d.last_seen_at ? { borderLeft: "3px solid #d4a017" } : undefined}>
                <div style={{ display: "flex", alignItems: "stretch", flexWrap: "wrap" }}>
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
                  <div style={{ flex: 1, minWidth: 120, padding: "18px 22px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
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
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                          <span
                            onDoubleClick={() => { setEditingDeviceId(d.id); setEditingName(d.name); }}
                            style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", cursor: "text" }}
                          >
                            {d.name}
                          </span>
                          <button
                            type="button"
                            onClick={() => { setEditingDeviceId(d.id); setEditingName(d.name); }}
                            title="端末名を変更"
                            aria-label="端末名を変更"
                            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: 5, background: "transparent", border: "1px solid #e2ddd2", color: "#8a8478", cursor: "pointer", flexShrink: 0 }}
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                          </button>
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
                            style={{ border: "1px solid #c8a96e", borderRadius: 4, padding: "2px 8px", fontSize: 12, color: "#1d1a15", background: "#fffefb", maxWidth: 180, width: "100%", minWidth: 0 }}
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
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                          <span
                            onDoubleClick={() => { setEditingLocationId(d.id); setEditingLocation(d.location ?? ""); }}
                            style={{ cursor: "text", color: d.location ? "#6b6559" : "#a8a198" }}
                          >
                            {d.location ?? "場所未設定"}
                          </span>
                          <button
                            type="button"
                            onClick={() => { setEditingLocationId(d.id); setEditingLocation(d.location ?? ""); }}
                            title="場所を変更"
                            aria-label="場所を変更"
                            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 5, background: "transparent", border: "1px solid #e2ddd2", color: "#a8a198", cursor: "pointer", flexShrink: 0 }}
                          >
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                          </button>
                        </span>
                      )}
                    </div>
                    <div className="adm-autofit-sm" style={{
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
                    <MkBtn size="sm" variant="ghost" onClick={() => handleDelete(d.id, d.name)}>
                      削除
                    </MkBtn>
                  </div>
                </div>
              </MkCard>
            );
          })
        )}
      </div>

      {/* Setup instructions */}
      <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559" }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>セットアップ手順</div>
        <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          <li>キオスク端末を起動する（Raspberry Pi は自動、ブラウザ端末は <span style={{ fontFamily: "monospace", fontSize: 11, overflowWrap: "anywhere" }}>{kioskUrl}</span> を開く）</li>
          <li>端末画面に「承認待ちです」と表示される</li>
          <li>この画面の<strong>「承認待ちの端末」</strong>に自動で表示されるので「承認する」を押す</li>
          <li>端末が自動的にキオスク受付画面へ切り替わる</li>
          <li>端末名や場所は鉛筆ボタンからいつでも変更できる</li>
        </ol>
      </div>
      {confirmTarget && (
        <ConfirmModal
          message={`「${confirmTarget.name}」を削除すると、そのキオスク端末は使用できなくなります。続けますか？`}
          onConfirm={doDelete}
          onCancel={() => setConfirmTarget(null)}
        />
      )}
      {modal && (
        <ConfirmModal
          message={modal.msg}
          confirmLabel={modal.confirmLabel}
          onConfirm={async () => { const action = modal.action; setModal(null); await action(); }}
          onCancel={() => setModal(null)}
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
