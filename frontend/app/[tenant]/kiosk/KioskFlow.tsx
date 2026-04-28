"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import {
  api,
  getCachedKioskSettings,
  setCachedKioskSettings,
  type PublicTenantSettings,
  type KioskPlaylistItem,
  type KioskMediaItem,
} from "@/lib/api";
import { KioskScaler } from "@/components/KioskScaler";

// ─── Types ────────────────────────────────────────────────────────────────────
type KioskScreen = "idle" | "top" | "reception" | "calling" | "complete";

interface FlowData {
  name: string;
  company: string;
  staff: string;
  purpose: string;
}

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";
const KIOSK_NAME_KEY = "mokuture_kiosk_name";
const VALID_SCREENS: KioskScreen[] = ["idle", "top", "reception", "calling", "complete"];

const DEFAULT_SETTINGS: PublicTenantSettings = {
  brand_color: "#4a7c4e",
  logo_url: null,
  font: "Noto Sans JP / Inter",
  kiosk_welcome_message: "ようこそ",
  kiosk_sub_message: "ご用件をお選びください",
  kiosk_calling_message: "担当者をお呼びしています",
  kiosk_complete_message: "担当者がご案内します",
  kiosk_idle_timeout_sec: 60,
  kiosk_complete_timeout_sec: 10,
};

// ─── Romaji conversion ────────────────────────────────────────────────────────
type FieldKey = "visitor_name" | "company" | "staff" | "purpose";

const FIELDS: { key: FieldKey; label: string; placeholder: string; required?: boolean }[] = [
  { key: "visitor_name", label: "お名前",    placeholder: "山田 太郎",           required: true },
  { key: "company",      label: "会社名",    placeholder: "株式会社 〇〇" },
  { key: "staff",        label: "ご担当者名", placeholder: "担当者のお名前" },
  { key: "purpose",      label: "ご用件",    placeholder: "お打ち合わせ など" },
];

const KB_ROWS = [
  ["1","2","3","4","5","6","7","8","9","0"],
  ["q","w","e","r","t","y","u","i","o","p"],
  ["a","s","d","f","g","h","j","k","l"],
  ["shift","z","x","c","v","b","n","m","⌫"],
];

const ROMAJI_MAP: Record<string, string> = {
  "a":"あ","i":"い","u":"う","e":"え","o":"お",
  "ka":"か","ki":"き","ku":"く","ke":"け","ko":"こ",
  "kya":"きゃ","kyu":"きゅ","kyo":"きょ",
  "sa":"さ","si":"し","su":"す","se":"せ","so":"そ",
  "shi":"し","sha":"しゃ","shu":"しゅ","sho":"しょ",
  "sya":"しゃ","syu":"しゅ","syo":"しょ",
  "ta":"た","ti":"ち","tu":"つ","te":"て","to":"と",
  "chi":"ち","tsu":"つ",
  "cha":"ちゃ","chu":"ちゅ","cho":"ちょ",
  "tya":"ちゃ","tyu":"ちゅ","tyo":"ちょ",
  "na":"な","ni":"に","nu":"ぬ","ne":"ね","no":"の",
  "nya":"にゃ","nyu":"にゅ","nyo":"にょ",
  "nn":"ん",
  "ha":"は","hi":"ひ","hu":"ふ","fu":"ふ","he":"へ","ho":"ほ",
  "hya":"ひゃ","hyu":"ひゅ","hyo":"ひょ",
  "ma":"ま","mi":"み","mu":"む","me":"め","mo":"も",
  "mya":"みゃ","myu":"みゅ","myo":"みょ",
  "ya":"や","yu":"ゆ","yo":"よ",
  "ra":"ら","ri":"り","ru":"る","re":"れ","ro":"ろ",
  "rya":"りゃ","ryu":"りゅ","ryo":"りょ",
  "wa":"わ","wo":"を","wi":"ゐ","we":"ゑ",
  "ga":"が","gi":"ぎ","gu":"ぐ","ge":"げ","go":"ご",
  "gya":"ぎゃ","gyu":"ぎゅ","gyo":"ぎょ",
  "za":"ざ","zi":"じ","zu":"ず","ze":"ぜ","zo":"ぞ",
  "ji":"じ","ja":"じゃ","ju":"じゅ","jo":"じょ",
  "zya":"じゃ","zyu":"じゅ","zyo":"じょ",
  "da":"だ","di":"ぢ","du":"づ","de":"で","do":"ど",
  "ba":"ば","bi":"び","bu":"ぶ","be":"べ","bo":"ぼ",
  "bya":"びゃ","byu":"びゅ","byo":"びょ",
  "pa":"ぱ","pi":"ぴ","pu":"ぷ","pe":"ぺ","po":"ぽ",
  "pya":"ぴゃ","pyu":"ぴゅ","pyo":"ぴょ",
  "xa":"ぁ","xi":"ぃ","xu":"ぅ","xe":"ぇ","xo":"ぉ",
  "xya":"ゃ","xyu":"ゅ","xyo":"ょ",
  "xtsu":"っ","xtu":"っ",
  "-":"ー",
};

