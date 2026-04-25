"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type MediaItem } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";

type FilterType = "all" | "video" | "image";

export default function AdminMediaPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [media, setMedia] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const loadMedia = useCallback(async (token: string) => {
    setLoading(true);
    try {
      setMedia(await api.listMedia(token));
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadMedia(token);
  }, [loadMedia, router]);

  const stats = useMemo(() => {
    const images = media.filter((m) => m.mime_type.startsWith("image/")).length;
    const videos = media.filter((m) => m.mime_type.startsWith("video/")).length;
    const totalBytes = media.reduce((s, m) => s + m.size_bytes, 0);
    return { images, videos, totalBytes };
  }, [media]);

  const filtered = useMemo(() => {
    let list = media;
    if (filter === "video") list = list.filter((m) => m.mime_type.startsWith("video/"));
    if (filter === "image") list = list.filter((m) => m.mime_type.startsWith("image/"));
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((m) => m.filename.toLowerCase().includes(q));
    }
    return list;
  }, [media, filter, search]);

  async function uploadFile(file: File) {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setUploading(true);
    setError("");
    setSuccess("");
    try {
      const created = await api.uploadMedia(token, file);
      setMedia((cur) => [created, ...cur]);
      setSuccess(`「${file.name}」をアップロードしました`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "アップロードに失敗しました");
    } finally {
      setUploading(false);
    }
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) void uploadFile(f);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) void uploadFile(f);
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`「${name}」を削除しますか？`)) return;
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deleteMedia(token, id);
      setMedia((cur) => cur.filter((m) => m.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  const filterCounts: Record<FilterType, number> = {
    all:   media.length,
    video: stats.videos,
    image: stats.images,
  };
  const filterLabels: Record<FilterType, string> = { all: "すべて", video: "動画", image: "静止画" };

  return (
    <AdminShell
      active="media"
      title="メディアライブラリ"
      breadcrumb="ホーム / コンテンツ管理"
      subtitle={`動画・静止画を管理 · 合計 ${media.length} 件 / 使用容量 ${formatBytes(stats.totalBytes)}`}
      actions={
        <>
          <MkBtn variant="primary" onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? "アップロード中…" : "↑ アップロード"}
          </MkBtn>
          <input ref={inputRef} type="file" accept="image/*,video/*" className="hidden" onChange={handleFilePick} />
        </>
      }
    >
      {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>{error}</div>}
      {success && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#eaf0e8", border: "1px solid #4a7c4e", color: "#3a6240", fontSize: 13 }}>{success}</div>}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `1.5px dashed ${isDragging ? "#4a7c4e" : "#d8d3c7"}`,
          borderRadius: 10,
          background: isDragging ? "#eaf0e8" : "#fffefb",
          padding: 18,
          marginBottom: 22,
          display: "flex",
          alignItems: "center",
          gap: 16,
          cursor: "pointer",
          transition: "all 0.15s",
        }}
      >
        <div
          style={{
            width: 44, height: 44, borderRadius: 7, flexShrink: 0,
            background: "#eaf0e8", color: "#3a6240",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <div style={{ flex: 1, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#2d2a24" }}>
            ドラッグ&amp;ドロップ、またはクリックしてアップロード
          </div>
          <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 3 }}>
            MP4 (H.264) · JPEG · PNG · SVG — 1ファイルあたり最大 500 MB
          </div>
        </div>
        <MkBtn variant="default" size="sm" onClick={() => { inputRef.current?.click(); }}>
          ファイルを選択
        </MkBtn>
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, width: 280 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ファイル名で検索"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: '"Noto Sans JP", system-ui, sans-serif', height: "100%" }}
          />
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["all", "video", "image"] as FilterType[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: "6px 12px", fontSize: 11.5,
                background: filter === f ? "#1d1a15" : "#fffefb",
                color: filter === f ? "#fffefb" : "#6b6559",
                border: `1px solid ${filter === f ? "#1d1a15" : "#d8d3c7"}`,
                borderRadius: 999, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 6,
                fontFamily: '"Noto Sans JP", system-ui, sans-serif',
              }}
            >
              {filterLabels[f]}
              <span style={{ fontSize: 10, opacity: 0.6, fontFamily: "monospace" }}>{filterCounts[f]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {loading ? (
        <div style={{ textAlign: "center", color: "#a8a198", padding: "48px 0" }}>読み込み中…</div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: "center", color: "#a8a198", padding: "48px 0" }}>
          {media.length === 0 ? "まだメディアが登録されていません" : "検索結果がありません"}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {filtered.map((item) => (
            <MediaTile key={item.id} item={item} onDelete={() => handleDelete(item.id, item.filename)} />
          ))}
        </div>
      )}
    </AdminShell>
  );
}

function MediaTile({ item, onDelete }: { item: MediaItem; onDelete: () => void }) {
  const isVideo = item.mime_type.startsWith("video/");
  const ext = item.mime_type.split("/")[1]?.toUpperCase() ?? "FILE";

  return (
    <div
      style={{
        background: "#fffefb", border: "1px solid #efece5", borderRadius: 10,
        overflow: "hidden", cursor: "pointer",
        boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
      }}
    >
      {/* Thumbnail */}
      <div
        style={{
          aspectRatio: "16/10",
          background: isVideo ? "#1d1a15" : "#f4f1ea",
          position: "relative",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: isVideo ? "#fffefb" : "#a8a198",
          borderBottom: "1px solid #efece5",
          overflow: "hidden",
        }}
      >
        {isVideo ? (
          <>
            <video src={item.url} muted playsInline style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div style={{ width: 36, height: 36, borderRadius: "50%", background: "rgba(255,255,255,0.15)", border: "1.5px solid rgba(255,255,255,0.4)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </div>
            </div>
          </>
        ) : (
          <img src={item.url} alt={item.filename} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        )}
        <div style={{ position: "absolute", top: 8, left: 8 }}>
          <MkPill tone={isVideo ? "info" : "neutral"}>{isVideo ? "MP4" : ext}</MkPill>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{
            position: "absolute", top: 6, right: 6, width: 22, height: 22,
            borderRadius: "50%", background: "rgba(168,66,56,0.85)", border: "none",
            color: "#fffefb", cursor: "pointer", fontSize: 14, lineHeight: "22px",
            display: "flex", alignItems: "center", justifyContent: "center",
            opacity: 0,
          }}
          className="delete-btn"
        >×</button>
      </div>

      {/* Info */}
      <div style={{ padding: "10px 12px" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#2d2a24", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {item.filename}
        </div>
        <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 3, display: "flex", gap: 6, fontFamily: "monospace" }}>
          <span>{formatBytes(item.size_bytes)}</span>
          <span style={{ color: "#d8d3c7" }}>·</span>
          <span>{formatDate(item.uploaded_at)}</span>
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const v = bytes / 1024 ** i;
  return `${v >= 100 ? Math.round(v) : v.toFixed(v >= 10 ? 1 : 2)} ${units[i]}`;
}

function formatDate(value: string) {
  if (!value) return "—";
  const d = new Date(value);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
