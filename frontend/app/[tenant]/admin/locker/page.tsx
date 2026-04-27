"use client";

import { useState, useEffect } from "react";
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

export default function AdminLockerPage() {
  const router = useRouter();
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      clearTokens();
      router.push("/login");
      return;
    }
    api.listLockers(token)
      .then((data) => {
        setLockers(data);
        if (data.length > 0) setSelectedId(data[0].id);
      })
      .catch(() => {
        clearTokens();
        router.push("/login");
      })
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
      setLockers((prev) => prev.map((l) => l.id === sel.id ? { ...l, state: "unlocked" } : l));
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

  if (loading) {
    return (
      <AdminShell active="locker" title="スマートロッカー" breadcrumb="ホーム / ロッカー" subtitle="読み込み中...">
        <div style={{ textAlign: "center", color: "#a8a198", fontSize: 13, padding: "60px 0" }}>ロッカー情報を取得中...</div>
      </AdminShell>
    );
  }

  if (error) {
    return (
      <AdminShell active="locker" title="スマートロッカー" breadcrumb="ホーム / ロッカー" subtitle="エラー">
        <div style={{ textAlign: "center", color: "#a84238", fontSize: 13, padding: "60px 0" }}>{error}</div>
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
        <MkBtn variant="default" size="sm">タイマー設定</MkBtn>
      }
    >
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
            ロッカーが登録されていません。管理者にお問い合わせください。
          </div>
        </MkCard>
      ) : (
        <div className="adm-grid-locker" style={{ gap: 20 }}>
          <MkCard>
            <MkSectionTitle
              title="ロッカー一覧"
              subtitle="クリックで詳細"
              action={<MkBtn size="sm" variant="ghost">レイアウト表示</MkBtn>}
            />
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
                      borderRadius: 7,
                      padding: 10,
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

                <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid #efece5" }}>
                  {[
                    { label: "扉ID",          value: sel.id,                                              mono: true },
                    { label: "開錠者",         value: "—",                                                mono: false },
                    { label: "開錠時刻",       value: sel.last_unlocked_at ? new Date(sel.last_unlocked_at).toLocaleString("ja-JP") : "—", mono: true },
                    { label: "自動再施錠",     value: sel.auto_relock_sec ? `${sel.auto_relock_sec}秒` : "—", mono: true },
                    { label: "扉センサー",     value: "—",                                                mono: false },
                    { label: "ハードウェア",   value: "—",                                                mono: false },
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
                  <MkBtn variant="ghost" onClick={() => {}}>開錠履歴を見る</MkBtn>
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

      <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559" }}>
        このページは Phase 2 で Raspberry Pi との実際の連携が実装されます。現在は UI プレビューのみです。
      </div>
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
