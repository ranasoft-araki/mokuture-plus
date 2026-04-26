"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api } from "@/lib/api";
import { KioskScaler } from "@/components/KioskScaler";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

declare class BarcodeDetector {
  constructor(options: { formats: string[] });
  detect(image: ImageBitmapSource): Promise<{ rawValue: string }[]>;
  static getSupportedFormats(): Promise<string[]>;
}

export default function KioskQRPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scanningRef = useRef(false);

  const [supported, setSupported] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState("");

  const resetIdle = useCallback(() => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => router.push(`/${params.tenant}/kiosk`), IDLE_TIMEOUT_MS);
  }, [params.tenant, router]);

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

    if (typeof BarcodeDetector === "undefined") {
      setSupported(false);
      return () => { if (idleRef.current) clearTimeout(idleRef.current); clearInterval(id); };
    }
    setSupported(true);
    startCamera();
    return () => {
      if (idleRef.current) clearTimeout(idleRef.current);
      clearInterval(id);
      stopCamera();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        setScanning(true);
        scanningRef.current = true;
        scanLoop();
      }
    } catch {
      setError("カメラを起動できませんでした。カメラのアクセス許可を確認してください。");
    }
  };

  const stopCamera = () => {
    scanningRef.current = false;
    streamRef.current?.getTracks().forEach((t) => t.stop());
  };

  const scanLoop = useCallback(async () => {
    if (!scanningRef.current || !videoRef.current) return;
    try {
      const detector = new BarcodeDetector({ formats: ["qr_code"] });
      const barcodes = await detector.detect(videoRef.current);
      if (barcodes.length > 0 && barcodes[0].rawValue) {
        scanningRef.current = false;
        setScanning(false);
        await handleQRData(barcodes[0].rawValue);
        return;
      }
    } catch { /* keep scanning */ }
    if (scanningRef.current) requestAnimationFrame(scanLoop);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleQRData = async (raw: string) => {
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) { router.replace(`/${params.tenant}/kiosk/setup`); return; }
    let name = "", company = "", purpose = "";
    try {
      const url = new URL(raw);
      name = url.searchParams.get("name") ?? "";
      company = url.searchParams.get("company") ?? "";
      purpose = url.searchParams.get("purpose") ?? "";
    } catch { name = raw.trim(); }
    if (!name) {
      setError("QRコードから来訪者情報を読み取れませんでした。フォームで受付をご利用ください。");
      scanningRef.current = true; setScanning(true); scanLoop();
      return;
    }
    setSubmitting(true);
    try {
      await api.createKioskReception(kioskToken, { visitor_name: name, company, purpose, method: "qr" });
      stopCamera();
      router.push(`/${params.tenant}/kiosk/calling?name=${encodeURIComponent(name)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付処理に失敗しました");
      setSubmitting(false);
      scanningRef.current = true; setScanning(true); scanLoop();
    }
  };

  const back = () => { stopCamera(); router.push(`/${params.tenant}/kiosk/top`); };
  const toForm = () => { stopCamera(); router.push(`/${params.tenant}/kiosk/reception`); };

  return (
    <KioskScaler bg="#faf8f4">
      <div
        style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}
        onClick={resetIdle}
      >
        {/* Brand */}
        <div style={{ padding: "32px 80px 0", display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
          <div style={{ width: 48, height: 48, borderRadius: 4, border: "1.5px solid #1d1a15", color: "#1d1a15", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 500, letterSpacing: -1, fontFamily: "Inter, system-ui, sans-serif" }}>磯</div>
          <div>
            <div style={{ fontSize: 11, letterSpacing: 3.2, textTransform: "uppercase" as const, color: "#a8a198", marginBottom: 4, fontFamily: "Inter, system-ui, sans-serif" }}>EST. 1948</div>
            <div style={{ fontSize: 20, fontWeight: 500, letterSpacing: -0.2, color: "#1d1a15" }}>磯野木工所</div>
          </div>
        </div>

        {/* Body: left=camera, right=copy */}
        <div style={{
          flex: 1, padding: "24px 80px 0",
          display: "grid", gridTemplateColumns: "1fr 1fr",
          gap: 56, alignItems: "center", minHeight: 0,
        }}>
          {/* Left: QR camera */}
          <div style={{
            background: "#1d1a15", borderRadius: 28,
            position: "relative", overflow: "hidden",
            display: "flex", alignItems: "center", justifyContent: "center",
            height: "100%", maxHeight: 760,
          }}>
            {submitting ? (
              <div style={{ textAlign: "center", color: "#ffffff" }}>
                <div style={{ width: 60, height: 60, borderRadius: "50%", border: "3px solid rgba(255,255,255,0.2)", borderTopColor: "#4a7c4e", animation: "kiosk-spin 0.8s linear infinite", margin: "0 auto 20px" }} />
                <div style={{ fontSize: 18, opacity: 0.7 }}>受付処理中…</div>
              </div>
            ) : supported === false ? (
              <div style={{ textAlign: "center", color: "#ffffff", padding: 40 }}>
                <div style={{ width: 80, height: 80, borderRadius: "50%", background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 24px" }}>
                  <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" />
                  </svg>
                </div>
                <div style={{ fontSize: 18, opacity: 0.6, lineHeight: 1.6 }}>QRスキャン非対応のブラウザです<br/>Chromiumをご利用ください</div>
              </div>
            ) : (
              <>
                {/* Camera viewfinder area */}
                <div style={{ position: "absolute", inset: 60, border: "3px dashed rgba(255,255,255,0.2)", borderRadius: 20, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(255,255,255,0.02)" }}>
                  {/* Corner marks */}
                  {[{ top: 0, left: 0, rot: 0 }, { top: 0, right: 0, rot: 90 }, { bottom: 0, right: 0, rot: 180 }, { bottom: 0, left: 0, rot: 270 }].map((c, i) => (
                    <div key={i} style={{
                      position: "absolute",
                      ...(c.top !== undefined ? { top: -3 } : { bottom: -3 }),
                      ...(c.left !== undefined ? { left: -3 } : { right: -3 }),
                      width: 56, height: 56,
                      transform: `rotate(${c.rot}deg)`,
                      borderTop: "5px solid #4a7c4e", borderLeft: "5px solid #4a7c4e",
                      borderRadius: "12px 0 0 0",
                    }} />
                  ))}
                  {/* Scan line */}
                  {scanning && (
                    <div style={{ position: "absolute", left: 0, right: 0, height: 3, background: "#4a7c4e", boxShadow: "0 0 24px #4a7c4e", animation: "kiosk-scan 2s linear infinite" }} />
                  )}
                  {/* QR icon placeholder */}
                  <svg width="120" height="120" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" />
                    <path d="M14 14h3v3h-3zM20 14h1M14 20h1M17 18v3M20 17v4" />
                  </svg>
                </div>

                {/* Actual camera feed */}
                <video
                  ref={videoRef}
                  muted
                  playsInline
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0.85 }}
                />

                {/* Status badge */}
                <div style={{ position: "absolute", bottom: 24, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(0,0,0,0.5)", color: "#ffffff", padding: "8px 20px", borderRadius: 999, fontSize: 15 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#4a7c4e", animation: "kiosk-dot-pulse 1.4s ease-in-out infinite" }} />
                    {scanning ? "読み取り中…" : "カメラ準備中…"}
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Right: instructions */}
          <div style={{ display: "flex", flexDirection: "column" }}>
            <button
              onClick={back}
              style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 999, fontSize: 14, color: "#6b6559", marginBottom: 28, cursor: "pointer", fontFamily: "inherit" }}
            >
              ← 戻る
            </button>

            <div style={{ fontSize: 14, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, marginBottom: 12, fontFamily: "Inter, system-ui, sans-serif" }}>STEP 1 / 1</div>
            <div style={{ fontSize: 64, fontWeight: 600, color: "#1d1a15", letterSpacing: -2, lineHeight: 1.15, marginBottom: 18 }}>
              QR コードを<br />かざしてください
            </div>
            <div style={{ fontSize: 20, color: "#6b6559", lineHeight: 1.6, marginBottom: 36 }}>
              メールでお送りした招待コードを<br />左の読み取り口へ
            </div>

            {error && (
              <div style={{ padding: "16px 20px", background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.3)", borderRadius: 14, color: "#a84238", fontSize: 16, lineHeight: 1.6, marginBottom: 24 }}>
                {error}
              </div>
            )}

            <div style={{ padding: "20px 24px", background: "#f4f1ea", borderRadius: 14, fontSize: 16, color: "#6b6559", borderLeft: "4px solid #4a7c4e", lineHeight: 1.6, marginBottom: 32 }}>
              <b style={{ color: "#2d2a24" }}>うまく読み取れない場合</b><br />
              画面の明るさをお確かめください。お手元のメール本文を直接かざしてもOKです。
            </div>

            <div style={{ display: "flex", gap: 14 }}>
              <button
                onClick={toForm}
                style={{ flex: 1, padding: "20px", background: "#fffefb", border: "2px solid #d8d3c7", borderRadius: 14, fontSize: 17, fontWeight: 500, color: "#2d2a24", cursor: "pointer", fontFamily: "inherit" }}
              >
                QR を持っていない
              </button>
              <button
                onClick={toForm}
                style={{ flex: 1, padding: "20px", background: "#1d1a15", border: "2px solid #1d1a15", borderRadius: 14, fontSize: 17, fontWeight: 600, color: "#ffffff", cursor: "pointer", fontFamily: "inherit" }}
              >
                フォームで受付する →
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: "16px 80px 28px", display: "flex", alignItems: "center", color: "#a8a198", fontSize: 13, flexShrink: 0 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14 }}>{now}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: "JetBrains Mono, monospace" }}>kiosk-hq-1f-01</span>
        </div>
      </div>

      <style>{`@keyframes kiosk-spin { to { transform: rotate(360deg); } }`}</style>
    </KioskScaler>
  );
}
