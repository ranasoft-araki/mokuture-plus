"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type KioskPlaylistItem, type KioskMediaItem } from "@/lib/api";

export default function KioskWaitingPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [items, setItems] = useState<KioskPlaylistItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const itemTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.getKioskSchedule(params.tenant);
        setItems(data.playlist?.items ?? []);
      } catch {
        // Network error or tenant not found — show default waiting screen
      } finally {
        setLoaded(true);
      }
    })();
  }, [params.tenant]);

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
      onClick={() => router.push(`/${params.tenant}/kiosk/reception`)}
    >
      {currentMedia ? (
        currentMedia.mime_type === "video/mp4" ? (
          <video
            key={currentMedia.id}
            src={currentMedia.url}
            autoPlay
            muted
            playsInline
            className="w-full h-full object-cover"
            onEnded={advanceItem}
          />
        ) : (
          <img
            key={currentMedia.id}
            src={currentMedia.url}
            alt=""
            className="w-full h-full object-cover"
          />
        )
      ) : (
        <div className="w-full h-full flex flex-col items-center justify-center gap-8">
          <div className="text-[#faf8f4] text-5xl font-light tracking-widest">mokuture+</div>
          <div className="text-[#c8c0b0] text-xl">ようこそ</div>
        </div>
      )}

      <div className="absolute bottom-16 left-0 right-0 flex flex-col items-center gap-3 pointer-events-none">
        <div className="text-[#faf8f4] text-lg opacity-80 animate-pulse">画面をタッチして受付へ</div>
        <div className="w-12 h-1 rounded-full bg-[#4a7c4e] opacity-60" />
      </div>
    </div>
  );
}
