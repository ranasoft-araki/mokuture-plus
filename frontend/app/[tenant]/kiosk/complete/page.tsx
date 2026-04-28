"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { KioskScaler } from "@/components/KioskScaler";
import { api, getCachedKioskSettings, setCachedKioskSettings } from "@/lib/api";

const DEFAULT_RETURN_SEC = 60;
const DEFAULT_COMPLETE_MSG = "担当者がお迎えします";

const CheckIcon = ({ size = 50, stroke = 2.4 }: { size?: number; stroke?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12l5 5L20 6" strokeDasharray="60" strokeDashoffset="60" style={{ animation: "kiosk-check-draw 0.6s 0.3s cubic-bezier(0.2,0.9,0.3,1) forwards" }} />
  </svg>
);

const ArrowIcon = () => (
  <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);

const ClockIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" />
  </svg>
);

export default function KioskWelcomePage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "お客様";
  const staff = searchParams.get("staff") ?? "";
  const _cached = getCachedKioskSettings(params.tenant);
  const [autoReturnSec, setAutoReturnSec] = useState(_cached?.kiosk_complete_timeout_sec ?? DEFAULT_RETURN_SEC);
  const [count, setCount] = useState(_cached?.kiosk_complete_timeout_sec ?? DEFAULT_RETURN_SEC);
  const [completeMessage, setCompleteMessage] = useState(_cached?.kiosk_complete_message ?? DEFAULT_COMPLETE_MSG);
  const [brandColor, setBrandColor] = useState(_cached?.brand_color ?? "#4a7c4e");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [now, setNow] = useState("");

  useEffect(() => {
    let returnSec = _cached?.kiosk_complete_timeout_sec ?? DEFAULT_RETURN_SEC;
    api.getPublicTenantSettings(params.tenant)
      .then((s) => {
        returnSec = s.kiosk_complete_timeout_sec;
        setAutoReturnSec(returnSec);
        setCount(returnSec);
        setCompleteMessage(s.kiosk_complete_message);
        setBrandColor(s.brand_color);
        setCachedKioskSettings(params.tenant, s);
      })
      .catch(() => {})
      .finally(() => {
        timerRef.current = setInterval(() => {
          setCount((c) => {
            if (c <= 1) {
              clearInterval(timerRef.current!);
              router.push(`/${params.tenant}/kiosk`);
              return 0;
            }
            return c - 1;
          });
        }, 1000);
      });
    const tick = () => {
      const d = new Date();
      setNow(`${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      clearInterval(id);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.tenant, router]);

  const progress = ((autoReturnSec - count) / autoReturnSec) * 100;

  return (
    <KioskScaler bg="#faf8f4">
      <div style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
        {/* Gradient bar */}
        <div style={{ height: 6, background: `linear-gradient(90deg, ${brandColor}, #b8763a, #2e6b8e)`, flexShrink: 0 }} />



        {/* Body: left=welcome, right=details */}
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 56, padding: "16px 80px 0", minHeight: 0 }}>
          {/* Left: welcome */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div style={{
              width: 84, height: 84, borderRadius: 22, background: `${brandColor}22`,
              color: brandColor, display: "flex", alignItems: "center", justifyContent: "center",
              marginBottom: 24,
              animation: "kiosk-scale-in 0.5s cubic-bezier(0.2,0.9,0.3,1.1)",
            }}>
              <CheckIcon size={50} stroke={2.4} />
            </div>

            <div style={{ fontSize: 16, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, marginBottom: 12, fontFamily: "Inter, system-ui, sans-serif" }}>WELCOME</div>

            <div style={{ fontSize: 92, fontWeight: 600, color: "#1d1a15", letterSpacing: -3, lineHeight: 1.04, marginBottom: 16 }}>
              {name}<br />
              <span style={{ color: "#6b6559", fontSize: 56, fontWeight: 400 }}>様</span>
            </div>

            <div style={{ fontSize: 26, color: "#6b6559", lineHeight: 1.5 }}>
              お待ちしておりました
            </div>

            <div style={{ marginTop: 36, display: "flex", alignItems: "center", gap: 14 }}>
              <ClockIcon />
              <span style={{ fontSize: 14, color: "#6b6559", flex: 1 }}>
                この画面は <b>{count}秒後</b> に待機画面へ戻ります
              </span>
              <div style={{ width: 220, height: 4, background: "#efece5", borderRadius: 2 }}>
                <div style={{ width: `${progress}%`, height: "100%", background: brandColor, borderRadius: 2, transition: "width 1s linear" }} />
              </div>
            </div>
          </div>

          {/* Right: visit details + room */}
          <div style={{ display: "flex", flexDirection: "column", gap: 18, paddingBottom: 32, justifyContent: "center" }}>
            {/* Visit details card */}
            <div style={{
              background: "#fffefb", border: "1px solid #efece5",
              borderRadius: 18, padding: 26,
              boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
            }}>
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

            {/* Room guidance card */}
            <div style={{
              background: "#1d1a15", color: "#ffffff",
              borderRadius: 18, padding: 26,
              display: "flex", alignItems: "center", gap: 22,
            }}>
              <div style={{
                width: 68, height: 68, borderRadius: 16, background: "rgba(255,255,255,0.1)",
                display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                <ArrowIcon />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", letterSpacing: 2, textTransform: "uppercase" as const, marginBottom: 6, fontFamily: "Inter, system-ui, sans-serif" }}>NEXT — 受付へ</div>
                <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: -0.8, lineHeight: 1.15 }}>
                  {completeMessage}
                </div>
                <div style={{ fontSize: 15, color: "rgba(255,255,255,0.6)", marginTop: 4 }}>
                  恐れ入りますが、こちらでお待ちください
                </div>
              </div>
              <div style={{
                width: 68, height: 68, borderRadius: 16, background: "#fffefb", color: "#1d1a15",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 28, fontWeight: 700, fontFamily: "Inter, system-ui, sans-serif",
                flexShrink: 0,
              }}>
                ✓
              </div>
            </div>
          </div>
        </div>
      </div>
    </KioskScaler>
  );
}
