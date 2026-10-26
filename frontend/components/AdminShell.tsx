"use client";

import { useRouter, useParams } from "next/navigation";
import { clearTokens, getLogoutUrl, getAccessToken, getReadonly } from "@/lib/auth";
import { useEffect, useRef, useState, useTransition } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { api } from "@/lib/api";

export type NavId = "dashboard" | "media" | "playlist" | "schedule" | "device" | "reception" | "inquiries" | "appointments" | "meeting_rooms" | "notify" | "locker" | "kiosk_settings" | "settings" | "users" | "profile";

interface Props {
  active: NavId;
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  actions?: ReactNode;
  children: ReactNode;
  receptionUnread?: number;
}

const NAV_OPS: { id: NavId; label: string }[] = [
  { id: "dashboard", label: "ダッシュボード" },
  { id: "media",     label: "メディア" },
  { id: "playlist",  label: "プレイリスト" },
  { id: "schedule",  label: "スケジュール" },
  { id: "device",       label: "キオスク端末" },
  { id: "reception",    label: "受付ログ" },
  { id: "inquiries",     label: "問い合わせ" },
  { id: "appointments",  label: "来社予定" },
  { id: "meeting_rooms", label: "会議室管理" },
  { id: "locker",        label: "ロッカー" },
];

const NAV_SETTINGS: { id: NavId; label: string }[] = [
  { id: "notify",         label: "通知設定" },
  { id: "kiosk_settings", label: "受付設定" },
  { id: "settings",       label: "基本設定" },
  { id: "users",          label: "ユーザー管理" },
  { id: "profile",        label: "アカウント" },
];

const NAV_PATHS: Record<NavId, (t: string) => string> = {
  dashboard:     (t) => `/${t}/admin`,
  media:         (t) => `/${t}/admin/media`,
  playlist:      (t) => `/${t}/admin/playlists`,
  schedule:      (t) => `/${t}/admin/schedules`,
  device:        (t) => `/${t}/admin/kiosk`,
  reception:     (t) => `/${t}/admin/reception`,
  inquiries:     (t) => `/${t}/admin/inquiries`,
  appointments:  (t) => `/${t}/admin/appointments`,
  meeting_rooms: (t) => `/${t}/admin/meeting-rooms`,
  notify:        (t) => `/${t}/admin/notify`,
  locker:        (t) => `/${t}/admin/locker`,
  kiosk_settings:(t) => `/${t}/admin/kiosk-settings`,
  settings:      (t) => `/${t}/admin/settings`,
  users:         (t) => `/${t}/admin/users`,
  profile:       (t) => `/${t}/admin/profile`,
};

const FONT_UI = '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, "Noto Sans JP", sans-serif';
const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

// 審査用デモモード: サイドバーの誘導ガイド用カラートーン。
// nav = 指し先メニュー項目のハイライト(bg/文字/リング)、balloon = 吹き出しの塗り/文字。
// glow/ring は CSS変数(--mkg-glow / --mkg-ring)へ渡す "R,G,B" 文字列。
type GuideTone = {
  navBg: string; navFg: string; ring: string;
  balloonBg: string; balloonFg: string; glow: string;
};
const GUIDE_TONES: Record<"green" | "blue" | "yellow", GuideTone> = {
  green:  { navBg: "#eef4ec", navFg: "#3a6240", ring: "74,124,78",   balloonBg: "#4a7c4e", balloonFg: "#fff",     glow: "74,124,78" },
  blue:   { navBg: "#e8f0f6", navFg: "#2e6b8e", ring: "46,107,142",  balloonBg: "#2e6b8e", balloonFg: "#fff",     glow: "46,107,142" },
  yellow: { navBg: "#f7efd7", navFg: "#8a6524", ring: "217,163,38",  balloonBg: "#d9a326", balloonFg: "#3d2f10", glow: "217,163,38" },
};

