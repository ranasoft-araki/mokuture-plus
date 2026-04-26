"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api } from "@/lib/api";

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

    if (typeof BarcodeDetector === "undefined") {
      setSupported(false);
      return;
    }

    setSupported(true);
    startCamera();

    return () => {
      if (idleRef.current) clearTimeout(idleRef.current);
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
    } catch {
      // keep scanning
    }
    if (scanningRef.current) requestAnimationFrame(scanLoop);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleQRData = async (raw: string) => {
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) { router.replace(`/${params.tenant}/kiosk/setup`); return; }

    let name = "";
    let company = "";
    let purpose = "";
    try {
      const url = new URL(raw);
      name = url.searchParams.get("name") ?? "";
      company = url.searchParams.get("company") ?? "";
      purpose = url.searchParams.get("purpose") ?? "";
    } catch {
      name = raw.trim();
    }

    if (!name) {
      setError("QRコードから来訪者情報を読み取れませんでした。入力して受付をご利用ください。");
      scanningRef.current = true;
      setScanning(true);
      scanLoop();
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
      scanningRef.current = true;
      setScanning(true);
      scanLoop();
    }
  };

  const back = () => { stopCamera(); router.push(`/${params.tenant}/kiosk/top`); };

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
        height: 88, display: "flex", alignItems: "center", gap: 16, flexShrink: 0, zIndex: 10,
      }}>
        <button
          onClick={back}
          style={{
            width: 44, height: 44, borderRadius: 12,
            background: "rgba(255,255,255,0.15)", border: "none",
            display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 5l-7 7 7 7" />
          </svg>
        </button>
        <h1 style={{ color: "white", fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          QRコードで受付
        </h1>
      </div>

      {/* Content */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "40px 32px",
        gap: 28,
      }}>
        {supported === false ? (
          /* BarcodeDetector not supported */
          <div style={{ textAlign: "center", maxWidth: 400 }}>
            <div style={{
              width: 80, height: 80, borderRadius: "50%",
              background: "#eaf0e8", color: "#4a7c4e",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 24px",
            }}>
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>
              </svg>
            </div>
            <div style={{ color: "#6b6559", fontSize: 16, lineHeight: 1.6, marginBottom: 28 }}>
              このブラウザはQR受付に対応していません。<br />
              Chromium系ブラウザをご利用ください。
            </div>
            <button
              onClick={() => router.push(`/${params.tenant}/kiosk/reception`)}
              style={{
                background: "#4a7c4e", color: "white", border: "none",
                borderRadius: 14, height: 60, padding: "0 32px", fontSize: 17,
                fontWeight: 600, cursor: "pointer",
                boxShadow: "0 4px 16px rgba(74,124,78,0.3)",
              }}
            >
              入力して受付へ
            </button>
          </div>
        ) : submitting ? (
          <div style={{ textAlign: "center" }}>
            <div style={{
              width: 60, height: 60, borderRadius: "50%",
              border: "3px solid #eaf0e8", borderTopColor: "#4a7c4e",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 20px",
            }} />
            <div style={{ color: "#6b6559", fontSize: 17 }}>受付処理中…</div>
          </div>
        ) : (
          <>
            <p style={{ color: "#6b6559", fontSize: 16, margin: 0, textAlign: "center" }}>
              QRコードをカメラにかざしてください
            </p>

            {/* Camera viewfinder */}
            <div style={{
              position: "relative",
              width: "min(72vw, 380px)", aspectRatio: "1",
              borderRadius: 20, overflow: "hidden",
            }}>
              {/* Camera feed */}
              <video
                ref={videoRef}
                muted
                playsInline
                style={{ width: "100%", height: "100%", objectFit: "cover", background: "#e8e4dd" }}
              />

              {/* Corner marks */}
              {[
                { top: 0, left: 0, borderTop: "3px solid #4a7c4e", borderLeft: "3px solid #4a7c4e", borderTopLeftRadius: 8 },
                { top: 0, right: 0, borderTop: "3px solid #4a7c4e", borderRight: "3px solid #4a7c4e", borderTopRightRadius: 8 },
                { bottom: 0, left: 0, borderBottom: "3px solid #4a7c4e", borderLeft: "3px solid #4a7c4e", borderBottomLeftRadius: 8 },
                { bottom: 0, right: 0, borderBottom: "3px solid #4a7c4e", borderRight: "3px solid #4a7c4e", borderBottomRightRadius: 8 },
              ].map((s, i) => (
                <div key={i} style={{ position: "absolute", width: 32, height: 32, ...s }} />
              ))}

              {/* Scan line */}
              {scanning && (
                <div style={{
                  position: "absolute", left: 8, right: 8, height: 2,
                  background: "linear-gradient(90deg, transparent, #4a7c4e, transparent)",
                  boxShadow: "0 0 8px rgba(74,124,78,0.6)",
                  animation: "kiosk-scan 2s linear infinite",
                }} />
              )}
            </div>

            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{
                  width: 8, height: 8, borderRadius: "50%", background: "#4a7c4e",
                  animation: `kiosk-dot-bounce 1.4s ${i * 0.18}s ease-in-out infinite`,
                }} />
              ))}
            </div>

            {error && (
              <div style={{
                padding: "14px 20px", background: "#f6e0dc",
                border: "1px solid rgba(168,66,56,0.3)", borderRadius: 12,
                color: "#a84238", fontSize: 14, maxWidth: 400, textAlign: "center",
                lineHeight: 1.5,
              }}>
                {error}
              </div>
            )}

            <button
              onClick={() => { stopCamera(); router.push(`/${params.tenant}/kiosk/reception`); }}
              style={{
                background: "transparent",
                border: "1.5px solid #d8d3c7", color: "#6b6559",
                borderRadius: 12, height: 52, padding: "0 28px",
                fontSize: 15, cursor: "pointer",
                transition: "border-color 0.15s, color 0.15s",
              }}
            >
              入力して受付に切り替え
            </button>
          </>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