const ROMAJI_PREFIXES = new Set(
  Object.keys(ROMAJI_MAP).flatMap(k =>
    Array.from({ length: k.length }, (_, i) => k.slice(0, i + 1))
  )
);

const VOWELS = new Set(["a","i","u","e","o"]);

function convertRomaji(buffer: string, newChar: string): { output: string; pending: string } {
  const candidate = buffer + newChar;

  if (buffer === "n" && !VOWELS.has(newChar) && newChar !== "y" && newChar !== "n") {
    const rest = convertRomaji("", newChar);
    return { output: "ん" + rest.output, pending: rest.pending };
  }

  if (
    buffer.length > 0 &&
    newChar === buffer[buffer.length - 1] &&
    !VOWELS.has(newChar) &&
    newChar !== "n"
  ) {
    const rest = convertRomaji("", newChar);
    return { output: "っ" + rest.output, pending: rest.pending };
  }

  if (ROMAJI_MAP[candidate] !== undefined) return { output: ROMAJI_MAP[candidate], pending: "" };
  if (ROMAJI_PREFIXES.has(candidate)) return { output: "", pending: candidate };
  if (ROMAJI_PREFIXES.has(newChar)) return { output: buffer, pending: newChar };
  if (ROMAJI_MAP[newChar] !== undefined) return { output: buffer + ROMAJI_MAP[newChar], pending: "" };
  return { output: candidate, pending: "" };
}

// ─── SVG Icons ────────────────────────────────────────────────────────────────
const ReceptionIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);
const QRIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <path d="M14 14h3v3h-3zM20 14h1M14 20h1M17 18v3M20 17v4" />
  </svg>
);
const TruckIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="1" y="3" width="15" height="13" rx="1" /><path d="M16 8h4l3 3v5h-7V8z" />
    <circle cx="5.5" cy="18.5" r="2.5" /><circle cx="18.5" cy="18.5" r="2.5" />
  </svg>
);
const MoreIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /><circle cx="5" cy="12" r="1" />
  </svg>
);
const TileArrowIcon = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);
const BellSmallIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" /><path d="M10 19a2 2 0 0 0 4 0" />
  </svg>
);
const BellLargeIcon = () => (
  <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" /><path d="M10 19a2 2 0 0 0 4 0" />
  </svg>
);
const CheckIconSmall = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12l5 5L20 6" />
  </svg>
);
const CheckIconLarge = ({ size = 50, stroke = 2.4 }: { size?: number; stroke?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12l5 5L20 6" strokeDasharray="60" strokeDashoffset="60" style={{ animation: "kiosk-check-draw 0.6s 0.3s cubic-bezier(0.2,0.9,0.3,1) forwards" }} />
  </svg>
);
const CompleteArrowIcon = () => (
  <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);
const ClockIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" />
  </svg>
);