export function AdminShell({ active, title, subtitle, breadcrumb, actions, children, receptionUnread }: Props) {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const tenant = params.tenant ?? "";
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // ── 審査環境の閲覧専用アカウント（demo1@ranasoft.co.jp 等） ──
  // アクセストークンの ro クレームから判定（SSR一致のため初期 false→マウント後に確定）。
  // true のとき: ユーザー管理/アカウント メニューとログアウトを非表示、来社予定以外の
  // 画面上部アクション(保存・追加等)を隠し、閲覧専用バナーを出す。実際の書込抑止は
  // lib/api.ts のガードとサーバの ReadOnlyGuardMiddleware が担う（本表示はそのUX面）。
  const [readOnly, setReadOnly] = useState(false);
  useEffect(() => { setReadOnly(getReadonly()); }, []);

  // 非表示ページ(ユーザー管理/アカウント)へ直リンクで来ても閲覧専用時はダッシュボードへ戻す。
  useEffect(() => {
    if (readOnly && (active === "users" || active === "profile")) {
      router.replace(`/${tenant}/admin`);
    }
  }, [readOnly, active, tenant, router]);

  const settingsNav = readOnly
    ? NAV_SETTINGS.filter((i) => i.id !== "users" && i.id !== "profile")
    : NAV_SETTINGS;
  // 来社予定は閲覧専用でも操作可。それ以外の画面では上部アクションを隠す。
  const hideActions = readOnly && active !== "appointments";

  // ── メニュー遷移中インジケータ ──
  // router.push を useTransition でラップし、遷移完了(=遷移先ページが描画される)まで
  // isPending=true を得る。クリックした項目を即ハイライト＋スピナー表示し、
  // トップバー直下にも不定進捗バーを出して「遷移中」であることを明示する。
  const [isPending, startTransition] = useTransition();
  const [pendingId, setPendingId] = useState<NavId | null>(null);
  const navigating = isPending && pendingId !== null;

  const navigate = (id: NavId) => {
    setSidebarOpen(false); // モバイルはメニュー選択でドロワーを閉じる
    if (id === active) return; // 同じページなら遷移不要
    setPendingId(id);
    startTransition(() => {
      router.push(NAV_PATHS[id](tenant));
    });
  };

  // 遷移が完了/中断したら pending をクリア（遷移先で AdminShell が再マウントされる
  // ケースでも念のため）。
  useEffect(() => {
    if (!isPending) setPendingId(null);
  }, [isPending]);

  // ── 審査用デモモード: QR発行ガイド ──
  // デモテナントのときだけ、サイドバー「来社予定」に「QR発行はこちら①」バルーンを出す
  // （来社予定ページに入ると②以降が引き継ぐので、ここでは在席ページを除外して表示）。
  const [qrGuide, setQrGuide] = useState(false);
  const [isDesktop, setIsDesktop] = useState(false);
  const apptNavRef = useRef<HTMLButtonElement>(null);
  // デモモード: 受付ログ(反映確認)/ロッカー(施錠状況)へも同様の誘導ガイドを出す
  const receptionNavRef = useRef<HTMLButtonElement>(null);
  const lockerNavRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const apply = () => setIsDesktop(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    if (!tenant) return;
    try {
      const cached = localStorage.getItem(`mk_isdemo_${tenant}`);
      if (cached === "1") setQrGuide(true);
      else if (cached === "0") setQrGuide(false);
    } catch { /* localStorage 不可でも無視 */ }
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token).then((s) => {
      const demo = !!s.is_demo;
      setQrGuide(demo);
      try { localStorage.setItem(`mk_isdemo_${tenant}`, demo ? "1" : "0"); } catch { /* noop */ }
    }).catch(() => { /* 取得失敗時はキャッシュ値のまま */ });
  }, [tenant]);

  return (
    <div className="flex overflow-hidden adm-shell-root" style={{ background: "#faf8f4", fontFamily: FONT_UI }}>
      {/* ─ Overlay (mobile) ─────────────────────────────────── */}
      {sidebarOpen && (
        <div className="adm-sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ─ Sidebar ──────────────────────────────────────────── */}
      <aside className={`adm-sidebar${sidebarOpen ? " open" : ""}`}>
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
        <nav className="adm-sidebar-nav" style={{ padding: "10px 10px", flex: 1 }}>
          <div style={{ fontSize: 10.5, color: "#a8a198", textTransform: "uppercase", letterSpacing: "0.6px", padding: "8px 10px 6px" }}>
            運用
          </div>
          {NAV_OPS.map((item) => (
            <NavItem
              key={item.id}
              id={item.id}
              label={item.label}
              active={active === item.id}
              pending={pendingId === item.id}
              onClick={() => navigate(item.id)}
              badge={item.id === "reception" && receptionUnread && receptionUnread > 0 ? receptionUnread : undefined}
              buttonRef={
                item.id === "appointments" ? apptNavRef
                : item.id === "reception" ? receptionNavRef
                : item.id === "locker" ? lockerNavRef
                : undefined
              }
              guide={qrGuide && active !== item.id && (item.id === "appointments" || item.id === "reception" || item.id === "locker")}
              guideTone={
                item.id === "reception" ? GUIDE_TONES.blue
                : item.id === "locker" ? GUIDE_TONES.yellow
                : GUIDE_TONES.green
              }
            />
          ))}
          <div style={{ fontSize: 10.5, color: "#a8a198", textTransform: "uppercase", letterSpacing: "0.6px", padding: "14px 10px 6px" }}>
            設定
          </div>
          {settingsNav.map((item) => (
            <NavItem key={item.id} id={item.id} label={item.label} active={active === item.id} pending={pendingId === item.id} onClick={() => navigate(item.id)} />
          ))}
        </nav>

        {/* User footer */}
        <div className="adm-sidebar-footer" style={{ borderTop: "1px solid #efece5", flexShrink: 0 }}>
          <div style={{ padding: "12px 12px 8px", display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#f7ecd9", color: "#b8763a", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, flexShrink: 0 }}>
              {tenant[0]?.toUpperCase() ?? "A"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#2d2a24" }}>管理者</div>
              <div style={{ fontSize: 10.5, color: "#a8a198" }}>管理者 · admin</div>
            </div>
          </div>
          {/* 閲覧専用アカウント(demo1)ではログアウトを非表示 */}
          {!readOnly && (
            <button
              onClick={() => { clearTokens(); router.push(getLogoutUrl()); }}
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
          )}
        </div>
      </aside>

      {/* ─ Main ────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* TopBar */}
        <div className="adm-topbar" style={{ borderBottom: "1px solid #efece5", background: "#fffefb", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Hamburger (mobile only) */}
          <button className="adm-hamburger" onClick={() => setSidebarOpen(true)} aria-label="メニューを開く">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
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
          {actions && !hideActions && <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>{actions}</div>}
        </div>

        {/* 審査環境の閲覧専用バナー（来社予定以外の画面で表示） */}
        {readOnly && active !== "appointments" && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 20px", background: "#f7ecd9",
            borderBottom: "1px solid #ecdcc0", color: "#8a6524",
            fontSize: 12.5, fontFamily: FONT_JP, flexShrink: 0,
          }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>
            </svg>
            この画面は閲覧専用です。操作できるのは「来社予定」のみです。
          </div>
        )}

        {/* 遷移中の不定進捗バー（トップバー直下） */}
        <div aria-hidden={!navigating} style={{ height: 2, flexShrink: 0, overflow: "hidden", background: navigating ? "#eaf0e8" : "transparent" }}>
          {navigating && (
            <div style={{
              height: "100%", width: "40%",
              background: "linear-gradient(90deg, transparent, #4a7c4e, transparent)",
              animation: "mkNavBar 0.9s ease-in-out infinite",
            }} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto adm-content">
          {children}
        </div>
      </div>

      {/* 審査用デモモード: QR発行ガイド① （サイドバー「来社予定」） */}
      <QrGuideBalloon
        anchorRef={apptNavRef}
        active={qrGuide && isDesktop && active !== "appointments"}
        text="QR発行はこちら①"
        placement="right"
      />

      {/* 審査用デモモード: 受付ログの反映確認ガイド（サイドバー「受付ログ」・青） */}
      <QrGuideBalloon
        anchorRef={receptionNavRef}
        active={qrGuide && isDesktop && active !== "reception"}
        text="受付ログへの反映確認はこちら"
        placement="right"
        fill={GUIDE_TONES.blue.balloonBg}
        textColor={GUIDE_TONES.blue.balloonFg}
        glow={GUIDE_TONES.blue.glow}
      />

      {/* 審査用デモモード: ロッカー施錠状況ガイド（サイドバー「ロッカー」・黄） */}
      <QrGuideBalloon
        anchorRef={lockerNavRef}
        active={qrGuide && isDesktop && active !== "locker"}
        text="ロッカー施錠状況はこちら"
        placement="right"
        fill={GUIDE_TONES.yellow.balloonBg}
        textColor={GUIDE_TONES.yellow.balloonFg}
        glow={GUIDE_TONES.yellow.glow}
      />
    </div>
  );
}

function NavItem({ id, label, active, pending = false, onClick, badge, buttonRef, guide = false, guideTone = GUIDE_TONES.green }: { id: NavId; label: string; active: boolean; pending?: boolean; onClick: () => void; badge?: number; buttonRef?: React.Ref<HTMLButtonElement>; guide?: boolean; guideTone?: GuideTone }) {
  // pending 中はクリック直後から選択済みに見せる（即時フィードバック）
  const hot = active || pending;
  // 審査用デモモード: ガイドが指すメニュー(来社予定=緑/受付ログ=青/ロッカー=黄)を色枠＋パルスで強調（選択中は通常表示）
  const guiding = guide && !hot;
  return (
    <button
      ref={buttonRef}
      onClick={onClick}
      aria-busy={pending || undefined}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 10,
        padding: hot ? "8px 10px 8px 12px" : "8px 10px",
        borderRadius: 7, marginBottom: 1,
        background: hot ? "#eaf0e8" : guiding ? guideTone.navBg : "transparent",
        color: hot ? "#3a6240" : guiding ? guideTone.navFg : "#6b6559",
        fontSize: 13, fontWeight: hot || guiding ? 600 : 500,
        cursor: pending ? "progress" : "pointer", textAlign: "left",
        borderLeft: `2px solid ${hot ? "#4a7c4e" : "transparent"}`,
        border: "none", fontFamily: FONT_JP,
        transition: "background 0.1s",
        boxShadow: guiding ? `0 0 0 2px rgba(${guideTone.ring},0.9)` : "none",
        animation: guiding ? "mkGuidePulse 1.6s ease-in-out infinite" : undefined,
        ...(guiding ? { ["--mkg-ring" as string]: guideTone.ring } : {}),
      } as React.CSSProperties}
      onMouseEnter={(e) => { if (!hot && !guiding) (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
      onMouseLeave={(e) => { if (!hot && !guiding) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
    >
      <NavIcon id={id} active={hot} />
      <span style={{ flex: 1 }}>{label}</span>
      {pending ? (
        <span
          aria-label="遷移中"
          style={{
            width: 13, height: 13, flexShrink: 0, marginLeft: 4,
            border: "2px solid #cfe0cd", borderTopColor: "#4a7c4e",
            borderRadius: "50%", animation: "mkNavSpin 0.6s linear infinite",
          }}
        />
      ) : badge !== undefined && badge > 0 && (
        <span style={{
          background: "#c8a96e",
          color: "#1d1a15",
          borderRadius: 999,
          fontSize: 10,
          fontWeight: 700,
          padding: "1px 5px",
          minWidth: 16,
          textAlign: "center",
          marginLeft: 4,
          lineHeight: "14px",
          display: "inline-block",
        }}>
          {badge > 99 ? "99+" : badge}
        </span>
      )}
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

/* ─ ガイドバルーンの重なり回避（全インスタンス共有） ─────────────────
   QrGuideBalloon は各々独立した position:fixed ポータルで互いを知らないため、
   モジュールスコープに各バルーンの「ずらす前の理想box」を集約し、重なる場合のオフセット(dy)を返す。
   ・ボタンを指す top/bottom(②〜⑤) は動かさない（押すと自分のアンカー=ボタンを覆うため）。
   ・サイドバー left/right は「上方向」へ逃がす（下だとコンテンツや他バルーンに被るため）。 */
type GuideBox = { top: number; left: number; width: number; height: number };
const guideRegistry = new Map<number, { order: number; box: GuideBox; placement: string }>();
const guideListeners = new Set<() => void>();
let guideSeq = 0;
function notifyGuides() { guideListeners.forEach((fn) => fn()); }
function resolveGuideOffsets(): Map<number, number> {
  const isSide = (p: string) => p === "left" || p === "right";
  const all = [...guideRegistry.entries()];
  const placed: GuideBox[] = [];
  const offsets = new Map<number, number>();
  const MARGIN = 8;
  // 1) ボタンを指すバルーン(top/bottom=②〜⑤)は動かさず理想位置で確定する。
  for (const [id, e] of all) {
    if (!isSide(e.placement)) { offsets.set(id, 0); placed.push({ ...e.box }); }
  }
  // 2) サイドバー(left/right)は上方向へ避ける。下にあるものから処理して上へ積み、
  //    視覚順(上の nav 項目=上)を保つ。上端が相手より上に出るまで負方向へずらす。
  const sides = all
    .filter(([, e]) => isSide(e.placement))
    .sort((a, b) => (b[1].box.top - a[1].box.top) || (a[1].order - b[1].order));
  for (const [id, e] of sides) {
    const box = e.box;
    let shift = 0;
    let moved = true;
    while (moved) {
      moved = false;
      const top = box.top + shift;
      for (const p of placed) {
        const horiz = box.left < p.left + p.width && box.left + box.width > p.left;
        const vert  = top < p.top + p.height && top + box.height > p.top;
        // 上へ逃がす: 自分の下端を相手の上端より上へ。shift は負に単調減少＝必ず停止。
        if (horiz && vert) { shift = (p.top - box.height - MARGIN) - box.top; moved = true; }
      }
    }
    offsets.set(id, shift);   // 上方向＝負値
    placed.push({ ...box, top: box.top + shift });
  }
  return offsets;
}

/* ─ QR発行ガイド用 バルーン（審査用デモモード限定） ─────────────────
   任意の要素(anchorRef)に吹き出しを固定表示する。position:fixed + ポータルで
   親の overflow(サイドバー/テーブルのスクロール)にクリップされず、スクロール/リサイズにも追従する。
   pointer-events:none なので下のボタンのクリックは妨げない。 */
export function QrGuideBalloon<T extends HTMLElement>({
  anchorRef, active, text, placement = "bottom",
  fill = "#4a7c4e", textColor = "#fff", glow = "74,124,78",
}: {
  anchorRef: React.RefObject<T | null>;
  active: boolean;
  text: string;
  placement?: "top" | "bottom" | "left" | "right";
  /** 吹き出しの塗り色（既定=緑）。青/黄など誘導ごとに変える。 */
  fill?: string;
  /** 吹き出しの文字色（塗りに応じて可読性を確保。既定=白） */
  textColor?: string;
  /** 明滅グロー色 "R,G,B"（CSS変数 --mkg-glow へ。既定=緑） */
  glow?: string;
}) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [covered, setCovered] = useState(false);   // モーダル等に覆われているか（覆われたら裏側へ回す）
  const [dy, setDy] = useState(0);                  // 他バルーンとの重なりを避ける下方向オフセット
  const dyRef = useRef(0); dyRef.current = dy;
  const idRef = useRef(-1); if (idRef.current < 0) idRef.current = guideSeq++;

  useEffect(() => {
    if (!active) { setRect(null); setCovered(false); return; }
    let raf = 0;
    let prevKey = "";
    const update = () => {
      const el = anchorRef.current;
      if (!el) { setRect(null); return; }
      const r = el.getBoundingClientRect();
      // 非表示(off-canvas サイドバー等)は出さない
      if (r.width === 0 && r.height === 0) { setRect(null); prevKey = ""; return; }
      // 位置/サイズが実際に変わった時だけ setRect（毎回新オブジェクトでの無駄な再描画/再登録を防ぐ）
      const key = `${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.width)},${Math.round(r.height)}`;
      if (key !== prevKey) { prevKey = key; setRect(r); }
      // アンカーがモーダル等に覆われているか判定（覆われていたら裏側に回す）。
      // バルーンは pointer-events:none なので elementFromPoint はバルーン自身を返さない。
      const topEl = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      setCovered(!!topEl && !(topEl === el || el.contains(topEl) || topEl.contains(el)));
    };
    update();
    const onChange = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(update); };
    window.addEventListener("scroll", onChange, true);
    window.addEventListener("resize", onChange);
    // モーダル等の出現/消滅を即検知して covered を更新する（scroll/resize が出ない開閉でも
    // 400ms を待たずに裏側へ回す）。属性は監視せず childList/subtree のみ＝バルーン自身の
    // style 変更ではループしない。バーストは rAF で1フレームに集約。
    const mo = new MutationObserver(onChange);
    mo.observe(document.body, { childList: true, subtree: true });
    const id = window.setInterval(update, 400); // レイアウト変化(画像読込・トランジション等)の取りこぼしのフォールバック
    return () => {
      window.removeEventListener("scroll", onChange, true);
      window.removeEventListener("resize", onChange);
      mo.disconnect();
      window.clearInterval(id);
      cancelAnimationFrame(raf);
    };
  }, [anchorRef, active]);

  // カーソルを吹き出しに重ねたら一時的に消して下のコンテンツを見せる。
  // pointer-events:none のままなので座標判定は window の mousemove で行う（クリックは元々透過）。
  const boxRef = useRef<HTMLDivElement>(null);
  const [dodge, setDodge] = useState(false);
  useEffect(() => {
    if (!active) { setDodge(false); return; }
    const onMove = (e: MouseEvent) => {
      const el = boxRef.current;
      if (!el) return;
      const b = el.getBoundingClientRect();
      if (b.width === 0 && b.height === 0) { setDodge(false); return; }
      const m = 4; // わずかに広めに判定して端でチラつかないように
      setDodge(
        e.clientX >= b.left - m && e.clientX <= b.right + m &&
        e.clientY >= b.top - m && e.clientY <= b.bottom + m,
      );
    };
    const onLeaveWin = () => setDodge(false); // 吹き出し上でウィンドウ外へ出たら戻す
    window.addEventListener("mousemove", onMove, { passive: true });
    document.addEventListener("mouseleave", onLeaveWin);
    return () => {
      window.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseleave", onLeaveWin);
      setDodge(false);
    };
  }, [active]);

  // 重なり回避: 自分の理想boxを共有レジストリへ登録し、他バルーンとの重なりから dy を解決する。
  // 覆われている(裏側)/非表示のときは他を押しのけないよう登録しない。
  useEffect(() => {
    const id = idRef.current;
    const unregister = () => { if (guideRegistry.delete(id)) notifyGuides(); };
    if (!active || !rect || covered) {
      unregister();
      setDy((prev) => (prev !== 0 ? 0 : prev));
      return;
    }
    const el = boxRef.current;
    if (!el) return;
    const b = el.getBoundingClientRect();
    if (b.width === 0 && b.height === 0) { unregister(); return; }
    // 現在適用中の dy を差し引いた「ずらす前の理想位置」を登録する。
    guideRegistry.set(id, { order: id, placement, box: { top: b.top - dyRef.current, left: b.left, width: b.width, height: b.height } });
    const recompute = () => {
      const next = resolveGuideOffsets().get(id) ?? 0;
      setDy((prev) => (Math.abs(prev - next) > 0.5 ? next : prev));
    };
    guideListeners.add(recompute);
    notifyGuides();   // 自分の登録を全バルーンへ反映して再解決させる
    return () => { guideListeners.delete(recompute); unregister(); };
  }, [active, rect, covered, text, placement]);

  if (!active || !rect) return null;

  const GAP = 14;
  const ARROW = 11;

  const box: React.CSSProperties = {
    position: "fixed", zIndex: covered ? 900 : 4000, pointerEvents: "none",
    background: fill, color: textColor,
    fontFamily: FONT_JP, fontSize: 17, fontWeight: 700, lineHeight: 1.3,
    letterSpacing: "0.3px", whiteSpace: "nowrap",
    padding: "13px 22px", borderRadius: 12,
    boxShadow: `0 6px 20px rgba(${glow},0.5)`,
    animation: "mkGuideGlow 1.6s ease-in-out infinite",
    // 既定は約20%透明（下がうっすら見える）、カーソルが重なったら完全に消す
    opacity: dodge ? 0 : 0.8,
    transition: "opacity 0.18s ease",
    ["--mkg-glow" as string]: glow,
  } as React.CSSProperties;
  const arrow: React.CSSProperties = {
    position: "absolute", width: 0, height: 0, border: `${ARROW}px solid transparent`,
  };

  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  if (placement === "right") {
    box.left = rect.right + GAP; box.top = cy; box.transform = "translateY(-50%)";
    Object.assign(arrow, { right: "100%", top: "50%", marginTop: -ARROW, borderRightColor: fill });
  } else if (placement === "left") {
    box.left = rect.left - GAP; box.top = cy; box.transform = "translate(-100%, -50%)";
    Object.assign(arrow, { left: "100%", top: "50%", marginTop: -ARROW, borderLeftColor: fill });
  } else if (placement === "top") {
    box.left = cx; box.top = rect.top - GAP; box.transform = "translate(-50%, -100%)";
    Object.assign(arrow, { top: "100%", left: "50%", marginLeft: -ARROW, borderTopColor: fill });
  } else { // bottom
    box.left = cx; box.top = rect.bottom + GAP; box.transform = "translateX(-50%)";
    Object.assign(arrow, { bottom: "100%", left: "50%", marginLeft: -ARROW, borderBottomColor: fill });
  }

  // 重なり回避の下方向オフセットを反映（覆われている時は dy=0 に戻している）。
  box.top = (box.top as number) + dy;

  // 重なりで本体をずらしたときは、三角しっぽの代わりに「根本を伸ばした引き出し線」で
  // 本体を対象(メニュー項目/ボタン)までつなぎ、どの案内かを一目で分かるようにする。
  // anchorPt=対象側の付け根(点を打つ) / edgePt=バルーン側の付け根。dy(縦ずれ)を線で橋渡しする。
  const boxCy = cy + dy;
  let anchorPt: { x: number; y: number };
  let edgePt: { x: number; y: number };
  if (placement === "right")      { anchorPt = { x: rect.right, y: cy };    edgePt = { x: rect.right + GAP, y: boxCy }; }
  else if (placement === "left")  { anchorPt = { x: rect.left,  y: cy };    edgePt = { x: rect.left - GAP,  y: boxCy }; }
  else if (placement === "top")   { anchorPt = { x: cx, y: rect.top };      edgePt = { x: cx, y: rect.top - GAP + dy }; }
  else                            { anchorPt = { x: cx, y: rect.bottom };   edgePt = { x: cx, y: rect.bottom + GAP + dy }; }

  const showLeader = Math.abs(dy) >= 2;   // ずれた時だけ引き出し線に切替（通常は従来の三角しっぽ＝差分なし）
  let leader: ReactNode = null;
  if (showLeader) {
    const pad = 12;
    const minX = Math.min(anchorPt.x, edgePt.x) - pad;
    const minY = Math.min(anchorPt.y, edgePt.y) - pad;
    const w = Math.abs(anchorPt.x - edgePt.x) + pad * 2;
    const h = Math.abs(anchorPt.y - edgePt.y) + pad * 2;
    leader = (
      <svg
        width={w} height={h}
        style={{
          position: "fixed", left: minX, top: minY,
          zIndex: (covered ? 900 : 4000) - 1, pointerEvents: "none",
          opacity: dodge ? 0 : 0.85, transition: "opacity 0.18s ease", overflow: "visible",
        }}
      >
        <line
          x1={anchorPt.x - minX} y1={anchorPt.y - minY}
          x2={edgePt.x - minX}   y2={edgePt.y - minY}
          stroke={fill} strokeWidth={5} strokeLinecap="round"
        />
        <circle cx={anchorPt.x - minX} cy={anchorPt.y - minY} r={6} fill={fill} />
      </svg>
    );
  }

  return createPortal(
    <>
      {leader}
      <div ref={boxRef} style={box}>
        {text}
        {!showLeader && <span style={arrow} />}
      </div>
    </>,
    document.body,
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
    case "inquiries":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4h16a1 1 0 011 1v11a1 1 0 01-1 1H8l-4 4V5a1 1 0 011-1z"/><path d="M8 9h8M8 13h5"/>
      </svg>;
    case "appointments":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M8 15h4M8 18h2"/>
        <path d="M15 15l1.5 1.5L19 13"/>
      </svg>;
    case "meeting_rooms":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 4v16M16 4v16M3 12h18"/>
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
    case "profile":
      return <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
      </svg>;
  }
}
