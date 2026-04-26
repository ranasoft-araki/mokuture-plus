"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

const QRIcon = () => (
  <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="0.5"/>
    <rect x="14" y="3" width="7" height="7" rx="0.5"/>
    <rect x="3" y="14" width="7" height="7" rx="0.5"/>
    <path d="M14 14h3v3h-3zM20 14h1M14 20h1M17 18v3M20 17v4"/>
  </svg>
);

const EditIcon = () => (
  <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>
  </svg>
);

const ArrowLeftIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
    stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 12H5M12 5l-7 7 7 7"/>
  </svg>
);

export default function KioskTopPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pressedCard, setPressedCard] = useState<string | null>(null);

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
    return () => { if (idleRef.current) clearTimeout(idleRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCardPress = (id: string, dest: string) => {
    resetIdle();
    setPressedCard(id);
    setTimeout(() => { setPressedCard(null); router.push(dest); }, 180);
  };

  const back = () => router.push(`/${params.tenant}/kiosk`);

  return (
    <div
      className="w-screen h-screen flex flex-col select-none overflow-hidden"
      style={{
        background: "#faf8f4",
        animation: "kiosk-screen-in 0.35s cubic-bezier(0.2,0.7,0.3,1)",
      }}
      onClick={resetIdle}
    >
      {/* Header */}
      <div style={{
        background: "#4a7c4e", padding: "0 28px",
        height: 88, display: "flex", alignItems: "center", gap: 16, flexShrink: 0,
      }}>
        <button
          onClick={back}
          style={{
            width: 44, height: 44, borderRadius: 12,
            background: "rgba(255,255,255,0.15)", border: "none",
            display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
          }}
        >
          <ArrowLeftIcon />
        </button>
        <h1 style={{ color: "white", fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          受付
        </h1>
        <div style={{ flex: 1 }} />
        <div style={{ color: "rgba(255,255,255,0.55)", fontSize: 12, fontFamily: "monospace" }}>
          kiosk-hq-1f-01
        </div>
      </div>

      {/* Body */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        padding: "40px 32px 48px",
      }}>
        <p style={{
          color: "#6b6559", fontSize: 16, margin: "0 0 32px",
          lineHeight: 1.5, letterSpacing: "0.01em",
          animation: "kiosk-fade-up 0.35s 0.05s both",
        }}>
          受付方法をお選びください。
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 20, flex: 1 }}>
          {/* QR Card */}
          <button
            onClick={() => handleCardPress("qr", `/${params.tenant}/kiosk/qr`)}
            style={{
              flex: 1, background: "#fffefb",
              border: `2px solid ${pressedCard === "qr" ? "#4a7c4e" : "#efece5"}`,
              borderRadius: 20, padding: "32px 28px",
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 18,
              cursor: "pointer", textAlign: "center",
              boxShadow: pressedCard === "qr"
                ? "0 0 0 4px #eaf0e8"
                : "0 2px 8px rgba(29,26,21,0.06), 0 8px 24px rgba(29,26,21,0.04)",
              transform: pressedCard === "qr" ? "scale(0.97)" : "scale(1)",
              transition: "transform 0.15s cubic-bezier(0.2,0.7,0.3,1), border-color 0.15s, box-shadow 0.15s",
              animation: "kiosk-fade-up 0.4s 0.12s both",
            }}
          >
            <div style={{
              width: 72, height: 72, borderRadius: 20,
              background: "#eaf0e8", color: "#4a7c4e",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              <QRIcon />
            </div>
            <div>
              <div style={{ fontSize: 22, fontWeight: 600, color: "#2d2a24", letterSpacing: "-0.02em", marginBottom: 6 }}>
                QRコードで受付
              </div>
              <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.5 }}>
                事前に受け取ったQRコードをかざしてください
              </div>
            </div>
          </button>

          {/* Form Card */}
          <button
            onClick={() => handleCardPress("form", `/${params.tenant}/kiosk/reception`)}
            style={{
              flex: 1, background: "#fffefb",
              border: `2px solid ${pressedCard === "form" ? "#4a7c4e" : "#efece5"}`,
              borderRadius: 20, padding: "32px 28px",
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 18,
              cursor: "pointer", textAlign: "center",
              boxShadow: pressedCard === "form"
                ? "0 0 0 4px #eaf0e8"
                : "0 2px 8px rgba(29,26,21,0.06), 0 8px 24px rgba(29,26,21,0.04)",
              transform: pressedCard === "form" ? "scale(0.97)" : "scale(1)",
              transition: "transform 0.15s cubic-bezier(0.2,0.7,0.3,1), border-color 0.15s, box-shadow 0.15s",
              animation: "kiosk-fade-up 0.4s 0.22s both",
            }}
          >
            <div style={{
              width: 72, height: 72, borderRadius: 20,
              background: "#eaf0e8", color: "#4a7c4e",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              <EditIcon />
            </div>
            <div>
              <div style={{ fontSize: 22, fontWeight: 600, color: "#2d2a24", letterSpacing: "-0.02em", marginBottom: 6 }}>
                入力して受付
              </div>
              <div style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.5 }}>
                お名前・会社名・用件をご入力ください
              </div>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
