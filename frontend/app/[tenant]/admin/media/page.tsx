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
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
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
      subtitle={`動画・静止画・ロゴを管理 · 合計 ${media.length} 件 / 使用容量 ${formatBytes(stats.totalBytes)}`}
      actions={
        <>
          <MkBtn variant="default" size="sm">
            フォルダ
          </MkBtn>
          <MkBtn variant="primary" onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? "アップロード中…" : "↑ アップロード"}
          </MkBtn>
          <input ref={inputRef} type="file" accept="image/*,video/*" className="hidden" onChange={handleFilePick} />
        </>
      }
    >
      {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>{error}</div>}
      {success && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#eaf0e8", border: "1px solid #4a7c4e", color: "#3a6240", fontSize: 13 }}>{success}</div>}

      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, width: 320 }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ファイル名・タグで検索"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
          />
        </div>
        {/* Filter chips */}
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
              }}
            >
              {filterLabels[f]}
              <span style={{ fontSize: 10, opacity: 0.6, fontFamily: "monospace" }}>{filterCounts[f]}</span>
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {/* Grid/List toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: 2, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 7, padding: 2 }}>
          <button
            onClick={() => setViewMode("grid")}
            style={{ padding: 6, background: viewMode === "grid" ? "#f4f1ea" : "transparent", border: "none", borderRadius: 4, cursor: "pointer" }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={viewMode === "grid" ? "#2d2a24" : "#a8a198"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </button>
          <button
            onClick={() => setViewMode("list")}
            style={{ padding: 6, background: viewMode === "list" ? "#f4f1ea" : "transparent", border: "none", borderRadius: 4, cursor: "pointer" }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={viewMode === "list" ? "#2d2a24" : "#a8a198"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>
            </svg>
          </button>
        </div>
        <button style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "6px 10px", fontSize: 11.5, background: "transparent", color: "#6b6559", border: "none", cursor: "pointer" }}>
          アップロード順
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
        </button>
      </div>

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
        <div style={{ width: 44, height: 44, borderRadius: 7, flexShrink: 0, background: "#eaf0e8", color: "#3a6240", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v12M7 8l5-5 5 5"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/>
          </svg>
        </div>
        <div style={{ flex: 1 }}>
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

      {/* Grid / List */}
      {loading ? (
        <div style={{ textAlign: "center", color: "#a8a198", padding: "48px 0" }}>読み込み中…</div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: "center", color: "#a8a198", padding: "48px 0" }}>
          {media.length === 0 ? "まだメディアが登録されていません" : "検索結果がありません"}
        </div>
      ) : viewMode === "grid" ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {filtered.map((item) => (
            <MediaTile key={item.id} item={item} onDelete={() => handleDelete(item.id, item.filename)} />
          ))}
        </div>
      ) : (
        <MkCard padding="0">
          {filtered.map((item, i) => (
            <MediaRow key={item.id} item={item} onDelete={() => handleDelete(item.id, item.filename)} isFirst={i === 0} />
          ))}
        </MkCard>
      )}
    </AdminShell>
  );
}

function MediaTile({ item, onDelete }: { item: MediaItem; onDelete: () => void }) {
  const isVideo = item.mime_type.startsWith("video/");
  const ext = item.mime_type.split("/")[1]?.toUpperCase() ?? "FILE";

  return (
    <div
      className="group"
      style={{
        background: "#fffefb", border: "1px solid #efece5", borderRadius: 10,
        overflow: "hidden", cursor: "pointer",
        boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
      }}
    >
      <div
        style={{
          aspectRatio: "16/10",
          background: isVideo
            ? `#1d1a15 repeating-linear-gradient(45deg, rgba(255,255,255,0.04) 0 10px, transparent 10px 20px)`
            : "#f4f1ea",
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
              <div style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(255,255,255,0.12)", border: "1.5px solid rgba(255,255,255,0.4)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="6 4 20 12 6 20 6 4"/></svg>
              </div>
            </div>
          </>
        ) : (
          <img src={item.url} alt={item.filename} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        )}
        <div style={{ position: "absolute", top: 8, left: 8 }}>
          <MkPill tone={isVideo ? "info" : "neutral"} dot={false}>{isVideo ? "MP4" : ext}</MkPill>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{
            position: "absolute", top: 6, right: 6, width: 22, height: 22,
            borderRadius: "50%", background: "rgba(168,66,56,0.85)", border: "none",
            color: "#fffefb", cursor: "pointer", fontSize: 14, lineHeight: "22px",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
          className="opacity-0 group-hover:opacity-100 transition-opacity"
        >×</button>
      </div>
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

function MediaRow({ item, onDelete, isFirst }: { item: MediaItem; onDelete: () => void; isFirst: boolean }) {
  const isVideo = item.mime_type.startsWith("video/");
  const ext = item.mime_type.split("/")[1]?.toUpperCase() ?? "FILE";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", borderTop: isFirst ? "none" : "1px solid #efece5" }}>
      <div style={{ width: 56, height: 36, borderRadius: 5, overflow: "hidden", background: isVideo ? "#1d1a15" : "#f4f1ea", flexShrink: 0 }}>
        {isVideo ? (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="6 4 20 12 6 20 6 4"/></svg>
          </div>
        ) : (
          <img src={item.url} alt={item.filename} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        )}
      </div>
      <MkPill tone={isVideo ? "info" : "neutral"} dot={false}>{isVideo ? "MP4" : ext}</MkPill>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#2d2a24", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.filename}</div>
        <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 2, fontFamily: "monospace" }}>{formatBytes(item.size_bytes)} · {formatDate(item.uploaded_at)}</div>
      </div>
      <button onClick={onDelete} style={{ background: "none", border: "none", color: "#a84238", cursor: "pointer", fontSize: 12, padding: "4px 8px" }}>削除</button>
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
