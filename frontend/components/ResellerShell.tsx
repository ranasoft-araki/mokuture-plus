"use client";

import { useRouter, usePathname, useParams } from "next/navigation";
import { clearTokens, getLogoutUrl, getAccessToken } from "@/lib/auth";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

export function ResellerShell({ children, receptionUnread: receptionUnreadProp }: { children: ReactNode; receptionUnread?: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [receptionUnread, setReceptionUnread] = useState<number>(receptionUnreadProp ?? 0);

  useEffect(() => {
    if (receptionUnreadProp !== undefined) {
      setReceptionUnread(receptionUnreadProp);
      return;
    }
    const token = getAccessToken();
    if (!token) return;
    api.listResellerReception(token, { status: "received", limit: 100 })
      .then((data) => setReceptionUnread(data.length))
      .catch(() => {});
  }, [receptionUnreadProp]);

  const NAV_ITEMS = [
    { id: "dashboard", label: "ダッシュボード", path: `/${tenant}/reseller` },
    { id: "customers", label: "顧客管理", path: `/${tenant}/reseller/customers` },
    { id: "users", label: "ユーザー管理", path: `/${tenant}/reseller/users` },
    { id: "devices", label: "デバイス管理", path: `/${tenant}/reseller/devices` },
    { id: "reception", label: "受付ログ", path: `/${tenant}/reseller/reception` },
    { id: "settings", label: "設定", path: `/${tenant}/reseller/settings` },
    { id: "profile", label: "アカウント", path: `/${tenant}/reseller/profile` },
  ];

  const getActive = () => {
    if (pathname === `/${tenant}/reseller`) return "dashboard";
    for (const item of NAV_ITEMS) {
      if (pathname.startsWith(item.path) && item.path !== `/${tenant}/reseller`) return item.id;
    }
    return "dashboard";
  };

  const active = getActive();
  const pageTitle = NAV_ITEMS.find((n) => n.id === active)?.label ?? "ダッシュボード";

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "#faf8f4", fontFamily: FONT_UI }}>
      {/* Sidebar */}
      <aside style={{ width: 248, background: "#fffefb", borderRight: "1px solid #efece5", display: "flex", flexDirection: "column", height: "100%", flexShrink: 0 }}>
        {/* Brand */}
        <div style={{ padding: "22px 20px 18px", display: "flex", alignItems: "center", gap: 10, borderBottom: "1px solid #efece5" }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/><path d="M12 4v10"/></svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.2px" }}>mokuture<span style={{ color: "#4a7c4e" }}>+</span></div>
            <div style={{ fontSize: 10.5, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase" as const, fontFamily: FONT_MONO }}>パートナー</div>
          </div>
        </div>

        {/* Tenant badge */}
        <div style={{ padding: "12px 16px 8px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: "#f4f1ea", border: "1px solid #efece5", borderRadius: 7 }}>
            <div style={{ width: 22, height: 22, borderRadius: 5, background: "#b8763a", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>
              {tenant[0]?.toUpperCase() ?? "P"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#2d2a24", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>{tenant}</div>
              <div style={{ fontSize: 10, color: "#a8a198", fontFamily: FONT_MONO }}>PARTNER · {tenant}</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: "10px 10px", flex: 1, overflow: "auto" }}>
          <div style={{ fontSize: 10.5, color: "#a8a198", textTransform: "uppercase" as const, letterSpacing: "0.6px", padding: "8px 10px 6px" }}>管理</div>
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
                  background: isActive ? "#fdf3e4" : "transparent",
                  color: isActive ? "#8a5a1e" : "#6b6559",
                  fontSize: 13, fontWeight: isActive ? 600 : 500,
                  cursor: "pointer", textAlign: "left" as const,
                  borderLeft: `2px solid ${isActive ? "#b8763a" : "transparent"}`,
                  border: "none", fontFamily: FONT_JP,
                }}
                onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
                onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
              >
                <ResellerNavIcon id={item.id} active={isActive} />
                <span style={{ flex: 1 }}>{item.label}</span>
                {item.id === "reception" && receptionUnread > 0 && (
                  <span style={{
                    background: "#c8a96e", color: "#1d1a15",
                    borderRadius: 999, fontSize: 10, fontWeight: 700,
                    padding: "1px 5px", minWidth: 16, textAlign: "center",
                    marginLeft: 4, lineHeight: "14px", display: "inline-block",
                  }}>
                    {receptionUnread > 99 ? "99+" : receptionUnread}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div style={{ borderTop: "1px solid #efece5" }}>
          <button
            onClick={() => { clearTokens(); router.push(getLogoutUrl()); }}
            style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "12px 14px", background: "none", border: "none", borderTop: "1px solid #efece5", cursor: "pointer", color: "#6b6559", fontSize: 12.5, fontFamily: FONT_JP, textAlign: "left" as const }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
            ログアウト
          </button>
        </div>
      </aside>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ background: "#fffefb", borderBottom: "1px solid #efece5", padding: "16px 32px", display: "flex", alignItems: "center" }}>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.3px", fontFamily: FONT_JP }}>{pageTitle}</h1>
          <span style={{ marginLeft: "auto", fontSize: 11, padding: "4px 9px", border: "1px solid #e2ddd6", borderRadius: 4, color: "#b8763a", fontFamily: FONT_MONO, letterSpacing: 1 }}>PARTNER</span>
        </div>
        <div style={{ flex: 1, overflow: "auto" }}>{children}</div>
      </div>
    </div>
  );
}

function ResellerNavIcon({ id, active }: { id: string; active: boolean }) {
  const color = active ? "#8a5a1e" : "#a8a198";
  const w = 17;
  const sw = active ? 1.8 : 1.6;
  switch (id) {
    case "dashboard": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>;
    case "customers": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>;
    case "users": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>;
    case "devices": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>;
    case "reception": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/></svg>;
    case "settings": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/></svg>;
    case "profile": return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>;
    default: return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/></svg>;
  }
}
