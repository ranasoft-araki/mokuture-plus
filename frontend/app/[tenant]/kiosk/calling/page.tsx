"use client";

import { useEffect, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

const AUTO_ADVANCE_MS = 3_500;

export default function KioskCallingPage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "";
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      router.push(`/${params.tenant}/kiosk/complete?name=${encodeURIComponent(name)}`);
    }, AUTO_ADVANCE_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [params.tenant, router, name]);

  return (
    <div
      className="w-screen h-screen flex flex-col items-center justify-center select-none overflow-hidden"
      style={{
        background: "#4a7c4e",
        position: "relative",
        animation: "kiosk-screen-in 0.4s cubic-bezier(0.2,0.7,0.3,1)",
      }}
    >
      {/* Radial glow */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: "radial-gradient(circle at 50% 46%, rgba(255,255,255,0.09) 0%, transparent 65%)",
        pointerEvents: "none",
      }} />

      {/* Logo */}
      <div style={{
        position: "absolute", top: 40, left: 0, right: 0,
        display: "flex", justifyContent: "center", zIndex: 1,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "rgba(255,255,255,0.2)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="9" r="5"/><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5"/><path d="M12 4v10"/>
            </svg>
          </div>
          <span style={{ color: "rgba(255,255,255,0.9)", fontSize: 15, fontWeight: 600 }}>
            mokuture<span style={{ color: "rgba(255,255,255,0.45)" }}>+</span>
          </span>
        </div>
      </div>

      {/* Pulse rings + icon */}
      <div style={{ position: "relative", width: 200, height: 200, marginBottom: 52, zIndex: 1 }}>
        {/* Outermost ring */}
        <div style={{
          position: "absolute", inset: 0,
          borderRadius: "50%",
          background: "rgba(255,255,255,0.1)",
          border: "1.5px solid rgba(255,255,255,0.2)",
          animation: "kiosk-pulse-ring-3 2.6s ease-in-out 0s infinite",
        }} />
        {/* Middle ring */}
        <div style={{
          position: "absolute", inset: "20px",
          borderRadius: "50%",
          background: "rgba(255,255,255,0.12)",
          border: "1.5px solid rgba(255,255,255,0.25)",
          animation: "kiosk-pulse-ring-2 2.6s ease-in-out 0.25s infinite",
        }} />
        {/* Inner ring */}
        <div style={{
          position: "absolute", inset: "40px",
          borderRadius: "50%",
          background: "rgba(255,255,255,0.16)",
          border: "1.5px solid rgba(255,255,255,0.35)",
          animation: "kiosk-pulse-ring 2.6s ease-in-out 0.5s infinite",
        }} />
        {/* Center icon */}
        <div style={{
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div style={{
            width: 72, height: 72, borderRadius: "50%",
            background: "rgba(255,255,255,0.22)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "white",
          }}>
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 8a6 6 0 0112 0v5l2 3H4l2-3z"/>
              <path d="M10 19a2 2 0 004 0"/>
            </svg>
          </div>
        </div>
      </div>

      {/* Text */}
      <div style={{ textAlign: "center", padding: "0 48px", zIndex: 1 }}>
        <p style={{
          color: "white", fontSize: 26, fontWeight: 600,
          letterSpacing: "-0.02em", lineHeight: 1.3,
          margin: "0 0 14px",
        }}>
          担当者を呼び出しています
        </p>
        <p style={{ color: "rgba(255,255,255,0.7)", fontSize: 17, margin: "0 0 36px" }}>
          少々お待ちください
        </p>

        {/* Dot loader */}
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 10, height: 10, borderRadius: "50%", background: "white",
              animation: `kiosk-dot-bounce 1.5s ${i * 0.18}s ease-in-out infinite`,
            }} />
          ))}
        </div>
      </div>
    </div>
  );
}
