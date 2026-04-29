"use client";

import { useRouter, useParams } from "next/navigation";
import { clearTokens } from "@/lib/auth";
import { useState } from "react";
import type { ReactNode } from "react";

export type NavId = "dashboard" | "media" | "playlist" | "schedule" | "device" | "reception" | "notify" | "locker" | "kiosk_settings" | "settings" | "users";

interface Props {
  active: NavId;
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  actions?: ReactNode;
  children: ReactNode;
}

const NAV_OPS: { id: NavId; label: string }[] = [
  { id: "dashboard", label: "ダッシュボード" },
  { id: "media",     label: "メディア" },
  { id: "playlist",  label: "プレイリスト" },
  { id: "schedule",  label: "スケジュール" },
  { id: "device",    label: "キオスク端末" },
  { id: "reception", label: "受付ログ" },
];

const NAV_SETTINGS: { id: NavId; label: string }[] = [
  { id: "notify",         label: "通知設定" },
  { id: "locker",         label: "ロッカー" },
  { id: "kiosk_settings", label: "受付設定" },
  { id: "settings",       label: "基本設定" },
  { id: "users",          label: "ユーザー管理" },
];

const NAV_PATHS: Record<NavId, (t: string) => string> = {
  dashboard:     (t) => `/${t}/admin`,
  media:         (t) => `/${t}/admin/media`,
  playlist:      (t) => `/${t}/admin/playlists`,
  schedule:      (t) => `/${t}/admin/schedules`,
  device:        (t) => `/${t}/admin/kiosk`,
  reception:     (t) => `/${t}/admin/reception`,
  notify:        (t) => `/${t}/admin/notify`,
  locker:        (t) => `/${t}/admin/locker`,
  kiosk_settings:(t) => `/${t}/admin/kiosk-settings`,
  settings:      (t) => `/${t}/admin/settings`,
  users:         (t) => `/${t}/admin/users`,
};

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, "Noto Sans JP", sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

