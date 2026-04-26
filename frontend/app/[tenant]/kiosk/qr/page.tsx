"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api } from "@/lib/api";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

// BarcodeDetector is a browser API — declare types manually
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

    // Check BarcodeDetector support
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

    // Try to parse URLSearchParams from the QR value
    let name = "";
    let company = "";
    let purpose = "";
    try {
      const url = new URL(raw);
      name = url.searchParams.get("name") ?? "";
      company = url.searchParams.get("company") ?? "";
      purpose = url.searchParams.get("purpose") ?? "";
    } catch {
      // Plain text fallback: treat entire value as visitor name
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
      router.push(`/${params.tenant}/kiosk/complete?name=${encodeURIComponent(name)}`);
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
      className="w-screen h-screen flex flex-col select-none"
      style={{ background: "#1d1a15" }}
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
      <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>

        {supported === false ? (
          /* BarcodeDetector not supported */
          <div style={{ padding: "0 40px", textAlign: "center" }}>
            <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 16, lineHeight: 1.6, marginBottom: 28 }}>
              このブラウザはQR受付に対応していません。<br />
              Chromium系ブラウザをご利用ください。
            </div>
            <button
              onClick={() => router.push(`/${params.tenant}/kiosk/reception`)}
              style={{
                background: "#4a7c4e", color: "white", border: "none",
                borderRadius: 14, height: 60, padding: "0 32px", fontSize: 17,
                fontWeight: 600, cursor: "pointer",
              }}
            >
              入力して受付へ
            </button>
          </div>
        ) : submitting ? (
          <div style={{ color: "white", fontSize: 20, opacity: 0.8 }}>受付処理中…</div>
        ) : (
          <>
            {/* Camera viewfinder */}
            <div style={{
              position: "relative", width: "min(80vw, 400px)", aspectRatio: "1",
              borderRadius: 24, overflow: "hidden",
              border: "2px solid rgba(74,124,78,0.7)",
              boxShadow: "0 0 0 4px rgba(74,124,78,0.2)",
            }}>
              <video
                ref={videoRef}
                muted
                playsInline
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
              {/* Corner marks */}
              {[
                { top: 0, left: 0 },
                { top: 0, right: 0 },
                { bottom: 0, left: 0 },
                { bottom: 0, right: 0 },
              ].map((pos, i) => (
                <div key={i} style={{
                  position: "absolute", width: 28, height: 28, ...pos,
                  borderTop: i < 2 ? `3px solid #4a7c4e` : "none",
                  borderBottom: i >= 2 ? `3px solid #4a7c4e` : "none",
                  borderLeft: i % 2 === 0 ? `3px solid #4a7c4e` : "none",
                  borderRight: i % 2 === 1 ? `3px solid #4a7c4e` : "none",
                  borderRadius: i === 0 ? "8px 0 0 0" : i === 1 ? "0 8px 0 0" : i === 2 ? "0 0 0 8px" : "0 0 8px 0",
                }} />
              ))}
              {scanning && (
                <div style={{
                  position: "absolute", top: "50%", left: 0, right: 0, height: 2,
                  background: "rgba(74,124,78,0.8)",
                  animation: "scan 2s linear infinite",
                }} />
              )}
            </div>

            <p style={{ color: "rgba(255,255,255,0.7)", fontSize: 15, marginTop: 28, textAlign: "center" }}>
              QRコードをカメラにかざしてください
            </p>

            {error && (
              <div style={{
                marginTop: 20, padding: "12px 20px", background: "#f6e0dc",
                borderRadius: 12, color: "#a84238", fontSize: 14,
                maxWidth: 380, textAlign: "center",
              }}>
                {error}
              </div>
            )}

            <button
              onClick={() => router.push(`/${params.tenant}/kiosk/reception`)}
              style={{
                marginTop: 32, background: "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.2)", color: "rgba(255,255,255,0.7)",
                borderRadius: 12, height: 50, padding: "0 24px", fontSize: 15, cursor: "pointer",
              }}
            >
              入力して受付に切り替え
            </button>
          </>
        )}
      </div>

      <style>{`
        @keyframes scan {
          0% { top: 10%; }
          50% { top: 90%; }
          100% { top: 10%; }
        }
      `}</style>
    </div>
  );
}
