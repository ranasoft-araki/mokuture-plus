"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

const AUTO_RETURN_SEC = 10;

export default function CompletePage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "お客様";
  const [count, setCount] = useState(AUTO_RETURN_SEC);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
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
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [params.tenant, router]);

  return (
    <div
      className="w-screen h-screen flex flex-col items-center justify-center select-none overflow-hidden"
      style={{
        background: "#4a7c4e",
        position: "relative",
        animation: "kiosk-screen-in 0.4s cubic-bezier(0.2,0.7,0.3,1)",
      }}
      onClick={() => router.push(`/${params.tenant}/kiosk`)}
    >
      {/* Radial glow */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: "radial-gradient(circle at 50% 42%, rgba(255,255,255,0.08) 0%, transparent 65%)",
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

      {/* Center content */}
      <div
        className="flex flex-col items-center"
        style={{ zIndex: 1, padding: "0 52px", textAlign: "center", width: "100%", maxWidth: 520 }}
      >
        {/* Checkmark rings */}
        <div style={{
          marginBottom: 36,
          animation: "kiosk-scale-in 0.5s cubic-bezier(0.2,0.9,0.3,1.1)",
        }}>
          <div style={{
            width: 120, height: 120, borderRadius: "50%",
            background: "rgba(255,255,255,0.18)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{
              width: 88, height: 88, borderRadius: "50%",
              background: "rgba(255,255,255,0.14)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="42" height="42" viewBox="0 0 24 24" fill="none"
                stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path
                  d="M5 12l5 5L20 6"
                  strokeDasharray="60"
                  strokeDashoffset="60"
                  style={{ animation: "kiosk-check-draw 0.6s 0.35s cubic-bezier(0.2,0.9,0.3,1) forwards" }}
                />
              </svg>
            </div>
          </div>
        </div>

        <p style={{
          color: "white", fontSize: "2.25rem", fontWeight: 600,
          letterSpacing: "-0.03em", lineHeight: 1.25, margin: "0 0 10px",
        }}>
          {name}様、
        </p>
        <p style={{
          color: "white", fontSize: "1.6rem", fontWeight: 500,
          letterSpacing: "-0.02em", margin: "0 0 32px",
        }}>
          ようこそいらっしゃいました
        </p>

        {/* Info card */}
        <div style={{
          width: "100%",
          background: "rgba(255,255,255,0.14)",
          borderRadius: 16, padding: "20px 24px",
          border: "1px solid rgba(255,255,255,0.2)",
          textAlign: "left",
        }}>
          <div style={{
            color: "rgba(255,255,255,0.6)", fontSize: 11,
            letterSpacing: 1.5, textTransform: "uppercase",
            fontFamily: "monospace", marginBottom: 10,
          }}>
            担当者へ通知しました
          </div>
          <p style={{
            color: "white", fontSize: "1.1rem", fontWeight: 500,
            lineHeight: 1.6, margin: "0 0 14px",
          }}>
            担当者をお呼びしています。<br />少々お待ちください。
          </p>
          {/* NEXT block */}
          <div style={{
            padding: "12px 14px",
            background: "rgba(255,255,255,0.12)",
            borderRadius: 10,
            borderLeft: "3px solid rgba(255,255,255,0.5)",
          }}>
            <div style={{
              color: "rgba(255,255,255,0.5)", fontSize: 10,
              letterSpacing: 1, textTransform: "uppercase",
              fontFamily: "monospace", marginBottom: 5,
            }}>
              NEXT
            </div>
            <div style={{ color: "white", fontSize: 15, fontWeight: 500 }}>
              2階 商談ルーム A にご案内します
            </div>
          </div>
        </div>

        {/* Animated dots */}
        <div style={{ display: "flex", gap: 8, marginTop: 28 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "white",
              animation: `kiosk-dot-pulse 1.6s ${i * 0.3}s ease-in-out infinite`,
            }} />
          ))}
        </div>
      </div>

      {/* Countdown */}
      <div style={{
        position: "absolute", bottom: 40, left: 0, right: 0,
        display: "flex", justifyContent: "center", zIndex: 1,
      }}>
        <p style={{
          color: "rgba(255,255,255,0.4)", fontSize: 13,
          fontFamily: "monospace", margin: 0,
        }}>
          {count}秒後に自動で戻ります
        </p>
      </div>
    </div>
  );
}
