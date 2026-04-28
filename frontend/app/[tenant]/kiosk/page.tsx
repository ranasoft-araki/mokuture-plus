"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, getCachedKioskSettings, setCachedKioskSettings, type KioskPlaylistItem, type KioskMediaItem } from "@/lib/api";
import { KioskScaler } from "@/components/KioskScaler";

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function KioskIdlePage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);

  const [items, setItems] = useState<KioskPlaylistItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [brandColor, setBrandColor] = useState(
    () => getCachedKioskSettings(params.tenant)?.brand_color ?? "#4a7c4e"
  );

  const itemTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }

    api.getPublicTenantSettings(params.tenant)
      .then((s) => {
        setBrandColor(s.brand_color);
        setCachedKioskSettings(params.tenant, s);
      })
      .catch(() => {});

    const fetchSchedule = async () => {
      try {
        const data = await api.getKioskSchedule(kioskToken);
        setItems(data.playlist?.items ?? []);
      } catch (err: unknown) {
        if (err instanceof Error && err.message === "Invalid kiosk token") {
          localStorage.removeItem(KIOSK_TOKEN_KEY);
          router.replace(`/${params.tenant}/kiosk/setup`);
        }
      }
    };

    (async () => {
      await fetchSchedule();
      setLoaded(true);
    })();

    const intervalId = setInterval(fetchSchedule, 60_000);
    return () => clearInterval(intervalId);
  }, [params.tenant, router]);

  const advanceItem = useCallback(() => {
    setCurrentIndex((i) => (i + 1) % Math.max(items.length, 1));
  }, [items.length]);

  useEffect(() => {
    if (items.length === 0) return;
    const item = items[currentIndex];
    if (!item?.media) {
      itemTimerRef.current = setTimeout(advanceItem, 3000);
      return () => { if (itemTimerRef.current) clearTimeout(itemTimerRef.current); };
    }
    if (item.media.mime_type === "video/mp4") return;
    itemTimerRef.current = setTimeout(advanceItem, item.duration_sec * 1000);
    return () => {
      if (itemTimerRef.current) clearTimeout(itemTimerRef.current);
    };
  }, [currentIndex, items, advanceItem]);

  const currentMedia: KioskMediaItem | null = items[currentIndex]?.media ?? null;

  if (!loaded) {
    return (
      <div style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 18 }}>読み込み中…</div>
      </div>
    );
  }

  return (
    <KioskScaler bg="#0a0806">
      <div
        style={{
          width: 1920, height: 1080, position: "relative", overflow: "hidden",
          cursor: "pointer", userSelect: "none",
        }}
        onClick={() => router.push(`/${params.tenant}/kiosk/top`)}
      >
        {/* ── Background: real video from playlist or cinematic placeholder ── */}
        {currentMedia?.mime_type === "video/mp4" ? (
          <video
            ref={videoRef}
            key={currentMedia.id}
            src={currentMedia.url}
            autoPlay
            muted
            playsInline
            loop={items.length === 1}
            onLoadedMetadata={() => videoRef.current?.play().catch(() => {})}
            onEnded={advanceItem}
            onError={() => advanceItem()}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : currentMedia ? (
          <img
            key={currentMedia.id}
            src={currentMedia.url}
            alt=""
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          /* Cinematic placeholder matching design */
          <>
            <div style={{
              position: "absolute", inset: 0,
              background: "radial-gradient(ellipse at 35% 40%, #4a3e2c 0%, #1d1610 50%, #0a0806 100%)",
            }} />
            <svg width="1920" height="1080" style={{ position: "absolute", inset: 0, opacity: 0.18 }}>
              <defs>
                <pattern id="idleGrain" x="0" y="0" width="100%" height="36" patternUnits="userSpaceOnUse">
                  <path d="M0 18 Q 480 4 960 20 T 1920 16" stroke="#e8d8b8" strokeWidth="0.7" fill="none" />
                </pattern>
                <linearGradient id="idleVignette" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#000" stopOpacity="0.55" />
                  <stop offset="45%" stopColor="#000" stopOpacity="0" />
                  <stop offset="100%" stopColor="#000" stopOpacity="0.85" />
                </linearGradient>
              </defs>
              <rect width="1920" height="1080" fill="url(#idleGrain)" />
              <rect width="1920" height="1080" fill="url(#idleVignette)" />
            </svg>
            <div style={{
              position: "absolute", left: "8%", bottom: "14%", width: 500, height: 360,
              background: "linear-gradient(180deg, transparent, rgba(0,0,0,0.6))",
              borderRadius: "50% 50% 8% 8% / 30% 30% 8% 8%",
              filter: "blur(40px)", opacity: 0.7,
            }} />
            <div style={{
              position: "absolute", right: "12%", top: "18%", width: 600, height: 400,
              background: "radial-gradient(ellipse, #f0d9a8 0%, transparent 60%)",
              opacity: 0.25, filter: "blur(2px)",
            }} />
          </>
        )}

        {/* ── Main content overlay ── */}
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          zIndex: 1,
        }}>
          <div style={{ flex: 1 }} />

          {/* Bottom: tap CTA */}
          <div style={{
            padding: "0 80px 80px",
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "flex-end",
          }}>
            {/* tap CTA card */}
            <div style={{
              padding: "28px 36px",
              background: "rgba(255,255,255,0.96)",
              color: "#1d1a15",
              borderRadius: 20,
              display: "flex", alignItems: "center", gap: 22,
              boxShadow: "0 12px 48px rgba(0,0,0,0.4)",
            }}>
              {/* Pulse dot */}
              <div style={{ position: "relative", width: 56, height: 56, flexShrink: 0 }}>
                <div style={{
                  position: "absolute", inset: 0, borderRadius: "50%",
                  border: `2px solid ${brandColor}`, opacity: 0.4,
                  animation: "kiosk-ring-expand 2.4s ease-out 0s infinite",
                }} />
                <div style={{
                  position: "absolute", inset: 0, borderRadius: "50%",
                  border: `2px solid ${brandColor}`, opacity: 0.3,
                  animation: "kiosk-ring-expand 2.4s ease-out 0.8s infinite",
                }} />
                <div style={{
                  position: "absolute", inset: 8, borderRadius: "50%",
                  background: brandColor,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#ffffff" }} />
                </div>
              </div>
              <div>
                <div style={{
                  fontSize: 11, letterSpacing: 2, color: "#a8a198",
                  textTransform: "uppercase", marginBottom: 4,
                  fontFamily: "Inter, system-ui, sans-serif",
                }}>TAP TO BEGIN</div>
                <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: -0.5 }}>
                  画面にタッチして受付
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </KioskScaler>
  );
}
