"use client";

import { useState } from "react";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";

type LockerState = "idle" | "unlocked" | "occupied" | "fault";

const STATE_MAP: Record<LockerState, { bg: string; fg: string; border: string; label: string; icon: "lock" | "unlock" }> = {
  idle:     { bg: "#fffefb", fg: "#2d2a24", border: "#d8d3c7",  label: "施錠",   icon: "lock" },
  unlocked: { bg: "#eaf0e8", fg: "#3a6240", border: "#4a7c4e",  label: "開錠中", icon: "unlock" },
  occupied: { bg: "#f7ecd9", fg: "#b8763a", border: "#b8763a",  label: "使用中", icon: "lock" },
  fault:    { bg: "#f6e0dc", fg: "#a84238", border: "#a84238",  label: "異常",   icon: "lock" },
};

const LOCKER_STATES: LockerState[] = [
  "idle","idle","idle","idle","unlocked","idle","idle","occupied","idle","idle",
  "idle","idle","unlocked","idle","fault","idle","idle","idle","idle","occupied",
];

export default function AdminLockerPage() {
  const [selected, setSelected] = useState<number | null>(4);

  const lockers = LOCKER_STATES.map((state, i) => ({ n: i + 1, state }));

  const counts = {
    idle:     lockers.filter((l) => l.state === "idle").length,
    unlocked: lockers.filter((l) => l.state === "unlocked").length,
    occupied: lockers.filter((l) => l.state === "occupied").length,
    fault:    lockers.filter((l) => l.state === "fault").length,
  };

  const sel = selected !== null ? lockers[selected - 1] : null;

  return (
    <AdminShell
      active="locker"
      title="スマートロッカー"
      breadcrumb="ホーム / ロッカー"
      subtitle="20扉 · 自動再施錠タイマー 180秒 · Raspberry Pi 01 制御"
      actions={
        <>
          <MkBtn variant="default" size="sm">タイマー設定</MkBtn>
          <MkBtn variant="danger" size="sm">全扉 緊急施錠</MkBtn>
        </>
      }
    >
      {/* Stats */}
      <div style={{ display: "flex", gap: 14, marginBottom: 20 }}>
        {[
          { label: "施錠中", value: counts.idle,     color: "#2d2a24" },
          { label: "開錠中", value: counts.unlocked, color: "#3a6240" },
          { label: "使用中", value: counts.occupied, color: "#b8763a" },
          { label: "異常",   value: counts.fault,    color: "#a84238" },
        ].map(({ label, value, color }) => (
          <MkCard key={label} padding={14} style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#a8a198" }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, color, marginTop: 4, letterSpacing: "-0.6px" }}>{value}</div>
          </MkCard>
        ))}
      </div>

      <div className="adm-grid-locker" style={{ gap: 20 }}>
        <MkCard>
          <MkSectionTitle
            title="ロッカー一覧"
            subtitle="クリックで詳細 · ダブルクリックで開錠"
            action={<MkBtn size="sm" variant="ghost">レイアウト表示</MkBtn>}
          />
          <div className="adm-grid-5" style={{ gap: 10 }}>
            {lockers.map((l) => {
              const s = STATE_MAP[l.state];
              const isSelected = selected === l.n;
              return (
                <div
                  key={l.n}
                  onClick={() => setSelected(l.n)}
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
                    {String(l.n).padStart(2, "0")}
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

        {/* Selected detail */}
        <MkCard>
          {sel ? (
            <>
              <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", letterSpacing: "0.4px" }}>選択中の扉</div>
              <div style={{ fontSize: 28, fontWeight: 600, color: "#1d1a15", marginTop: 4, letterSpacing: "-0.8px" }}>
                ロッカー {String(sel.n).padStart(2, "0")}
              </div>
              <MkPill tone={sel.state === "unlocked" ? "live" : sel.state === "occupied" ? "warn" : sel.state === "fault" ? "error" : "neutral"}>
                {STATE_MAP[sel.state].label}
              </MkPill>

              <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid #efece5" }}>
                {[
                  { label: "扉ID",          value: `LK-HQ-${String(sel.n).padStart(2, "0")}`, mono: true },
                  { label: "開錠者",         value: "—",                                        mono: false },
                  { label: "開錠時刻",       value: "—",                                        mono: true },
                  { label: "残り再施錠まで", value: "—",                                        mono: true },
                  { label: "扉センサー",     value: "閉じています",                               mono: false },
                  { label: "ハードウェア",   value: "美和ロック ALU-AI",                          mono: false },
                ].map((r, i) => (
                  <div key={i} style={{ display: "flex", padding: "8px 0", borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                    <span style={{ flex: 1, fontSize: 11.5, color: "#a8a198" }}>{r.label}</span>
                    <span style={{ fontSize: 12, color: "#2d2a24", fontWeight: 500, fontFamily: r.mono ? "monospace" : undefined }}>{r.value}</span>
                  </div>
                ))}
              </div>

              <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 8 }}>
                <MkBtn variant="primary" onClick={() => {}}>今すぐ開錠</MkBtn>
                <MkBtn variant="default" onClick={() => {}}>タイマー延長 (+60s)</MkBtn>
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
