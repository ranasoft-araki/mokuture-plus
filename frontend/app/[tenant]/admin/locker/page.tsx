"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, Locker } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";

type UIState = "idle" | "unlocked" | "occupied" | "fault";

const STATE_MAP: Record<UIState, { bg: string; fg: string; border: string; label: string; icon: "lock" | "unlock" }> = {
  idle:     { bg: "#fffefb", fg: "#2d2a24", border: "#d8d3c7",  label: "施錠",   icon: "lock" },
  unlocked: { bg: "#eaf0e8", fg: "#3a6240", border: "#4a7c4e",  label: "開錠中", icon: "unlock" },
  occupied: { bg: "#f7ecd9", fg: "#b8763a", border: "#b8763a",  label: "使用中", icon: "lock" },
  fault:    { bg: "#f6e0dc", fg: "#a84238", border: "#a84238",  label: "異常",   icon: "lock" },
};

function toUIState(backendState: string): UIState {
  if (backendState === "unlocked") return "unlocked";
  if (backendState === "error") return "fault";
  return "idle";
}

function ConfirmDialog({ open, title, description, onConfirm, onCancel, danger }: {
  open: boolean; title: string; description?: string;
  onConfirm: () => void; onCancel: () => void; danger?: boolean;
}) {
  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onCancel}>
      <div style={{ background: "#fffefb", borderRadius: 12, padding: 28, width: 360, boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", marginBottom: 8 }}>{title}</div>
        {description && <div style={{ fontSize: 12.5, color: "#6b6559", lineHeight: 1.6, marginBottom: 20 }}>{description}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={{ padding: "8px 16px", borderRadius: 7, border: "1px solid #d8d3c7", background: "#fffefb", fontSize: 12.5, cursor: "pointer", color: "#6b6559" }}>キャンセル</button>
          <button onClick={onConfirm} style={{ padding: "8px 16px", borderRadius: 7, border: "none", background: danger ? "#a84238" : "#4a7c4e", color: "#fffefb", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>削除</button>
        </div>
      </div>
    </div>
  );
}

function AddLockerModal({ open, onClose, onAdd }: { open: boolean; onClose: () => void; onAdd: (door: number, timer: number) => Promise<void> }) {
  const [doorNumber, setDoorNumber] = useState("");
  const [autoRelock, setAutoRelock] = useState("60");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  if (!open) return null;

  const handle = async () => {
    const n = Number(doorNumber);
    if (!n || n < 1) { setErr("扉番号を入力してください"); return; }
    setAdding(true);
    setErr("");
    try {
      await onAdd(n, Number(autoRelock));
      setDoorNumber("");
      setAutoRelock("60");
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "追加に失敗しました");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div style={{ background: "#fffefb", borderRadius: 12, padding: 28, width: 400, boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", marginBottom: 20 }}>ロッカーを追加</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 20 }}>
          <div>
            <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>扉番号</label>
            <input
              type="number" min="1" value={doorNumber}
              onChange={(e) => setDoorNumber(e.target.value)}
              placeholder="例: 1"
              style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, fontSize: 12.5, color: "#2d2a24", outline: "none", boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>自動施錠タイマー</label>
            <select
              value={autoRelock} onChange={(e) => setAutoRelock(e.target.value)}
              style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 10px", height: 34, fontSize: 12.5, color: "#2d2a24", background: "#fffefb", outline: "none" }}
            >
              <option value="30">30秒</option>
              <option value="60">60秒</option>
              <option value="120">120秒</option>
              <option value="300">300秒</option>
              <option value="0">タイマーなし</option>
            </select>
          </div>
        </div>
        {err && <div style={{ marginBottom: 12, padding: "8px 12px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 7, color: "#a84238", fontSize: 12 }}>{err}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ padding: "8px 16px", borderRadius: 7, border: "1px solid #d8d3c7", background: "#fffefb", fontSize: 12.5, cursor: "pointer", color: "#6b6559" }}>キャンセル</button>
          <button onClick={handle} disabled={adding} style={{ padding: "8px 16px", borderRadius: 7, border: "none", background: "#4a7c4e", color: "#fffefb", fontSize: 12.5, fontWeight: 600, cursor: adding ? "not-allowed" : "pointer", opacity: adding ? 0.6 : 1 }}>
            {adding ? "追加中…" : "追加"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AutoRelockTimer({ lastUnlockedAt, autoRelockSec, onExpired }: {
  lastUnlockedAt: string | null; autoRelockSec: number; onExpired: () => void;
}) {
  const [remaining, setRemaining] = useState(autoRelockSec);

  useEffect(() => {
    if (!lastUnlockedAt || autoRelockSec <= 0) return;
    const update = () => {
      const elapsed = (Date.now() - new Date(lastUnlockedAt).getTime()) / 1000;
      const rem = Math.max(0, autoRelockSec - elapsed);
      setRemaining(rem);
      if (rem <= 0) onExpired();
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastUnlockedAt, autoRelockSec]);

  if (autoRelockSec <= 0) return null;

  return (
    <div style={{ padding: "10px 14px", background: "#f7ecd9", borderRadius: 7, border: "1px solid #b8763a", display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#b8763a" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
      <span style={{ fontSize: 12, color: "#b8763a", fontWeight: 500 }}>自動施錠まで {Math.ceil(remaining)}秒</span>
    </div>
  );
}

export default function AdminLockerPage() {
  const router = useRouter();
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { clearTokens(); router.push("/login"); return; }
    api.listLockers(token)
      .then((data) => {
        setLockers(data);
        if (data.length > 0) setSelectedId(data[0].id);
      })
      .catch(() => { clearTokens(); router.push("/login"); })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sel = selectedId ? lockers.find((l) => l.id === selectedId) ?? null : null;

  const counts = {
    locked:   lockers.filter((l) => l.state === "locked").length,
    unlocked: lockers.filter((l) => l.state === "unlocked").length,
    error:    lockers.filter((l) => l.state === "error").length,
  };

  async function handleUnlock() {
    if (!sel) return;
    const token = getAccessToken();
    if (!token) { clearTokens(); router.push("/login"); return; }
    setActionLoading(true);
    try {
      await api.unlockLocker(token, sel.id);
      setLockers((prev) => prev.map((l) => l.id === sel.id ? { ...l, state: "unlocked", last_unlocked_at: new Date().toISOString() } : l));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleLock() {
    if (!sel) return;
    const token = getAccessToken();
    if (!token) { clearTokens(); router.push("/login"); return; }
    setActionLoading(true);
    try {
      await api.lockLocker(token, sel.id);
      setLockers((prev) => prev.map((l) => l.id === sel.id ? { ...l, state: "locked" } : l));
    } finally {
      setActionLoading(false);
    }
  }

  async function handleAdd(door_number: number, auto_relock_sec: number) {
    const token = getAccessToken();
    if (!token) throw new Error("ログインが必要です");
    const created = await api.createLocker(token, door_number, auto_relock_sec);
    setLockers((prev) => [...prev, created].sort((a, b) => a.door_number - b.door_number));
    setSelectedId(created.id);
  }

  async function handleDelete(id: string) {
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deleteLocker(token, id);
      setLockers((prev) => prev.filter((l) => l.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  }

  const handleAutoLocked = useCallback((id: string) => {
    setLockers((prev) => prev.map((l) => l.id === id ? { ...l, state: "locked" } : l));
  }, []);

  if (loading) {
    return (
      <AdminShell active="locker" title="スマートロッカー" breadcrumb="ホーム / ロッカー" subtitle="読み込み中...">
        <div style={{ textAlign: "center", color: "#a8a198", fontSize: 13, padding: "60px 0" }}>ロッカー情報を取得中...</div>
      </AdminShell>
    );
  }

  return (
    <AdminShell
      active="locker"
      title="スマートロッカー"
      breadcrumb="ホーム / ロッカー"
      subtitle={`${lockers.length}扉`}
      actions={
        <MkBtn variant="primary" size="sm" onClick={() => setShowAddModal(true)}>
          + ロッカーを追加
        </MkBtn>
      }
    >
      {error && (
        <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 8, background: "none", border: "none", cursor: "pointer", color: "#a84238", fontSize: 11 }}>✕</button>
        </div>
      )}

      {/* Stats */}
      <div style={{ display: "flex", gap: 14, marginBottom: 20 }}>
        {[
          { label: "施錠中", value: counts.locked,   color: "#2d2a24" },
          { label: "開錠中", value: counts.unlocked,  color: "#3a6240" },
          { label: "使用中", value: 0,                color: "#b8763a" },
          { label: "異常",   value: counts.error,     color: "#a84238" },
        ].map(({ label, value, color }) => (
          <MkCard key={label} padding={14} style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, color, marginTop: 4, letterSpacing: "-0.6px" }}>{value}</div>
          </MkCard>
        ))}
      </div>

      {lockers.length === 0 ? (
        <MkCard>
          <div style={{ textAlign: "center", color: "#a8a198", fontSize: 12, padding: "40px 0" }}>
            ロッカーが登録されていません。<br />
            「ロッカーを追加」ボタンで追加してください。
          </div>
        </MkCard>
      ) : (
        <div className="adm-grid-locker" style={{ gap: 20 }}>
          <MkCard>
            <MkSectionTitle
              title="ロッカー一覧"
              subtitle="クリックで詳細"
              action={
                <div style={{ display: "flex", gap: 4, background: "#f4f1ea", borderRadius: 7, padding: 2 }}>
                  <button
                    onClick={() => setViewMode("grid")}
                    style={{ padding: "5px 10px", borderRadius: 5, border: "none", background: viewMode === "grid" ? "#fffefb" : "transparent", cursor: "pointer", fontSize: 11, color: viewMode === "grid" ? "#1d1a15" : "#a8a198" }}
                  >グリッド</button>
                  <button
                    onClick={() => setViewMode("list")}
                    style={{ padding: "5px 10px", borderRadius: 5, border: "none", background: viewMode === "list" ? "#fffefb" : "transparent", cursor: "pointer", fontSize: 11, color: viewMode === "list" ? "#1d1a15" : "#a8a198" }}
                  >リスト</button>
                </div>
              }
            />
            {viewMode === "grid" ? (
              <div className="adm-grid-5" style={{ gap: 10 }}>
                {lockers.map((l) => {
                  const uiState = toUIState(l.state);
                  const s = STATE_MAP[uiState];
                  const isSelected = selectedId === l.id;
                  return (
                    <div
                      key={l.id}
                      onClick={() => setSelectedId(l.id)}
                      style={{
                        aspectRatio: "3/4",
                        background: s.bg,
                        border: `${isSelected ? "2.5px" : "1.5px"} solid ${isSelected ? "#1d1a15" : s.border}`,
                        borderRadius: 7, padding: 10,
                        display: "flex", flexDirection: "column",
                        cursor: "pointer", position: "relative",
                      }}
                    >
                      <div style={{ fontSize: 11, color: s.fg, fontFamily: "monospace", fontWeight: 600, letterSpacing: "0.5px" }}>
                        {String(l.door_number).padStart(2, "0")}
                      </div>
                      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <LockIcon unlocked={s.icon === "unlock"} color={s.fg} />
                      </div>
                      <div style={{ fontSize: 10, color: s.fg, fontWeight: 600, textAlign: "center" }}>{s.label}</div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div>
                {lockers.map((l, i) => {
                  const uiState = toUIState(l.state);
                  const s = STATE_MAP[uiState];
                  const isSelected = selectedId === l.id;
                  return (
                    <div
                      key={l.id}
                      onClick={() => setSelectedId(l.id)}
                      style={{
                        display: "flex", alignItems: "center", gap: 12,
                        padding: "10px 12px",
                        borderTop: i > 0 ? "1px solid #efece5" : "none",
                        background: isSelected ? "#eaf0e8" : "transparent",
                        borderRadius: isSelected ? 7 : 0,
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ width: 32, height: 32, borderRadius: 6, background: s.bg, border: `1.5px solid ${s.border}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <LockIcon unlocked={s.icon === "unlock"} color={s.fg} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#2d2a24", fontFamily: "monospace" }}>
                          扉 {String(l.door_number).padStart(2, "0")}
                        </div>
                        <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2 }}>
                          {l.auto_relock_sec > 0 ? `自動施錠: ${l.auto_relock_sec}秒` : "自動施錠なし"}
                        </div>
                      </div>
                      <MkPill tone={l.state === "unlocked" ? "live" : l.state === "error" ? "error" : "neutral"}>{s.label}</MkPill>
                    </div>
                  );
                })}
              </div>
            )}
          </MkCard>

          <MkCard>
            {sel ? (
              <>
                <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", letterSpacing: "0.4px" }}>選択中の扉</div>
                <div style={{ fontSize: 28, fontWeight: 600, color: "#1d1a15", marginTop: 4, letterSpacing: "-0.8px" }}>
                  ロッカー {String(sel.door_number).padStart(2, "0")}
                </div>
                <MkPill tone={sel.state === "unlocked" ? "live" : sel.state === "error" ? "error" : "neutral"}>
                  {STATE_MAP[toUIState(sel.state)].label}
                </MkPill>

                {sel.state === "unlocked" && sel.auto_relock_sec > 0 && (
                  <AutoRelockTimer
                    lastUnlockedAt={sel.last_unlocked_at}
                    autoRelockSec={sel.auto_relock_sec}
                    onExpired={() => handleAutoLocked(sel.id)}
                  />
                )}

                <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid #efece5" }}>
                  {[
                    { label: "扉ID",      value: sel.id,                                                    mono: true },
                    { label: "開錠時刻",   value: sel.last_unlocked_at ? new Date(sel.last_unlocked_at).toLocaleString("ja-JP") : "—", mono: true },
                    { label: "自動施錠",   value: sel.auto_relock_sec > 0 ? `${sel.auto_relock_sec}秒` : "なし", mono: true },
                    { label: "発行日",     value: "—", mono: false },
                  ].map((r, i) => (
                    <div key={i} style={{ display: "flex", padding: "8px 0", borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                      <span style={{ flex: 1, fontSize: 11.5, color: "#a8a198" }}>{r.label}</span>
                      <span style={{ fontSize: 12, color: "#2d2a24", fontWeight: 500, fontFamily: r.mono ? "monospace" : undefined }}>{r.value}</span>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 8 }}>
                  {sel.state === "locked" && (
                    <MkBtn variant="primary" onClick={handleUnlock} disabled={actionLoading}>
                      {actionLoading ? "処理中..." : "今すぐ開錠"}
                    </MkBtn>
                  )}
                  {sel.state === "unlocked" && (
                    <MkBtn variant="default" onClick={handleLock} disabled={actionLoading}>
                      {actionLoading ? "処理中..." : "施錠する"}
                    </MkBtn>
                  )}
                  <MkBtn variant="ghost" style={{ color: "#a84238" }} onClick={() => setDeleteTarget(sel.id)}>
                    このロッカーを削除
                  </MkBtn>
                </div>
              </>
            ) : (
              <div style={{ textAlign: "center", color: "#a8a198", fontSize: 12, padding: "40px 0" }}>
                ロッカーを選択してください
              </div>
            )}
          </MkCard>
        </div>
      )}

      <AddLockerModal open={showAddModal} onClose={() => setShowAddModal(false)} onAdd={handleAdd} />
      <ConfirmDialog
        open={deleteTarget !== null}
        title="ロッカーを削除しますか？"
        description={`扉 ${String(lockers.find((l) => l.id === deleteTarget)?.door_number ?? "").padStart(2, "0")} を削除します。この操作は取り消せません。`}
        onConfirm={async () => { if (deleteTarget) { await handleDelete(deleteTarget); setDeleteTarget(null); } }}
        onCancel={() => setDeleteTarget(null)}
        danger
      />
    </AdminShell>
  );
}

function LockIcon({ unlocked, color }: { unlocked: boolean; color: string }) {
  return unlocked ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="10" rx="2"/>
      <path d="M8 11V7a4 4 0 017.3-2.3"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="10" rx="2"/>
      <path d="M8 11V7a4 4 0 018 0v4"/>
    </svg>
  );
}
