"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { KioskScaler } from "@/components/KioskScaler";
import { api } from "@/lib/api";

const AUTO_ADVANCE_MS = 4_000;
const DEFAULT_CALLING_MSG = "担当者をお呼びしています";

const CheckIcon = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12l5 5L20 6" />
  </svg>
);

const BellIcon = () => (
  <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </svg>
);

export default function KioskCallingPage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "";
  const staff = searchParams.get("staff") ?? "";
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [now, setNow] = useState("");
  const [callingMessage, setCallingMessage] = useState(DEFAULT_CALLING_MSG);

  useEffect(() => {
    api.getPublicTenantSettings(params.tenant)
      .then((s) => setCallingMessage(s.kiosk_calling_message))
      .catch(() => {});

    timerRef.current = setTimeout(() => {
      const qs = new URLSearchParams({ name });
      if (staff) qs.set("staff", staff);
      router.push(`/${params.tenant}/kiosk/complete?${qs.toString()}`);
    }, AUTO_ADVANCE_MS);
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      clearInterval(id);
    };
  }, [params.tenant, router, name, staff]);

  return (
    <KioskScaler bg="#faf8f4">
      <div style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>


        {/* Body: left=pulse, right=copy */}
        <div style={{
          flex: 1,
          display: "grid", gridTemplateColumns: "auto 1fr",
          gap: 80, padding: "0 100px",
          alignItems: "center", minHeight: 0,
        }}>
          {/* Left: concentric rings + bell */}
          <div style={{ position: "relative", width: 360, height: 360, flexShrink: 0 }}>
            {[1, 0.7, 0.4].map((s, i) => (
              <div key={i} style={{
                position: "absolute",
                inset: `${(1 - s) * 40}%`,
                border: "2px solid #4a7c4e",
                borderRadius: "50%",
                opacity: 0.15 + i * 0.18,
                animation: `kiosk-pulse-ring${i === 0 ? "-3" : i === 1 ? "-2" : ""} 2.6s ease-in-out ${i * 0.25}s infinite`,
              }} />
            ))}
            <div style={{
              position: "absolute", inset: "32%",
              background: "#4a7c4e", borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#ffffff",
              boxShadow: "0 8px 32px rgba(74,124,78,0.45)",
            }}>
              <BellIcon />
            </div>
          </div>

          {/* Right: text */}
          <div>
            <div style={{ fontSize: 18, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, marginBottom: 18, fontFamily: "Inter, system-ui, sans-serif" }}>CALLING</div>
            <div style={{ fontSize: 96, fontWeight: 600, color: "#1d1a15", letterSpacing: -3, lineHeight: 1.05, marginBottom: 24 }}>
              {callingMessage}
            </div>
            <div style={{ fontSize: 22, color: "#6b6559", lineHeight: 1.7, maxWidth: 720, marginBottom: 28 }}>
              まもなく担当者がお迎えにあがります<br />
              恐れ入りますが、こちらでお待ちください
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{
                  width: 14, height: 14, borderRadius: "50%",
                  background: "#4a7c4e", opacity: i === 1 ? 1 : 0.25,
                  animation: `kiosk-dot-bounce 1.5s ${i * 0.18}s ease-in-out infinite`,
                }} />
              ))}
            </div>
          </div>
        </div>

        {/* Bottom notification card */}
        <div style={{ padding: "0 100px 32px", flexShrink: 0 }}>
          <div style={{
            background: "#fffefb", border: "1px solid #efece5",
            borderRadius: 18, padding: 22,
            display: "flex", alignItems: "center", gap: 18,
            boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
          }}>
            <div style={{
              width: 48, height: 48, borderRadius: 12, background: "#eaf0e8", color: "#3a6240",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <CheckIcon />
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
