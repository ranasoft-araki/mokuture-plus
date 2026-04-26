"use client";

import { useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function KioskTopPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const back = () => router.push(`/${params.tenant}/kiosk`);

  return (
    <div
      className="w-screen h-screen flex flex-col select-none"
      style={{ background: "#faf8f4" }}
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
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 5l-7 7 7 7" />
          </svg>
        </button>
        <h1 style={{ color: "white", fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          受付
        </h1>
      </div>

      {/* Body */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "0 40px", gap: 24,
      }}>
        <p style={{ color: "#6b6559", fontSize: 18, margin: "0 0 12px", textAlign: "center" }}>
          受付方法を選択してください
        </p>

        {/* QR button */}
        <button
          onClick={() => router.push(`/${params.tenant}/kiosk/qr`)}
          style={{
            width: "100%", maxWidth: 460, height: 120,
            background: "#1d1a15", color: "white",
            border: "none", borderRadius: 20, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 28, padding: "0 36px",
            boxShadow: "0 4px 20px rgba(29,26,21,0.18)",
          }}
        >
          <div style={{
            width: 60, height: 60, borderRadius: 14,
            background: "rgba(255,255,255,0.1)",
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}>
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="0.5"/>
              <rect x="14" y="3" width="7" height="7" rx="0.5"/>
              <rect x="3" y="14" width="7" height="7" rx="0.5"/>
              <path d="M14 14h3v3h-3zM20 14h1M14 20h1M17 18v3M20 17v4"/>
            </svg>
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.02em" }}>QRコードで受付</div>
            <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", marginTop: 4 }}>
              事前に受け取ったQRコードをかざしてください
            </div>
          </div>
        </button>

        {/* Form button */}
        <button
          onClick={() => router.push(`/${params.tenant}/kiosk/reception`)}
          style={{
            width: "100%", maxWidth: 460, height: 120,
            background: "#4a7c4e", color: "white",
            border: "none", borderRadius: 20, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 28, padding: "0 36px",
            boxShadow: "0 4px 20px rgba(74,124,78,0.3)",
          }}
        >
          <div style={{
            width: 60, height: 60, borderRadius: 14,
            background: "rgba(255,255,255,0.15)",
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}>
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>
            </svg>
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.02em" }}>入力して受付</div>
            <div style={{ fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 4 }}>
              お名前・会社名・用件をご入力ください
            </div>
          </div>
        </button>
      </div>
    </div>
  );
}
