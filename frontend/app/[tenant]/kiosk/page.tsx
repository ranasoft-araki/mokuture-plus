"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type Playlist, type PlaylistItem, type MediaItem } from "@/lib/api";

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";
const IDLE_TIMEOUT_MS = 60_000; // return to waiting screen after 60s of inactivity

export default function KioskWaitingPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [playlist, setPlaylist] = useState<Playlist | null>(null);
  const [mediaMap, setMediaMap] = useState<Record<string, MediaItem>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const itemTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch current scheduled playlist
  useEffect(() => {
    const token = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!token) {
      // Redirect to login if no kiosk token; in Phase 1 use device-pairing flow
      router.push(`/${params.tenant}/admin`);
      return;
    }
    (async () => {
      try {
        const { playlist_id } = await api.currentSchedule(token);
        if (!playlist_id) { setLoaded(true); return; }
        const playlists = await api.listPlaylists(token);
        const pl = playlists.find((p) => p.id === playlist_id) ?? null;
        setPlaylist(pl);
        if (pl && pl.items.length > 0) {
          const media = await api.listMedia(token);
          const map: Record<string, MediaItem> = {};
          media.forEach((m) => (map[m.id] = m));
          setMediaMap(map);
        }
      } catch {
        // No token or API error — show blank waiting screen
      } finally {
        setLoaded(true);
      }
    })();
  }, [params.tenant, router]);

  // Advance to next media item
  const advanceItem = useCallback(() => {
    if (!playlist) return;
    setCurrentIndex((i) => (i + 1) % playlist.items.length);
  }, [playlist]);

  // Set per-item display timer
  useEffect(() => {
    if (!playlist || playlist.items.length === 0) return;
    const item = playlist.items[currentIndex];
    if (!item) return;
    const mediaItem = mediaMap[item.media_id];
    // Videos auto-advance on "ended" event; images use duration_sec
    if (!mediaItem || mediaItem.mime_type === "video/mp4") return;
    itemTimerRef.current = setTimeout(advanceItem, item.duration_sec * 1000);
    return () => { if (itemTimerRef.current) clearTimeout(itemTimerRef.current); };
  }, [currentIndex, playlist, mediaMap, advanceItem]);

  // Navigate to reception on any touch/click
  const handleTouch = () => {
    router.push(`/${params.tenant}/kiosk/reception`);
  };

  if (!loaded) {
    return <div className="w-screen h-screen bg-[#1d1a15] flex items-center justify-center">
      <div className="text-[#faf8f4] text-2xl opacity-50">読み込み中…</div>
    </div>;
  }

  const currentItem = playlist?.items[currentIndex];
  const currentMedia = currentItem ? mediaMap[currentItem.media_id] : null;

  return (
    <div
      className="w-screen h-screen bg-[#1d1a15] relative overflow-hidden cursor-pointer select-none"
      onClick={handleTouch}
    >
      {/* Media layer */}
      {currentMedia ? (
        currentMedia.mime_type === "video/mp4" ? (
          <video
            ref={videoRef}
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
        /* Default waiting screen when no playlist is configured */
        <div className="w-full h-full flex flex-col items-center justify-center gap-8">
          <div className="text-[#faf8f4] text-5xl font-light tracking-widest">mokuture+</div>
          <div className="text-[#c8c0b0] text-xl">ようこそ</div>
        </div>
      )}

      {/* Touch prompt overlay */}
      <div className="absolute bottom-16 left-0 right-0 flex flex-col items-center gap-3 pointer-events-none">
        <div className="text-[#faf8f4] text-lg opacity-80 animate-pulse">画面をタッチして受付へ</div>
        <div className="w-12 h-1 rounded-full bg-[#4a7c4e] opacity-60" />
      </div>
    </div>
  );
}
