"use client";

import { useRouter, usePathname } from "next/navigation";
import { clearTokens } from "@/lib/auth";
import type { ReactNode } from "react";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

const NAV_ITEMS = [
  { id: "dashboard", label: "ダッシュボード", path: "/operator", icon: "dashboard" },
  { id: "tenants", label: "テナント管理", path: "/operator/tenants", icon: "tenant" },
  { id: "resellers", label: "代理店管理", path: "/operator/resellers", icon: "reseller" },
  { id: "users", label: "ユーザー管理", path: "/operator/users", icon: "user" },
  { id: "devices", label: "デバイス管理", path: "/operator/devices", icon: "device" },
  { id: "reception", label: "受付ログ", path: "/operator/reception", icon: "reception" },
  { id: "broadcast", label: "緊急配信", path: "/operator/broadcast", icon: "broadcast" },
] as const;

export function OperatorShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const getActive = () => {
    if (pathname === "/operator") return "dashboard";
    for (const item of NAV_ITEMS) {
      if (pathname.startsWith(item.path) && item.path !== "/operator") return item.id;
    }
    return "dashboard";
  };

  const active = getActive();

  const pageTitle = NAV_ITEMS.find((n) => n.id === active)?.label ?? "ダッシュボード";

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "#0e0c08", fontFamily: FONT_UI }}>
      {/* Sidebar */}
      <aside style={{ width: 248, background: "#141210", borderRight: "1px solid rgba(255,255,255,0.06)", display: "flex", flexDirection: "column", height: "100%", flexShrink: 0 }}>
        {/* Brand */}
        <div style={{ padding: "22px 20px 18px", display: "flex", alignItems: "center", gap: 10, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "#4a7c4e", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/><path d="M12 4v10"/></svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#fffefb", letterSpacing: "-0.2px" }}>mokuture<span style={{ color: "#4a7c4e" }}>+</span></div>
            <div style={{ fontSize: 10.5, color: "rgba(255,255,255,0.35)", letterSpacing: "0.6px", textTransform: "uppercase" as const, fontFamily: FONT_MONO }}>OPS · CONSOLE</div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: "12px 10px", flex: 1, overflow: "auto" }}>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", textTransform: "uppercase" as const, letterSpacing: "0.8px", padding: "8px 10px 6px" }}>管理</div>
          {NAV_ITEMS.map((item) => {
            const isActive = active === item.id;
            return (
              <button
                key={item.id}
                onClick={() => router.push(item.path)}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: isActive ? "8px 10px 8px 12px" : "8px 10px",
                  borderRadius: 7, marginBottom: 1,
                  background: isActive ? "rgba(74,124,78,0.15)" : "transparent",
                  color: isActive ? "#7ec483" : "rgba(255,255,255,0.5)",
                  fontSize: 13, fontWeight: isActive ? 600 : 500,
                  cursor: "pointer", textAlign: "left" as const,
                  borderLeft: `2px solid ${isActive ? "#4a7c4e" : "transparent"}`,
                  border: "none", fontFamily: FONT_JP,
                }}
                onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.04)"; }}
                onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
              >
                <OperatorNavIcon id={item.icon} active={isActive} />
                <span>{item.label}</span>
                {item.id === "broadcast" && (
                  <span style={{ marginLeft: "auto", fontSize: 9, padding: "2px 6px", background: "rgba(168,66,56,0.25)", border: "1px solid rgba(168,66,56,0.4)", borderRadius: 4, color: "#e06060", fontFamily: FONT_MONO, letterSpacing: 0.5 }}>緊急</span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: 12 }}>
          <button
            onClick={() => { clearTokens(); router.push("/login"); }}
            style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", background: "none", border: "none", cursor: "pointer", color: "rgba(255,255,255,0.4)", fontSize: 12.5, fontFamily: FONT_JP, textAlign: "left" as const }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "rgba(255,255,255,0.7)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "rgba(255,255,255,0.4)"; }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
            ログアウト
          </button>
        </div>
      </aside>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* TopBar */}
        <div style={{ background: "#141210", borderBottom: "1px solid rgba(255,255,255,0.06)", padding: "16px 32px", display: "flex", alignItems: "center" }}>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: "#fffefb", letterSpacing: "-0.3px", fontFamily: FONT_JP }}>
            {pageTitle}
          </h1>
          <span style={{ marginLeft: "auto", fontSize: 11, padding: "4px 9px", border: "1px solid rgba(74,124,78,0.35)", borderRadius: 4, color: "#7ec483", fontFamily: FONT_MONO, letterSpacing: 1 }}>
            OPERATOR
          </span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: "auto", background: "#faf8f4" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

function OperatorNavIcon({ id, active }: { id: string; active: boolean }) {
  const color = active ? "#7ec483" : "rgba(255,255,255,0.35)";
  const w = 17;
  const sw = active ? 1.8 : 1.6;
  switch (id) {
    case "dashboard": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>;
    case "tenant": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>;
    case "reseller": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><circle cx="17" cy="21" r="1"/><circle cx="9" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 001.96 1.61h9.72a2 2 0 001.95-1.55L23 6H6"/></svg>;
    case "user": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>;
    case "device": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>;
    case "reception": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="9" y1="7" x2="15" y2="7"/><line x1="9" y1="11" x2="15" y2="11"/><line x1="9" y1="15" x2="12" y2="15"/></svg>;
    case "broadcast": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>;
    default: return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/></svg>;
  }
}