// ─── IdleScreen ───────────────────────────────────────────────────────────────
function IdleScreen({
  settings,
  items,
  onStart,
}: {
  settings: PublicTenantSettings;
  items: KioskPlaylistItem[];
  onStart: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const itemTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const brandColor = settings.brand_color;

  const advanceItem = useCallback(() => {
    setCurrentIndex(i => (i + 1) % Math.max(items.length, 1));
  }, [items.length]);

  useEffect(() => {
    if (items.length === 0) return;
    const item = items[currentIndex];
    if (!item?.media) {
      itemTimerRef.current = setTimeout(advanceItem, 3000);
      return () => { if (itemTimerRef.current) clearTimeout(itemTimerRef.current); };
    }
    if (item.media.mime_type === "video/mp4") return;
    itemTimerRef.current = setTimeout(advanceItem, item.duration_sec * 1000);
    return () => { if (itemTimerRef.current) clearTimeout(itemTimerRef.current); };
  }, [currentIndex, items, advanceItem]);

  const currentMedia: KioskMediaItem | null = items[currentIndex]?.media ?? null;

  return (
    <KioskScaler bg="#0a0806">
      <div
        style={{ width: 1920, height: 1080, position: "relative", overflow: "hidden", cursor: "pointer", userSelect: "none" }}
        onClick={onStart}
      >
        {currentMedia?.mime_type === "video/mp4" ? (
          <video
            ref={videoRef}
            key={currentMedia.id}
            src={currentMedia.url}
            autoPlay muted playsInline
            loop={items.length === 1}
            onLoadedMetadata={() => videoRef.current?.play().catch(() => {})}
            onEnded={advanceItem}
            onError={() => advanceItem()}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : currentMedia ? (
          <img
            key={currentMedia.id}
            src={currentMedia.url}
            alt=""
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <>
            <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 35% 40%, #4a3e2c 0%, #1d1610 50%, #0a0806 100%)" }} />
            <svg width="1920" height="1080" style={{ position: "absolute", inset: 0, opacity: 0.18 }}>
              <defs>
                <pattern id="idleGrain" x="0" y="0" width="100%" height="36" patternUnits="userSpaceOnUse">
                  <path d="M0 18 Q 480 4 960 20 T 1920 16" stroke="#e8d8b8" strokeWidth="0.7" fill="none" />
                </pattern>
                <linearGradient id="idleVignette" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#000" stopOpacity="0.55" />
                  <stop offset="45%" stopColor="#000" stopOpacity="0" />
                  <stop offset="100%" stopColor="#000" stopOpacity="0.85" />
                </linearGradient>
              </defs>
              <rect width="1920" height="1080" fill="url(#idleGrain)" />
              <rect width="1920" height="1080" fill="url(#idleVignette)" />
            </svg>
            <div style={{ position: "absolute", left: "8%", bottom: "14%", width: 500, height: 360, background: "linear-gradient(180deg, transparent, rgba(0,0,0,0.6))", borderRadius: "50% 50% 8% 8% / 30% 30% 8% 8%", filter: "blur(40px)", opacity: 0.7 }} />
            <div style={{ position: "absolute", right: "12%", top: "18%", width: 600, height: 400, background: "radial-gradient(ellipse, #f0d9a8 0%, transparent 60%)", opacity: 0.25, filter: "blur(2px)" }} />
          </>
        )}

        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", zIndex: 1 }}>
          <div style={{ flex: 1 }} />
          <div style={{ padding: "0 80px 80px", display: "flex", justifyContent: "flex-end", alignItems: "flex-end" }}>
            <div style={{ padding: "28px 36px", background: "rgba(255,255,255,0.96)", color: "#1d1a15", borderRadius: 20, display: "flex", alignItems: "center", gap: 22, boxShadow: "0 12px 48px rgba(0,0,0,0.4)" }}>
              <div style={{ position: "relative", width: 56, height: 56, flexShrink: 0 }}>
                <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `2px solid ${brandColor}`, opacity: 0.4, animation: "kiosk-ring-expand 2.4s ease-out 0s infinite" }} />
                <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `2px solid ${brandColor}`, opacity: 0.3, animation: "kiosk-ring-expand 2.4s ease-out 0.8s infinite" }} />
                <div style={{ position: "absolute", inset: 8, borderRadius: "50%", background: brandColor, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#ffffff" }} />
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, letterSpacing: 2, color: "#a8a198", textTransform: "uppercase", marginBottom: 4, fontFamily: "Inter, system-ui, sans-serif" }}>TAP TO BEGIN</div>
                <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: -0.5 }}>画面にタッチして受付</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </KioskScaler>
  );
}

