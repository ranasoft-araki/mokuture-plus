"use client";

import { useRouter, useParams } from "next/navigation";
import { clearTokens } from "@/lib/auth";
import type { ReactNode } from "react";

export type NavId = "dashboard" | "media" | "playlist" | "schedule" | "device" | "reception";

interface Props {
  active: NavId;
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  actions?: ReactNode;
  children: ReactNode;
}

const NAV_ITEMS: { id: NavId; label: string }[] = [
  { id: "dashboard", label: "ダッシュボード" },
  { id: "media",     label: "メディア" },
  { id: "playlist",  label: "プレイリスト" },
  { id: "schedule",  label: "スケジュール" },
  { id: "device",    label: "キオスク端末" },
  { id: "reception", label: "受付ログ" },
];

const NAV_PATHS: Record<NavId, (t: string) => string> = {
  dashboard: (t) => `/${t}/admin`,
  media:     (t) => `/${t}/admin/media`,
  playlist:  (t) => `/${t}/admin/playlists`,
  schedule:  (t) => `/${t}/admin/schedules`,
  device:    (t) => `/${t}/admin/kiosk`,
  reception: (t) => `/${t}/admin/reception`,
};

export function AdminShell({ active, title, subtitle, breadcrumb, actions, children }: Props) {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const tenant = params.tenant ?? "";

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "#faf8f4" }}>
      {/* ─ Sidebar ──────────────────────────────────────────── */}
      <aside
        className="w-[248px] flex-shrink-0 flex flex-col"
        style={{ background: "#fffefb", borderRight: "1px solid #efece5" }}
      >
        {/* Brand */}
        <div className="px-5 py-[22px] flex items-center gap-2.5" style={{ borderBottom: "1px solid #efece5" }}>
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: "#1d1a15" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-[-0.2px]" style={{ color: "#1d1a15" }}>
              mokuture<span style={{ color: "#4a7c4e" }}>+</span>
            </div>
            <div className="text-[10.5px] uppercase tracking-[0.4px]" style={{ color: "#a8a198", fontFamily: "monospace" }}>
              CMS console
            </div>
          </div>
        </div>

        {/* Tenant chip */}
        <div className="px-4 pt-3.5 pb-2">
          <div
            className="flex items-center gap-2.5 px-2.5 py-2 rounded-[7px]"
            style={{ background: "#f4f1ea", border: "1px solid #efece5" }}
          >
            <div
              className="w-[22px] h-[22px] rounded-[5px] flex items-center justify-center text-[11px] font-bold flex-shrink-0"
              style={{ background: "#4a7c4e", color: "#fffefb" }}
            >
              {tenant[0]?.toUpperCase() ?? "T"}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[12px] font-semibold leading-[1.2] truncate" style={{ color: "#2d2a24" }}>
                {tenant}
              </div>
              <div className="text-[10px] tracking-[0.4px]" style={{ color: "#a8a198", fontFamily: "monospace" }}>
                TENANT
              </div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="px-2.5 pt-2 flex-1 overflow-auto">
          <div
            className="text-[10.5px] uppercase tracking-[0.6px] px-2.5 pt-2 pb-1.5"
            style={{ color: "#a8a198" }}
          >
            運用
          </div>
          {NAV_ITEMS.map((item) => {
            const isActive = active === item.id;
            return (
              <button
                key={item.id}
                onClick={() => router.push(NAV_PATHS[item.id](tenant))}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[7px] mb-[1px] text-[13px] text-left transition-colors hover:bg-[#f4f1ea]"
                style={{
                  background: isActive ? "#eaf0e8" : "transparent",
                  color: isActive ? "#3a6240" : "#6b6559",
                  fontWeight: isActive ? 600 : 500,
                  borderLeft: `2px solid ${isActive ? "#4a7c4e" : "transparent"}`,
                }}
              >
                <NavIcon id={item.id} active={isActive} />
                <span style={{ fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* User footer */}
        <div className="p-3 flex items-center gap-2.5" style={{ borderTop: "1px solid #efece5" }}>
          <div
            className="w-[30px] h-[30px] rounded-full flex items-center justify-center text-[12px] font-bold flex-shrink-0"
            style={{ background: "#f7ecd9", color: "#b8763a" }}
          >
            {tenant[0]?.toUpperCase() ?? "A"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-semibold" style={{ color: "#2d2a24" }}>管理者</div>
            <div className="text-[10.5px]" style={{ color: "#a8a198" }}>admin</div>
          </div>
          <button
            onClick={() => { clearTokens(); router.push("/login"); }}
            className="text-[11.5px] hover:underline flex-shrink-0"
            style={{ color: "#a8a198", background: "none", border: "none", cursor: "pointer" }}
          >
            ログアウト
          </button>
        </div>
      </aside>

      {/* ─ Main ────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* TopBar */}
        <div
          className="px-8 py-[22px] pb-[18px] flex items-end gap-6"
          style={{ background: "#fffefb", borderBottom: "1px solid #efece5" }}
        >
          <div className="flex-1">
            {breadcrumb && (
              <div
                className="text-[11.5px] mb-1.5 tracking-[0.2px]"
                style={{ color: "#a8a198", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
              >
                {breadcrumb}
              </div>
            )}
            <h1
              className="m-0 text-[22px] font-semibold tracking-[-0.3px]"
              style={{ color: "#1d1a15", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
            >
              {title}
            </h1>
            {subtitle && (
              <div
                className="text-[13px] mt-1"
                style={{ color: "#6b6559", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
              >
                {subtitle}
              </div>
            )}
          </div>
          {actions && <div className="flex items-center gap-2.5">{actions}</div>}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto" style={{ padding: "24px 32px 40px" }}>
          {children}
        </div>
      </div>
    </div>
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
}: {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
  children: ReactNode;
  onClick?: (e?: React.MouseEvent) => void;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const sizes = {
    sm: "px-2.5 py-[5px] text-[11.5px]",
    md: "px-3.5 py-2 text-[12.5px]",
  }[size];
  const variants = {
    primary: "text-[#fffefb] hover:opacity-90",
    default: "text-[#2d2a24] hover:bg-[#f4f1ea]",
    ghost:   "text-[#6b6559] hover:bg-[#f4f1ea]",
    danger:  "text-[#a84238] hover:bg-[#f6e0dc]",
  }[variant];
  const bg = variant === "primary" ? "#4a7c4e" : "#fffefb";
  const border = variant === "primary" ? "#4a7c4e" : variant === "ghost" ? "transparent" : "#d8d3c7";

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 font-medium rounded-[7px] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-colors ${sizes} ${variants}`}
      style={{ background: bg, border: `1px solid ${border}` }}
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
  padding?: string;
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
        fontFamily: '"Noto Sans JP", system-ui, sans-serif',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function MkPill({ tone, children }: { tone: "live" | "warn" | "off" | "error" | "info" | "neutral"; children: ReactNode }) {
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
      className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded-full text-[10.5px] font-semibold tracking-[0.2px] whitespace-nowrap"
      style={{ background: tones.bg, color: tones.fg, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
    >
      <span className="w-[5px] h-[5px] rounded-full flex-shrink-0" style={{ background: tones.dot }} />
      {children}
    </span>
  );
}

/* Nav icons (inline SVG) */
function NavIcon({ id, active }: { id: NavId; active: boolean }) {
  const color = active ? "#3a6240" : "#a8a198";
  const w = 17;
  switch (id) {
    case "dashboard":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
      </svg>;
    case "media":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="18" rx="2"/><path d="M9 8l6 4-6 4V8z" fill={color} stroke="none"/>
      </svg>;
    case "playlist":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="15" y2="18"/><circle cx="20" cy="15" r="3"/><line x1="20" y1="9" x2="20" y2="12"/>
      </svg>;
    case "schedule":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
      </svg>;
    case "device":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
      </svg>;
    case "reception":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/>
      </svg>;
  }
}
