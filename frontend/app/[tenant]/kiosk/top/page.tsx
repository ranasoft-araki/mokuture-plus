"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { KioskScaler } from "@/components/KioskScaler";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

const ReceptionIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

const QRIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <path d="M14 14h3v3h-3zM20 14h1M14 20h1M17 18v3M20 17v4" />
  </svg>
);

const TruckIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="1" y="3" width="15" height="13" rx="1" />
    <path d="M16 8h4l3 3v5h-7V8z" />
    <circle cx="5.5" cy="18.5" r="2.5" />
    <circle cx="18.5" cy="18.5" r="2.5" />
  </svg>
);

const MoreIcon = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
    <circle cx="5" cy="12" r="1" />
  </svg>
);

const ArrowIcon = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);

const BellIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </svg>
);

interface Tile {
  Icon: React.ComponentType;
  label: string;
  sub: string;
  primary?: boolean;
  dest: string;
}

export default function KioskTopPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pressed, setPressed] = useState<number | null>(null);
  const [now, setNow] = useState("");

  const resetIdle = () => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => router.push(`/${params.tenant}/kiosk`), IDLE_TIMEOUT_MS);
  };

  useEffect(() => {
    if (!localStorage.getItem(KIOSK_TOKEN_KEY)) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }
    resetIdle();
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => {
      if (idleRef.current) clearTimeout(idleRef.current);
      clearInterval(id);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tiles: Tile[] = [
    { Icon: ReceptionIcon, label: "ご訪問",     sub: "お約束の方",             primary: true, dest: `/${params.tenant}/kiosk/reception` },
    { Icon: QRIcon,        label: "QR で受付",  sub: "招待コードをお持ちの方",               dest: `/${params.tenant}/kiosk/qr` },
    { Icon: TruckIcon,     label: "配送・宅配便", sub: "お荷物のお届け",                     dest: `/${params.tenant}/kiosk/reception?purpose=${encodeURIComponent("配送・宅配便")}` },
    { Icon: MoreIcon,      label: "その他",      sub: "上記以外のご用件",                    dest: `/${params.tenant}/kiosk/reception?purpose=${encodeURIComponent("その他")}` },
  ];

  const handleTile = (i: number, dest: string) => {
    resetIdle();
    setPressed(i);
    setTimeout(() => { setPressed(null); router.push(dest); }, 160);
  };

  return (
    <KioskScaler bg="#faf8f4">
      <div
        style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}
        onClick={resetIdle}
      >
        {/* Body */}
        <div style={{ flex: 1, padding: "28px 80px 0", display: "flex", flexDirection: "column", minHeight: 0 }}>
          {/* Heading */}
          <div style={{ display: "flex", alignItems: "flex-end", gap: 40, marginBottom: 40 }}>
            <div>
              <div style={{ fontSize: 14, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase", marginBottom: 12, fontFamily: "Inter, system-ui, sans-serif" }}>RECEPTION</div>
              <div style={{ fontSize: 78, fontWeight: 600, color: "#1d1a15", letterSpacing: -2.5, lineHeight: 1.1 }}>ようこそ</div>
            </div>
            <div style={{ paddingBottom: 16, fontSize: 22, color: "#6b6559" }}>ご用件をお選びください</div>
          </div>

          {/* 4-tile grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 22, flex: 1, minHeight: 0 }}>
            {tiles.map((tile, i) => {
              const isPrimary = tile.primary;
              return (
                <button
                  key={i}
                  onClick={() => handleTile(i, tile.dest)}
                  style={{
                    background: isPrimary ? "#1d1a15" : "#fffefb",
                    color: isPrimary ? "#ffffff" : "#2d2a24",
                    border: `2px solid ${isPrimary ? "#1d1a15" : "#efece5"}`,
                    borderRadius: 22,
                    padding: "36px 32px",
                    display: "flex", flexDirection: "column", justifyContent: "space-between",
                    position: "relative",
                    cursor: "pointer",
                    transform: pressed === i ? "scale(0.97)" : "scale(1)",
                    transition: "transform 0.14s cubic-bezier(0.2,0.8,0.3,1)",
                    textAlign: "left",
                    fontFamily: "inherit",
                  }}
                >
                  <div style={{
                    width: 76, height: 76, borderRadius: 18,
                    background: isPrimary ? "rgba(255,255,255,0.1)" : "#eaf0e8",
                    color: isPrimary ? "#ffffff" : "#3a6240",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <tile.Icon />
                  </div>
                  <div>
                    <div style={{ fontSize: 38, fontWeight: 600, letterSpacing: -1, lineHeight: 1.1 }}>
                      {tile.label}
                    </div>
                    <div style={{ fontSize: 16, marginTop: 8, color: isPrimary ? "rgba(255,255,255,0.6)" : "#6b6559" }}>
                      {tile.sub}
                    </div>
                  </div>
                  <div style={{ position: "absolute", top: 32, right: 32, color: isPrimary ? "rgba(255,255,255,0.5)" : "#a8a198" }}>
                    <ArrowIcon />
                  </div>
                </button>
              );
            })}
          </div>

          {/* Help bar */}
          <div style={{
            marginTop: 24, marginBottom: 24,
            background: "#f4f1ea", borderRadius: 16, padding: "18px 26px",
            display: "flex", alignItems: "center", gap: 18,
            border: "1px solid #efece5",
            flexShrink: 0,
          }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, background: "#fffefb",
              display: "flex", alignItems: "center", justifyContent: "center", color: "#b8763a",
            }}>
              <BellIcon />
            </div>
            <div style={{ flex: 1, fontSize: 16, color: "#2d2a24" }}>
              お困りの方は <b>受付スタッフ</b> までお声がけください
            </div>
            <div style={{ fontSize: 13, color: "#a8a198" }}>受付時間 09:00–18:00</div>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: "0 80px 28px",
          display: "flex", alignItems: "center",
          color: "#a8a198", fontSize: 13,
          flexShrink: 0,
        }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14 }}>{now}</span>
          <span style={{ flex: 1 }} />
          <span style={{ color: "#a8a198" }}>60秒で待機画面に戻ります</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: "JetBrains Mono, monospace" }}>kiosk-hq-1f-01</span>
        </div>
      </div>
    </KioskScaler>
  );
}