// ─── TopScreen ────────────────────────────────────────────────────────────────
function TopScreen({
  settings,
  deviceName,
  tenant,
  onNavigate,
  onIdle,
}: {
  settings: PublicTenantSettings;
  deviceName: string;
  tenant: string;
  onNavigate: (screen: KioskScreen, data?: Partial<FlowData>) => void;
  onIdle: () => void;
}) {
  const router = useRouter();
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pressed, setPressed] = useState<number | null>(null);
  const [now, setNow] = useState("");

  const resetIdle = useCallback(() => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(onIdle, settings.kiosk_idle_timeout_sec * 1000);
  }, [onIdle, settings.kiosk_idle_timeout_sec]);

  useEffect(() => {
    resetIdle();
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => { if (idleRef.current) clearTimeout(idleRef.current); clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tiles = [
    { Icon: ReceptionIcon, label: "ご訪問",      sub: "お約束の方",             primary: true, action: () => onNavigate("reception", { purpose: "" }) },
    { Icon: QRIcon,        label: "QR で受付",   sub: "招待コードをお持ちの方",               action: () => router.push(`/${tenant}/kiosk/qr`) },
    { Icon: TruckIcon,     label: "配送・宅配便", sub: "お荷物のお届け",                      action: () => onNavigate("reception", { purpose: "配送・宅配便" }) },
    { Icon: MoreIcon,      label: "その他",       sub: "上記以外のご用件",                    action: () => onNavigate("reception", { purpose: "その他" }) },
  ];

  const handleTile = (i: number, action: () => void) => {
    resetIdle();
    setPressed(i);
    setTimeout(() => { setPressed(null); action(); }, 160);
  };

  return (
    <KioskScaler bg="#faf8f4">
      <div
        style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}
        onClick={resetIdle}
      >
        <div style={{ flex: 1, padding: "28px 80px 0", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 40, marginBottom: 40 }}>
            <div>
              <div style={{ fontSize: 14, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase", marginBottom: 12, fontFamily: "Inter, system-ui, sans-serif" }}>RECEPTION</div>
              <div style={{ fontSize: 78, fontWeight: 600, color: "#1d1a15", letterSpacing: -2.5, lineHeight: 1.1 }}>{settings.kiosk_welcome_message}</div>
            </div>
            <div style={{ paddingBottom: 16, fontSize: 22, color: "#6b6559" }}>{settings.kiosk_sub_message}</div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 22, flex: 1, minHeight: 0 }}>
            {tiles.map((tile, i) => {
              const isPrimary = tile.primary;
              return (
                <button
                  key={i}
                  onClick={() => handleTile(i, tile.action)}
                  style={{
                    background: isPrimary ? "#1d1a15" : "#fffefb",
                    color: isPrimary ? "#ffffff" : "#2d2a24",
                    border: `2px solid ${isPrimary ? "#1d1a15" : "#efece5"}`,
                    borderRadius: 22, padding: "36px 32px",
                    display: "flex", flexDirection: "column", justifyContent: "space-between",
                    position: "relative", cursor: "pointer",
                    transform: pressed === i ? "scale(0.97)" : "scale(1)",
                    transition: "transform 0.14s cubic-bezier(0.2,0.8,0.3,1)",
                    textAlign: "left", fontFamily: "inherit",
                  }}
                >
                  <div style={{ width: 76, height: 76, borderRadius: 18, background: isPrimary ? "rgba(255,255,255,0.1)" : `${settings.brand_color}22`, color: isPrimary ? "#ffffff" : settings.brand_color, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <tile.Icon />
                  </div>
                  <div>
                    <div style={{ fontSize: 38, fontWeight: 600, letterSpacing: -1, lineHeight: 1.1 }}>{tile.label}</div>
                    <div style={{ fontSize: 16, marginTop: 8, color: isPrimary ? "rgba(255,255,255,0.6)" : "#6b6559" }}>{tile.sub}</div>
                  </div>
                  <div style={{ position: "absolute", top: 32, right: 32, color: isPrimary ? "rgba(255,255,255,0.5)" : "#a8a198" }}>
                    <TileArrowIcon />
                  </div>
                </button>
              );
            })}
          </div>

          <div style={{ marginTop: 24, marginBottom: 24, background: "#f4f1ea", borderRadius: 16, padding: "18px 26px", display: "flex", alignItems: "center", gap: 18, border: "1px solid #efece5", flexShrink: 0 }}>
            <div style={{ width: 40, height: 40, borderRadius: 10, background: "#fffefb", display: "flex", alignItems: "center", justifyContent: "center", color: "#b8763a" }}>
              <BellSmallIcon />
            </div>
            <div style={{ flex: 1, fontSize: 16, color: "#2d2a24" }}>お困りの方は <b>受付スタッフ</b> までお声がけください</div>
            <div style={{ fontSize: 13, color: "#a8a198" }}>受付時間 09:00–18:00</div>
          </div>
        </div>

        <div style={{ padding: "0 80px 28px", display: "flex", alignItems: "center", color: "#a8a198", fontSize: 13, flexShrink: 0 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14 }}>{now}</span>
          <span style={{ flex: 1 }} />
          <span>{settings.kiosk_idle_timeout_sec}秒で待機画面に戻ります</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: "JetBrains Mono, monospace" }}>{deviceName || "kiosk"}</span>
        </div>
      </div>
    </KioskScaler>
  );
}

// ─── ReceptionScreen ──────────────────────────────────────────────────────────
function ReceptionScreen({
  settings,
  deviceName,
  initialPurpose,
  onComplete,
  onBack,
  onIdle,
}: {
  settings: PublicTenantSettings;
  deviceName: string;
  initialPurpose: string;
  onComplete: (data: FlowData) => void;
  onBack: () => void;
  onIdle: () => void;
}) {
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [form, setForm] = useState<Record<FieldKey, string>>({
    visitor_name: "", company: "", staff: "", purpose: initialPurpose,
  });
  const [focusedField, setFocusedField] = useState<FieldKey>("visitor_name");
  const [shifted, setShifted] = useState(false);
  const [isKana, setIsKana] = useState(false);
  const [romajiBuffer, setRomajiBuffer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState("");

  const resetIdle = useCallback(() => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(onIdle, settings.kiosk_idle_timeout_sec * 1000);
  }, [onIdle, settings.kiosk_idle_timeout_sec]);

  useEffect(() => {
    resetIdle();
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => { if (idleRef.current) clearTimeout(idleRef.current); clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const commitBuffer = (field: FieldKey, buf: string) => {
    if (buf.length === 0) return;
    const committed = buf === "n" ? "ん" : buf;
    setForm(f => ({ ...f, [field]: f[field] + committed }));
    setRomajiBuffer("");
  };

  const handleKey = (key: string) => {
    resetIdle();
    if (key === "⌫") {
      if (isKana && romajiBuffer.length > 0) {
        setRomajiBuffer(b => b.slice(0, -1));
      } else {
        setForm(f => ({ ...f, [focusedField]: f[focusedField].slice(0, -1) }));
      }
    } else if (key === "shift") {
      setShifted(s => !s);
    } else if (key === "space") {
      if (isKana) commitBuffer(focusedField, romajiBuffer);
      setForm(f => ({ ...f, [focusedField]: f[focusedField] + " " }));
    } else if (key === "kana") {
      commitBuffer(focusedField, romajiBuffer);
      setIsKana(k => !k);
      setShifted(false);
    } else if (isKana && /^[a-z-]$/i.test(key)) {
      const { output, pending } = convertRomaji(romajiBuffer, key.toLowerCase());
      if (output) setForm(f => ({ ...f, [focusedField]: f[focusedField] + output }));
      setRomajiBuffer(pending);
    } else {
      if (isKana && romajiBuffer.length > 0) commitBuffer(focusedField, romajiBuffer);
      const char = shifted ? key.toUpperCase() : key;
      setForm(f => ({ ...f, [focusedField]: f[focusedField] + char }));
      if (shifted) setShifted(false);
    }
  };

  const handleSubmit = async () => {
    if (isKana && romajiBuffer.length > 0) commitBuffer(focusedField, romajiBuffer);
    if (!form.visitor_name.trim()) { setError("お名前を入力してください"); return; }
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) return;
    setSubmitting(true);
    try {
      await api.createKioskReception(kioskToken, {
        visitor_name: form.visitor_name, company: form.company,
        purpose: form.purpose, staff: form.staff, method: "form",
      });
      onComplete({ name: form.visitor_name, company: form.company, staff: form.staff, purpose: form.purpose });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付に失敗しました");
      setSubmitting(false);
    }
  };

  return (
    <KioskScaler bg="#faf8f4">
      <div
        style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}
        onClick={resetIdle}
      >
        <div style={{ flex: 1, padding: "16px 80px 0", display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 48, minHeight: 0 }}>
          {/* Left: fields */}
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <button
              onClick={onBack}
              style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8, padding: "10px 18px", background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 999, fontSize: 14, color: "#6b6559", marginBottom: 16, cursor: "pointer", fontFamily: "inherit" }}
            >
              ← 戻る
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 18 }}>
              <div style={{ fontSize: 14, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, fontFamily: "Inter, system-ui, sans-serif" }}>FORM</div>
              <div style={{ display: "flex", gap: 6 }}>
                <span style={{ width: 32, height: 5, borderRadius: 3, background: "#4a7c4e" }} />
                <span style={{ width: 32, height: 5, borderRadius: 3, background: "#efece5" }} />
              </div>
            </div>

            <div style={{ fontSize: 44, fontWeight: 600, color: "#1d1a15", letterSpacing: -1.4, lineHeight: 1.15, marginBottom: 22 }}>
              ご来訪情報を<br />ご記入ください
            </div>

            {error && (
              <div style={{ marginBottom: 14, background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.35)", borderRadius: 12, padding: "12px 16px", color: "#a84238", fontSize: 15 }}>{error}</div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
              {FIELDS.slice(0, 2).map(f => {
                const isFocused = focusedField === f.key;
                const pending = isFocused && isKana ? romajiBuffer : "";
                const displayValue = form[f.key] + pending;
                return (
                  <div key={f.key}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7 }}>
                      <span style={{ fontSize: 15, fontWeight: 600, color: "#2d2a24" }}>{f.label}</span>
                      {f.required && <span style={{ fontSize: 10, color: "#a84238", background: "#f6e0dc", padding: "2px 8px", borderRadius: 4, fontWeight: 600, letterSpacing: 0.5 }}>必須</span>}
                    </div>
                    <div
                      onClick={() => { if (isKana && romajiBuffer.length > 0) commitBuffer(focusedField, romajiBuffer); setFocusedField(f.key); resetIdle(); }}
                      style={{ background: "#fffefb", border: `2px solid ${isFocused ? "#4a7c4e" : form[f.key] ? "#4a7c4e" : "#d8d3c7"}`, borderRadius: 11, padding: "14px 20px", fontSize: 22, color: displayValue ? "#2d2a24" : "#a8a198", boxShadow: isFocused ? "0 0 0 4px #eaf0e8" : "none", cursor: "default", minHeight: 60, display: "flex", alignItems: "center", transition: "border-color 0.15s, box-shadow 0.15s" }}
                    >
                      {displayValue || f.placeholder}
                      {isFocused && <span style={{ display: "inline-block", width: 2, height: 26, background: "#4a7c4e", marginLeft: 4, animation: "kiosk-cursor-blink 1s step-end infinite" }} />}
                    </div>
                  </div>
                );
              })}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                {FIELDS.slice(2).map(f => {
                  const isFocused = focusedField === f.key;
                  const pending = isFocused && isKana ? romajiBuffer : "";
                  const displayValue = form[f.key] + pending;
                  return (
                    <div key={f.key}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7 }}>
                        <span style={{ fontSize: 15, fontWeight: 600, color: "#2d2a24" }}>{f.label}</span>
                      </div>
                      <div
                        onClick={() => { if (isKana && romajiBuffer.length > 0) commitBuffer(focusedField, romajiBuffer); setFocusedField(f.key); resetIdle(); }}
                        style={{ background: "#fffefb", border: `2px solid ${isFocused ? "#4a7c4e" : form[f.key] ? "#4a7c4e" : "#d8d3c7"}`, borderRadius: 11, padding: "14px 20px", fontSize: 20, color: displayValue ? "#2d2a24" : "#a8a198", boxShadow: isFocused ? "0 0 0 4px #eaf0e8" : "none", cursor: "default", minHeight: 56, display: "flex", alignItems: "center", transition: "border-color 0.15s, box-shadow 0.15s" }}
                      >
                        {displayValue || f.placeholder}
                        {isFocused && <span style={{ display: "inline-block", width: 2, height: 22, background: "#4a7c4e", marginLeft: 4, animation: "kiosk-cursor-blink 1s step-end infinite" }} />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Right: keyboard */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", minHeight: 0, paddingBottom: 24 }}>
            <div style={{ background: "#f4f1ea", borderRadius: 18, padding: 12, border: "1px solid #efece5" }}>
              {KB_ROWS.map((row, ri) => (
                <div key={ri} style={{ display: "flex", gap: 5, marginBottom: ri < KB_ROWS.length - 1 ? 5 : 0, justifyContent: "center", paddingLeft: ri === 2 ? 24 : 0 }}>
                  {row.map((k) => {
                    const isShift = k === "shift";
                    const isDel = k === "⌫";
                    const isWide = isShift || isDel;
                    return (
                      <button
                        key={k}
                        onMouseDown={(e) => { e.preventDefault(); handleKey(k); }}
                        onTouchStart={(e) => { e.preventDefault(); handleKey(k); }}
                        style={{
                          flex: isWide ? 1.8 : 1, height: 62,
                          background: (isShift && shifted) ? "#1d1a15" : "#fffefb",
                          border: "1px solid #d8d3c7", borderRadius: 9,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: isWide ? 14 : 24, fontWeight: isWide ? 600 : 400,
                          color: (isShift && shifted) ? "#ffffff" : "#2d2a24",
                          cursor: "pointer", fontFamily: "Inter, system-ui, sans-serif",
                          userSelect: "none", transition: "background 0.1s",
                        }}
                      >
                        {k === "shift" ? "⇧" : (shifted && !isShift && !isDel ? k.toUpperCase() : k)}
                      </button>
                    );
                  })}
                </div>
              ))}
              <div style={{ display: "flex", gap: 5, marginTop: 5, justifyContent: "center" }}>
                <button
                  onMouseDown={(e) => { e.preventDefault(); handleKey("kana"); }}
                  onTouchStart={(e) => { e.preventDefault(); handleKey("kana"); }}
                  style={{ flex: 2, height: 62, background: isKana ? "#1d1a15" : "#fffefb", border: "1px solid #d8d3c7", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: isKana ? "#ffffff" : "#6b6559", cursor: "pointer", fontFamily: "inherit", userSelect: "none", transition: "background 0.1s, color 0.1s" }}
                >
                  かな / ABC
                </button>
                <button
                  onMouseDown={(e) => { e.preventDefault(); handleKey("space"); }}
                  onTouchStart={(e) => { e.preventDefault(); handleKey("space"); }}
                  style={{ flex: 5, height: 62, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 9, cursor: "pointer", userSelect: "none" }}
                />
                <button
                  onClick={handleSubmit}
                  disabled={submitting}
                  style={{ flex: 2, height: 62, background: submitting ? "#7a9e7d" : "#1d1a15", borderRadius: 9, border: "none", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, color: "#ffffff", fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer", fontFamily: "inherit", userSelect: "none" }}
                >
                  {submitting ? (
                    <div style={{ width: 22, height: 22, borderRadius: "50%", border: "2.5px solid rgba(255,255,255,0.3)", borderTopColor: "#ffffff", animation: "kiosk-spin 0.7s linear infinite" }} />
                  ) : "送信 →"}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div style={{ padding: "12px 80px 20px", display: "flex", alignItems: "center", color: "#a8a198", fontSize: 13, flexShrink: 0 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14 }}>{now}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: "JetBrains Mono, monospace" }}>{deviceName || "kiosk"}</span>
        </div>
      </div>
    </KioskScaler>
  );
}

// ─── CallingScreen ────────────────────────────────────────────────────────────
function CallingScreen({
  settings,
  onNext,
}: {
  settings: PublicTenantSettings;
  onNext: () => void;
}) {
  const [now, setNow] = useState("");
  const brandColor = settings.brand_color;

  useEffect(() => {
    const id = setTimeout(onNext, 4_000);
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const clockId = setInterval(tick, 30_000);
    return () => { clearTimeout(id); clearInterval(clockId); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <KioskScaler bg="#faf8f4">
      <div style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "auto 1fr", gap: 80, padding: "0 100px", alignItems: "center", minHeight: 0 }}>
          {/* Concentric rings + bell */}
          <div style={{ position: "relative", width: 360, height: 360, flexShrink: 0 }}>
            {[1, 0.7, 0.4].map((s, i) => (
              <div key={i} style={{ position: "absolute", inset: `${(1 - s) * 40}%`, border: `2px solid ${brandColor}`, borderRadius: "50%", opacity: 0.15 + i * 0.18, animation: `kiosk-pulse-ring${i === 0 ? "-3" : i === 1 ? "-2" : ""} 2.6s ease-in-out ${i * 0.25}s infinite` }} />
            ))}
            <div style={{ position: "absolute", inset: "32%", background: brandColor, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "#ffffff", boxShadow: `0 8px 32px ${brandColor}72` }}>
              <BellLargeIcon />
            </div>
          </div>

          {/* Text */}
          <div>
            <div style={{ fontSize: 18, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, marginBottom: 18, fontFamily: "Inter, system-ui, sans-serif" }}>CALLING</div>
            <div style={{ fontSize: 96, fontWeight: 600, color: "#1d1a15", letterSpacing: -3, lineHeight: 1.05, marginBottom: 24 }}>
              {settings.kiosk_calling_message}
            </div>
            <div style={{ fontSize: 22, color: "#6b6559", lineHeight: 1.7, maxWidth: 720, marginBottom: 28 }}>
              まもなく担当者がお迎えにあがります<br />恐れ入りますが、こちらでお待ちください
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{ width: 14, height: 14, borderRadius: "50%", background: brandColor, opacity: i === 1 ? 1 : 0.25, animation: `kiosk-dot-bounce 1.5s ${i * 0.18}s ease-in-out infinite` }} />
              ))}
            </div>
          </div>
        </div>

        {/* Notification card */}
        <div style={{ padding: "0 100px 32px", flexShrink: 0 }}>
          <div style={{ background: "#fffefb", border: "1px solid #efece5", borderRadius: 18, padding: 22, display: "flex", alignItems: "center", gap: 18, boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)" }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: `${brandColor}22`, color: brandColor, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <CheckIconSmall />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 17, fontWeight: 600, color: "#2d2a24" }}>通知を送信しました</div>
              <div style={{ fontSize: 13, color: "#a8a198", marginTop: 3 }}>Slack · スマートフォン</div>
            </div>
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14, color: "#6b6559" }}>{now}</div>
          </div>
        </div>
      </div>
    </KioskScaler>
  );
}

