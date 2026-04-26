"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type KioskPlaylistItem, type KioskMediaItem } from "@/lib/api";

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function KioskWaitingPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [items, setItems] = useState<KioskPlaylistItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const itemTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }
    (async () => {
      try {
        const data = await api.getKioskSchedule(kioskToken);
        setItems(data.playlist?.items ?? []);
      } catch (err: unknown) {
        if (err instanceof Error && err.message === "Invalid kiosk token") {
          localStorage.removeItem(KIOSK_TOKEN_KEY);
          router.replace(`/${params.tenant}/kiosk/setup`);
          return;
        }
      } finally {
        setLoaded(true);
      }
    })();
  }, [params.tenant, router]);

  const advanceItem = useCallback(() => {
    setCurrentIndex((i) => (i + 1) % Math.max(items.length, 1));
  }, [items.length]);

  useEffect(() => {
    if (items.length === 0) return;
    const item = items[currentIndex];
    if (!item?.media || item.media.mime_type === "video/mp4") return;
    itemTimerRef.current = setTimeout(advanceItem, item.duration_sec * 1000);
    return () => { if (itemTimerRef.current) clearTimeout(itemTimerRef.current); };
  }, [currentIndex, items, advanceItem]);

  if (!loaded) {
    return (
      <div className="w-screen h-screen bg-[#1d1a15] flex items-center justify-center">
        <div className="text-[#faf8f4] text-2xl opacity-50">読み込み中…</div>
      </div>
    );
  }

  const currentMedia: KioskMediaItem | null = items[currentIndex]?.media ?? null;

  return (
    <div
      className="w-screen h-screen bg-[#1d1a15] relative overflow-hidden cursor-pointer select-none"
      style={{
        backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.025) 0 10px, transparent 10px 20px)",
      }}
      onClick={() => router.push(`/${params.tenant}/kiosk/top`)}
    >
      {/* Media layer */}
      {currentMedia ? (
        currentMedia.mime_type === "video/mp4" ? (
          <video
            key={currentMedia.id}
            src={currentMedia.url}
            autoPlay
            muted
            playsInline
            className="absolute inset-0 w-full h-full object-cover"
            onEnded={advanceItem}
          />
        ) : (
          <img
            key={currentMedia.id}
            src={currentMedia.url}
            alt=""
            className="absolute inset-0 w-full h-full object-cover"
          />
        )
      ) : (
        /* Default brand screen */
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0">
          {/* Concentric rings */}
          <div style={{
            width: 120, height: 120, borderRadius: "50%",
            border: "1.5px solid rgba(255,255,255,0.12)",
            display: "flex", alignItems: "center", justifyContent: "center",
            marginBottom: 36,
          }}>
            <div style={{
              width: 80, height: 80, borderRadius: "50%",
              border: "1.5px solid rgba(255,255,255,0.2)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <div style={{
                width: 44, height: 44, borderRadius: "50%", background: "#4a7c4e",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="9" r="5" /><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5" /><path d="M12 4v10" />
                </svg>
              </div>
            </div>
          </div>
          <p className="text-[#faf8f4] text-4xl font-medium tracking-tight" style={{ marginBottom: 12 }}>ようこそ</p>
          <p className="text-[#a8a198] text-lg" style={{ letterSpacing: "0.03em" }}>磯野木工所 本社</p>
        </div>
      )}

      {/* Top brand bar */}
      <div className="absolute top-0 left-0 right-0 flex items-center gap-3 pointer-events-none"
        style={{ padding: "32px 32px 0" }}>
        <div style={{
          width: 36, height: 36, borderRadius: 9, background: "#4a7c4e",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="9" r="5" /><path d="M4 19c2-3 5-4.5 8-4.5s6 1.5 8 4.5" /><path d="M12 4v10" />
          </svg>
        </div>
        <div>
          <div className="text-[#faf8f4] font-semibold" style={{ fontSize: 16, letterSpacing: "-0.02em" }}>
            mokuture<span style={{ color: "#4a7c4e" }}>+</span>
          </div>
          <div style={{ color: "rgba(255,255,255,0.35)", fontSize: 10, letterSpacing: "0.12em", fontFamily: "monospace" }}>
            KIOSK
          </div>
        </div>
      </div>

      {/* Bottom CTA */}
      <div className="absolute bottom-0 left-0 right-0 flex flex-col items-center pointer-events-none"
        style={{ paddingBottom: 56 }}>
        {/* Touch pulse indicator */}
        <div style={{ position: "relative", marginBottom: 22 }}>
          <div style={{
            width: 64, height: 64, borderRadius: "50%",
            background: "rgba(74,124,78,0.15)",
            border: "1.5px solid rgba(74,124,78,0.35)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: "50%",
              background: "rgba(74,124,78,0.25)",
              border: "1.5px solid rgba(74,124,78,0.6)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <div style={{ width: 24, height: 24, borderRadius: "50%", background: "#4a7c4e" }} />
            </div>
          </div>
        </div>
        <p className="text-[#faf8f4]" style={{ fontSize: 17, opacity: 0.85, letterSpacing: "0.02em" }}>
          画面をタッチして受付へ
        </p>
        <div style={{ marginTop: 18, width: 48, height: 3, background: "#4a7c4e", borderRadius: 2, opacity: 0.7 }} />
      </div>
    </div>
  );
}
