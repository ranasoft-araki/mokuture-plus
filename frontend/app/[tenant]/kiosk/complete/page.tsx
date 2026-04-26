"use client";

import { useEffect, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

const AUTO_RETURN_MS = 10_000;

export default function CompletePage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "お客様";
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      router.push(`/${params.tenant}/kiosk`);
    }, AUTO_RETURN_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [params.tenant, router]);

  return (
    <div
      className="w-screen h-screen flex flex-col items-center justify-center cursor-pointer select-none overflow-hidden"
      style={{ background: "#4a7c4e", position: "relative" }}
      onClick={() => router.push(`/${params.tenant}/kiosk`)}
    >
      {/* radial glow */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: "radial-gradient(circle at 50% 42%, rgba(255,255,255,0.08) 0%, transparent 65%)",
        pointerEvents: "none",
      }} />

      {/* Top brand */}
      <div style={{ position: "absolute", top: 40, left: 0, right: 0, display: "flex", justifyContent: "center", zIndex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "rgba(255,255,255,0.2)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="9" r="5" /><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5" /><path d="M12 4v10" />
            </svg>
          </div>
          <span style={{ color: "rgba(255,255,255,0.9)", fontSize: 15, fontWeight: 600 }}>
            mokuture<span style={{ color: "rgba(255,255,255,0.5)" }}>+</span>
          </span>
        </div>
      </div>

      {/* Center */}
      <div className="flex flex-col items-center" style={{ zIndex: 1, padding: "0 52px", textAlign: "center" }}>
        {/* Checkmark rings */}
        <div style={{
          width: 120, height: 120, borderRadius: "50%",
          background: "rgba(255,255,255,0.18)",
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 36,
        }}>
          <div style={{
            width: 88, height: 88, borderRadius: "50%",
            background: "rgba(255,255,255,0.14)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12l5 5L20 6" />
            </svg>
          </div>
        </div>

        <p style={{ color: "white", fontSize: "2.25rem", fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.25, marginBottom: 12 }}>
          {name}様、
        </p>
        <p style={{ color: "white", fontSize: "1.75rem", fontWeight: 500, letterSpacing: "-0.02em", marginBottom: 32 }}>
          ようこそいらっしゃいました
        </p>

        {/* Info card */}
        <div style={{
          width: "100%", maxWidth: 420,
          background: "rgba(255,255,255,0.14)",
          borderRadius: 16, padding: "20px 24px",
          border: "1px solid rgba(255,255,255,0.2)",
          textAlign: "left",
        }}>
          <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 11, letterSpacing: 1.5,
            textTransform: "uppercase", fontFamily: "monospace", marginBottom: 10 }}>
            担当者へ通知しました
          </div>
          <p style={{ color: "white", fontSize: "1.125rem", fontWeight: 500, lineHeight: 1.55, margin: 0 }}>
            担当者をお呼びしています。<br />少々お待ちください。
          </p>
        </div>

        {/* Dots */}
        <div style={{ display: "flex", gap: 8, marginTop: 32 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "white", opacity: i === 1 ? 1 : 0.35,
            }} />
          ))}
        </div>
      </div>

      {/* Bottom countdown */}
      <div style={{ position: "absolute", bottom: 40, left: 0, right: 0, display: "flex", justifyContent: "center", zIndex: 1 }}>
        <p style={{ color: "rgba(255,255,255,0.4)", fontSize: 13, fontFamily: "monospace", margin: 0 }}>
          {AUTO_RETURN_MS / 1000}秒後に自動で戻ります
        </p>
      </div>
    </div>
  );
}