// ─── CompleteScreen ───────────────────────────────────────────────────────────
function CompleteScreen({
  settings,
  name,
  staff,
  onReturn,
}: {
  settings: PublicTenantSettings;
  name: string;
  staff: string;
  onReturn: () => void;
}) {
  const returnSec = settings.kiosk_complete_timeout_sec;
  const [count, setCount] = useState(returnSec);
  const [now, setNow] = useState("");
  const brandColor = settings.brand_color;

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setNow(`${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const clockId = setInterval(tick, 30_000);

    const countId = setInterval(() => {
      setCount(c => {
        if (c <= 1) { clearInterval(countId); onReturn(); return 0; }
        return c - 1;
      });
    }, 1000);

    return () => { clearInterval(clockId); clearInterval(countId); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const progress = ((returnSec - count) / returnSec) * 100;
  const visitorName = name || "お客様";

  return (
    <KioskScaler bg="#faf8f4">
      <div style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
        <div style={{ height: 6, background: `linear-gradient(90deg, ${brandColor}, #b8763a, #2e6b8e)`, flexShrink: 0 }} />

        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 56, padding: "16px 80px 0", minHeight: 0 }}>
          {/* Left: welcome */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div style={{ width: 84, height: 84, borderRadius: 22, background: `${brandColor}22`, color: brandColor, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 24, animation: "kiosk-scale-in 0.5s cubic-bezier(0.2,0.9,0.3,1.1)" }}>
              <CheckIconLarge size={50} stroke={2.4} />
            </div>

            <div style={{ fontSize: 16, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, marginBottom: 12, fontFamily: "Inter, system-ui, sans-serif" }}>WELCOME</div>

            <div style={{ fontSize: 92, fontWeight: 600, color: "#1d1a15", letterSpacing: -3, lineHeight: 1.04, marginBottom: 16 }}>
              {visitorName}<br />
              <span style={{ color: "#6b6559", fontSize: 56, fontWeight: 400 }}>様</span>
            </div>

            <div style={{ fontSize: 26, color: "#6b6559", lineHeight: 1.5 }}>お待ちしておりました</div>

            <div style={{ marginTop: 36, display: "flex", alignItems: "center", gap: 14 }}>
              <ClockIcon />
              <span style={{ fontSize: 14, color: "#6b6559", flex: 1 }}>この画面は <b>{count}秒後</b> に待機画面へ戻ります</span>
              <div style={{ width: 220, height: 4, background: "#efece5", borderRadius: 2 }}>
                <div style={{ width: `${progress}%`, height: "100%", background: brandColor, borderRadius: 2, transition: "width 1s linear" }} />
              </div>
            </div>
          </div>

          {/* Right: visit details */}
          <div style={{ display: "flex", flexDirection: "column", gap: 18, paddingBottom: 32, justifyContent: "center" }}>
            <div style={{ background: "#fffefb", border: "1px solid #efece5", borderRadius: 18, padding: 26, boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22 }}>
                {[
                  { label: "ご担当", value: staff || "—" },
                  { label: "ご予約時間", value: now, mono: true },
                  { label: "通知方法", value: "Slack / プッシュ" },
                  { label: "ステータス", value: "通知済み" },
                ].map(({ label, value, mono }, i) => (
                  <div key={i}>
                    <div style={{ fontSize: 11, color: "#a8a198", letterSpacing: 1, fontWeight: 600, textTransform: "uppercase" as const, marginBottom: 6, fontFamily: "Inter, system-ui, sans-serif" }}>{label}</div>
                    <div style={{ fontSize: 22, fontWeight: 600, color: "#2d2a24", fontFamily: mono ? "JetBrains Mono, monospace" : "inherit" }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ background: "#1d1a15", color: "#ffffff", borderRadius: 18, padding: 26, display: "flex", alignItems: "center", gap: 22 }}>
              <div style={{ width: 68, height: 68, borderRadius: 16, background: "rgba(255,255,255,0.1)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <CompleteArrowIcon />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 6, fontFamily: "Inter, system-ui, sans-serif" }}>NEXT — 受付へ</div>
                <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: -0.8, lineHeight: 1.15 }}>{settings.kiosk_complete_message}</div>
                <div style={{ fontSize: 15, color: "rgba(255,255,255,0.6)", marginTop: 4 }}>恐れ入りますが、こちらでお待ちください</div>
              </div>
              <div style={{ width: 68, height: 68, borderRadius: 16, background: "#fffefb", color: "#1d1a15", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, fontWeight: 700, fontFamily: "Inter, system-ui, sans-serif", flexShrink: 0 }}>✓</div>
            </div>
          </div>
        </div>
      </div>
    </KioskScaler>
  );
}

// ─── KioskFlow (main export) ──────────────────────────────────────────────────
export function KioskFlow() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [screen, setScreen] = useState<KioskScreen>(() => {
    const s = searchParams.get("screen");
    return VALID_SCREENS.includes(s as KioskScreen) ? (s as KioskScreen) : "idle";
  });

  const [flowData, setFlowData] = useState<FlowData>({
    name: searchParams.get("name") ?? "",
    company: searchParams.get("company") ?? "",
    staff: searchParams.get("staff") ?? "",
    purpose: searchParams.get("purpose") ?? "",
  });

  const [settings, setSettings] = useState<PublicTenantSettings>(
    () => getCachedKioskSettings(params.tenant) ?? DEFAULT_SETTINGS
  );
  const [scheduleItems, setScheduleItems] = useState<KioskPlaylistItem[]>([]);
  const [deviceName, setDeviceName] = useState("");
  const [ready, setReady] = useState(false);

  // Clean URL params after reading initial state
  useEffect(() => {
    if (searchParams.get("screen") || searchParams.get("name") || searchParams.get("purpose")) {
      window.history.replaceState({}, "", `/${params.tenant}/kiosk`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load shared data once; keep schedule fresh every 60s
  useEffect(() => {
    const token = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!token) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }
    setDeviceName(localStorage.getItem(KIOSK_NAME_KEY) ?? "");

    api.getPublicTenantSettings(params.tenant)
      .then(s => { setSettings(s); setCachedKioskSettings(params.tenant, s); })
      .catch(() => {});

    const fetchSchedule = async () => {
      try {
        const data = await api.getKioskSchedule(token);
        setScheduleItems(data.playlist?.items ?? []);
      } catch (err) {
        if (err instanceof Error && err.message === "Invalid kiosk token") {
          localStorage.removeItem(KIOSK_TOKEN_KEY);
          router.replace(`/${params.tenant}/kiosk/setup`);
        }
      }
    };

    fetchSchedule().then(() => setReady(true));
    const id = setInterval(fetchSchedule, 60_000);
    return () => clearInterval(id);
  }, [params.tenant, router]);

  const navigate = (nextScreen: KioskScreen, data?: Partial<FlowData>) => {
    if (data) setFlowData(prev => ({ ...prev, ...data }));
    setScreen(nextScreen);
  };

  const handleReceptionComplete = (data: FlowData) => {
    setFlowData(data);
    setScreen("calling");
  };

  if (!ready) {
    return (
      <div style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 18 }}>読み込み中…</div>
      </div>
    );
  }

  return (
    <div key={screen} style={{ animation: "kiosk-fade-in 0.18s ease-out" }}>
      {screen === "idle" && (
        <IdleScreen
          settings={settings}
          items={scheduleItems}
          onStart={() => setScreen("top")}
        />
      )}
      {screen === "top" && (
        <TopScreen
          settings={settings}
          deviceName={deviceName}
          tenant={params.tenant}
          onNavigate={navigate}
          onIdle={() => setScreen("idle")}
        />
      )}
      {screen === "reception" && (
        <ReceptionScreen
          settings={settings}
          deviceName={deviceName}
          initialPurpose={flowData.purpose}
          onComplete={handleReceptionComplete}
          onBack={() => setScreen("top")}
          onIdle={() => setScreen("idle")}
        />
      )}
      {screen === "calling" && (
        <CallingScreen
          settings={settings}
          onNext={() => setScreen("complete")}
        />
      )}
      {screen === "complete" && (
        <CompleteScreen
          settings={settings}
          name={flowData.name}
          staff={flowData.staff}
          onReturn={() => setScreen("idle")}
        />
      )}
    </div>
  );
}