export function AdminShell({ active, title, subtitle, breadcrumb, actions, children }: Props) {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const tenant = params.tenant ?? "";
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "#faf8f4", fontFamily: FONT_UI }}>
      {/* ─ Overlay (mobile) ─────────────────────────────────── */}
      {sidebarOpen && (
        <div className="adm-sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ─ Sidebar ──────────────────────────────────────────── */}
      <aside
        className={`adm-sidebar${sidebarOpen ? " open" : ""}`}
      >
        {/* Brand */}
        <div style={{ padding: "22px 20px 18px", display: "flex", alignItems: "center", gap: 10, borderBottom: "1px solid #efece5" }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "#1d1a15", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="9" r="5"/>
              <path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/>
              <path d="M12 4v10"/>
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.2px" }}>
              mokuture<span style={{ color: "#4a7c4e" }}>+</span>
            </div>
            <div style={{ fontSize: 10.5, color: "#a8a198", letterSpacing: "0.4px", textTransform: "uppercase", fontFamily: FONT_MONO }}>
              CMS console
            </div>
          </div>
          {/* Close button (mobile only) */}
          <button
            className="adm-hamburger"
            onClick={() => setSidebarOpen(false)}
            aria-label="メニューを閉じる"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* Tenant switcher */}
        <div style={{ padding: "14px 16px 8px" }}>
          <button style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "8px 10px", background: "#f4f1ea", border: "1px solid #efece5",
            borderRadius: 7, cursor: "pointer", fontFamily: FONT_UI, textAlign: "left",
          }}>
            <div style={{ width: 22, height: 22, borderRadius: 5, background: "#4a7c4e", color: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>
              {tenant[0]?.toUpperCase() ?? "T"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#2d2a24", lineHeight: 1.2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{tenant}</div>
              <div style={{ fontSize: 10, color: "#a8a198", fontFamily: FONT_MONO }}>TENANT · {tenant}</div>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav style={{ padding: "10px 10px", flex: 1, overflow: "auto" }}>
          <div style={{ fontSize: 10.5, color: "#a8a198", textTransform: "uppercase", letterSpacing: "0.6px", padding: "8px 10px 6px" }}>
            運用
          </div>
          {NAV_OPS.map((item) => (
            <NavItem key={item.id} id={item.id} label={item.label} active={active === item.id} onClick={() => router.push(NAV_PATHS[item.id](tenant))} />
          ))}
          <div style={{ fontSize: 10.5, color: "#a8a198", textTransform: "uppercase", letterSpacing: "0.6px", padding: "14px 10px 6px" }}>
            設定
          </div>
          {NAV_SETTINGS.map((item) => (
            <NavItem key={item.id} id={item.id} label={item.label} active={active === item.id} onClick={() => router.push(NAV_PATHS[item.id](tenant))} />
          ))}
        </nav>

        {/* User footer */}
        <div style={{ borderTop: "1px solid #efece5" }}>
          <div style={{ padding: "12px 12px 8px", display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#f7ecd9", color: "#b8763a", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, flexShrink: 0 }}>
              {tenant[0]?.toUpperCase() ?? "A"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#2d2a24" }}>管理者</div>
              <div style={{ fontSize: 10.5, color: "#a8a198" }}>管理者 · admin</div>
            </div>
          </div>
          <button
            onClick={() => { clearTokens(); router.push("/login"); }}
            style={{
              width: "100%", display: "flex", alignItems: "center", gap: 8,
              padding: "9px 14px", background: "none", border: "none",
              borderTop: "1px solid #efece5", cursor: "pointer",
              color: "#6b6559", fontSize: 12.5, fontFamily: FONT_JP,
              textAlign: "left",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>
            </svg>
            ログアウト
          </button>
        </div>
      </aside>

      {/* ─ Main ────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* TopBar */}
        <div className="adm-topbar" style={{ borderBottom: "1px solid #efece5", background: "#fffefb", display: "flex", alignItems: "center", gap: 8 }}>
          {/* Hamburger (mobile only) */}
          <button className="adm-hamburger" onClick={() => setSidebarOpen(true)} aria-label="メニューを開く">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            {breadcrumb && (
              <div style={{ fontSize: 11.5, color: "#a8a198", marginBottom: 4, fontFamily: FONT_JP, letterSpacing: "0.2px" }}>
                {breadcrumb}
              </div>
            )}
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.3px", fontFamily: FONT_JP, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {title}
            </h1>
            {subtitle && (
              <div style={{ fontSize: 13, color: "#6b6559", marginTop: 4, fontFamily: FONT_JP }}>
                {subtitle}
              </div>
            )}
          </div>
          {actions && <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>{actions}</div>}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto adm-content">
          {children}
        </div>
      </div>
    </div>
  );
}

function NavItem({ id, label, active, onClick }: { id: NavId; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 10,
        padding: active ? "8px 10px 8px 12px" : "8px 10px",
        borderRadius: 7, marginBottom: 1,
        background: active ? "#eaf0e8" : "transparent",
        color: active ? "#3a6240" : "#6b6559",
        fontSize: 13, fontWeight: active ? 600 : 500,
        cursor: "pointer", textAlign: "left",
        borderLeft: `2px solid ${active ? "#4a7c4e" : "transparent"}`,
        border: "none", fontFamily: FONT_JP,
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
      onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
    >
      <NavIcon id={id} active={active} />
      <span>{label}</span>
    </button>
  );
}

/* ─ Shared UI primitives ──────────────────────────────────── */

export function MkBtn({
  variant = "default",
  size = "md",
  children,
  onClick,
  disabled,
  type = "button",
  style,
}: {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
  children: ReactNode;
  onClick?: (e?: React.MouseEvent) => void;
  disabled?: boolean;
  type?: "button" | "submit";
  style?: React.CSSProperties;
}) {
  const sizes = {
    sm: { padding: "5px 10px", fontSize: 11.5 },
    md: { padding: "8px 14px", fontSize: 12.5 },
  }[size];
  const variants = {
    primary: { bg: "#4a7c4e", color: "#fffefb", border: "#4a7c4e" },
    default: { bg: "#fffefb", color: "#2d2a24", border: "#d8d3c7" },
    ghost:   { bg: "transparent", color: "#6b6559", border: "transparent" },
    danger:  { bg: "#fffefb", color: "#a84238", border: "#d8d3c7" },
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7,
        padding: sizes.padding, fontSize: sizes.fontSize, fontWeight: 500,
        background: variants.bg, color: variants.color,
        border: `1px solid ${variants.border}`, borderRadius: 7,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontFamily: FONT_JP, letterSpacing: "0.1px",
        transition: "opacity 0.1s",
        boxShadow: variant === "primary" ? "0 1px 0 rgba(29,26,21,0.08)" : "none",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

export function MkCard({
  children,
  padding = "20px",
  style,
  id,
}: {
  children: ReactNode;
  padding?: string | number;
  style?: React.CSSProperties;
  id?: string;
}) {
  return (
    <div
      id={id}
      style={{
        background: "#fffefb",
        border: "1px solid #efece5",
        borderRadius: 10,
        padding,
        boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
        fontFamily: FONT_JP,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function MkPill({ tone, children, dot = true }: { tone: "live" | "warn" | "off" | "error" | "info" | "neutral"; children: ReactNode; dot?: boolean }) {
  const tones = {
    live:    { bg: "#eaf0e8", fg: "#3a6240", dot: "#4a7c4e" },
    warn:    { bg: "#f7ecd9", fg: "#b8763a", dot: "#b8763a" },
    off:     { bg: "#f4f1ea", fg: "#6b6559", dot: "#a8a198" },
    error:   { bg: "#f6e0dc", fg: "#a84238", dot: "#a84238" },
    info:    { bg: "#e4eef5", fg: "#2e6b8e", dot: "#2e6b8e" },
    neutral: { bg: "#f4f1ea", fg: "#6b6559", dot: "#a8a198" },
  }[tone];
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "3px 8px", borderRadius: 999, background: tones.bg, color: tones.fg,
        fontSize: 10.5, fontWeight: 600, fontFamily: FONT_JP, letterSpacing: "0.2px",
        whiteSpace: "nowrap",
      }}
    >
      {dot && <span style={{ width: 5, height: 5, borderRadius: "50%", background: tones.dot, flexShrink: 0 }} />}
      {children}
    </span>
  );
}

export function MkSectionTitle({ title, subtitle, action, style }: { title: string; subtitle?: string; action?: ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", marginBottom: 14, gap: 16, ...style }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, letterSpacing: "-0.1px" }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3, fontFamily: FONT_JP }}>{subtitle}</div>}
      </div>
      {action}
    </div>
  );
}

/* Nav icons */
function NavIcon({ id, active }: { id: NavId; active: boolean }) {
  const color = active ? "#3a6240" : "#a8a198";
  const stroke = active ? 1.8 : 1.6;
  const w = 17;
  switch (id) {
    case "dashboard":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>
      </svg>;
    case "media":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M3 16l5-4 4 3 4-4 5 4"/>
      </svg>;
    case "playlist":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 6h10M4 12h10M4 18h6"/><path d="M17 14l5 3-5 3z" fill={color} stroke="none"/>
      </svg>;
    case "schedule":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>
      </svg>;
    case "device":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>;
    case "reception":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 21v-2a4 4 0 014-4h8a4 4 0 014 4v2"/><circle cx="12" cy="8" r="4"/>
      </svg>;
    case "notify":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 8a6 6 0 0112 0v5l2 3H4l2-3z"/><path d="M10 19a2 2 0 004 0"/>
      </svg>;
    case "locker":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="1.5"/><path d="M3 12h18M12 3v18"/><circle cx="8" cy="8" r="0.8" fill={color}/><circle cx="8" cy="16" r="0.8" fill={color}/><circle cx="16" cy="8" r="0.8" fill={color}/><circle cx="16" cy="16" r="0.8" fill={color}/>
      </svg>;
    case "kiosk_settings":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>
        <path d="M7 10h2M11 10h6M7 13h4"/>
      </svg>;
    case "settings":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 010 4h-.1a1.7 1.7 0 00-1.5 1z"/>
      </svg>;
    case "users":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
      </svg>;
  }
}
