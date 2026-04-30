"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type MediaItem, type Playlist } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard } from "@/components/AdminShell";

interface DraftItem {
  media_id: string;
  display_order: number;
  duration_sec: number;
  media: MediaItem;
}

type EditViewMode = "list" | "timeline";

type TimelineDragState =
  | { kind: "reorder"; mediaId: string; startClientX: number; origIndex: number; currentTargetIndex: number }
  | { kind: "resize";  mediaId: string; startClientX: number; origDurationSec: number; currentDurationSec: number }
  | { kind: "insert";  sourceMediaId: string; startClientX: number; currentTargetIndex: number };

export default function AdminPlaylistsPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftItems, setDraftItems] = useState<DraftItem[]>([]);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  // List view drag state
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  // Upload state (Feature 2)
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [pickerDragging, setPickerDragging] = useState(false);
  const pickerInputRef = useRef<HTMLInputElement>(null);
  // Timeline state (Feature 3)
  const [editViewMode, setEditViewMode] = useState<EditViewMode>("list");
  const [pxPerSec, setPxPerSec] = useState(10);
  const [tlDrag, setTlDrag] = useState<TimelineDragState | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (token: string) => {
    setLoading(true);
    try {
      const [pls, ms] = await Promise.all([api.listPlaylists(token), api.listMedia(token)]);
      setPlaylists(pls);
      setMedia(ms);
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void load(token);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Timeline mouse event handlers (Feature 3)
  useEffect(() => {
    if (!tlDrag) return;

    function effectiveDurSec(d: DraftItem): number {
      if (d.media.mime_type.startsWith("video/")) return d.media.duration_sec ?? 30;
      if (tlDrag?.kind === "resize" && tlDrag.mediaId === d.media_id) return tlDrag.currentDurationSec;
      return d.duration_sec;
    }

    const onMove = (e: MouseEvent) => {
      switch (tlDrag.kind) {
        case "reorder":
        case "insert": {
          if (!timelineRef.current) return;
          const rect = timelineRef.current.getBoundingClientRect();
          const relX = e.clientX - rect.left + timelineRef.current.scrollLeft;
          let cum = 0;
          let tgt = draftItems.length;
          for (let i = 0; i < draftItems.length; i++) {
            const w = effectiveDurSec(draftItems[i]) * pxPerSec;
            if (relX < cum + w / 2) { tgt = i; break; }
            cum += w;
          }
          setTlDrag((d) => d ? { ...d, currentTargetIndex: tgt } : null);
          break;
        }
        case "resize": {
          const delta = (e.clientX - tlDrag.startClientX) / pxPerSec;
          const newDur = Math.max(1, Math.round(tlDrag.origDurationSec + delta));
          setTlDrag((d) => d ? { ...d, currentDurationSec: newDur } : null);
          break;
        }
      }
    };

    const onUp = () => {
      if (!tlDrag) return;
      switch (tlDrag.kind) {
        case "reorder": {
          const { origIndex, currentTargetIndex } = tlDrag;
          setTlDrag(null);
          if (origIndex === currentTargetIndex) return;
          const next = [...draftItems];
          const [moved] = next.splice(origIndex, 1);
          const at = currentTargetIndex > origIndex ? currentTargetIndex - 1 : currentTargetIndex;
          next.splice(at, 0, moved);
          setDraftItems(next.map((d, i) => ({ ...d, display_order: i })));
          break;
        }
        case "insert": {
          const { sourceMediaId, currentTargetIndex } = tlDrag;
          setTlDrag(null);
          const m = media.find((x) => x.id === sourceMediaId);
          if (!m) return;
          const newItem: DraftItem = {
            media_id: m.id,
            display_order: currentTargetIndex,
            duration_sec: m.mime_type.startsWith("video/") ? Math.round(m.duration_sec ?? 30) : 10,
            media: m,
          };
          const next = [...draftItems];
          next.splice(currentTargetIndex, 0, newItem);
          setDraftItems(next.map((d, i) => ({ ...d, display_order: i })));
          break;
        }
        case "resize": {
          const { mediaId, currentDurationSec } = tlDrag;
          setTlDrag(null);
          setDraftItems(draftItems.map((d) => d.media_id === mediaId ? { ...d, duration_sec: currentDurationSec } : d));
          break;
        }
      }
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tlDrag, draftItems, pxPerSec, media]);

  function selectPlaylist(pl: Playlist) {
    setSelectedId(pl.id);
    setError("");
    setSuccess("");
    const byId = Object.fromEntries(media.map((m) => [m.id, m]));
    setDraftItems(
      pl.items
        .filter((i) => byId[i.media_id])
        .map((i) => ({ media_id: i.media_id, display_order: i.display_order, duration_sec: i.duration_sec, media: byId[i.media_id] }))
        .sort((a, b) => a.display_order - b.display_order)
    );
  }

  function toggleMedia(m: MediaItem) {
    const inList = draftItems.some((d) => d.media_id === m.id);
    if (inList) {
      setDraftItems(draftItems.filter((d) => d.media_id !== m.id).map((d, i) => ({ ...d, display_order: i })));
    } else {
      setDraftItems([...draftItems, { media_id: m.id, display_order: draftItems.length, duration_sec: m.mime_type.startsWith("video/") ? 0 : 10, media: m }]);
    }
  }

  function moveItem(index: number, dir: -1 | 1) {
    const next = [...draftItems];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setDraftItems(next.map((d, i) => ({ ...d, display_order: i })));
  }

  function handleDragStart(e: React.DragEvent, idx: number) {
    setDragIdx(idx);
    e.dataTransfer.effectAllowed = "move";
  }

  function handleDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOver(idx);
  }

  async function handleDrop(e: React.DragEvent, targetIdx: number) {
    e.preventDefault();
    if (dragIdx === null || dragIdx === targetIdx) { setDragIdx(null); setDragOver(null); return; }
    const newItems = [...draftItems];
    const [moved] = newItems.splice(dragIdx, 1);
    newItems.splice(targetIdx, 0, moved);
    const updated = newItems.map((d, i) => ({ ...d, display_order: i }));
    setDraftItems(updated);
    setDragIdx(null);
    setDragOver(null);
    const token = getAccessToken();
    if (!token || !selectedId) return;
    try {
      await api.reorderPlaylistItems(token, selectedId, updated.map((d, i) => ({ id: d.media_id, sort_order: i })));
    } catch {
      // reorder is best-effort; full save will sync on next explicit save
    }
  }

  function handleDragEnd() {
    setDragIdx(null);
    setDragOver(null);
  }

  function setDuration(index: number, v: number) {
    setDraftItems(draftItems.map((d, i) => i === index ? { ...d, duration_sec: v } : d));
  }

  async function uploadAndAddToMedia(file: File) {
    const token = getAccessToken();
    if (!token) return;
    setUploading(true);
    setUploadError("");
    try {
      const newMedia = await api.uploadMedia(token, file);
      setMedia((cur) => [newMedia, ...cur]);
      if (selectedId) {
        setDraftItems((cur) => [...cur, {
          media_id: newMedia.id,
          display_order: cur.length,
          duration_sec: newMedia.mime_type.startsWith("video/") ? Math.round(newMedia.duration_sec ?? 0) : 10,
          media: newMedia,
        }]);
      }
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : "アップロードに失敗しました");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreate() {
    const token = getAccessToken();
    if (!token || !newName.trim()) return;
    setCreating(true);
    setError("");
    try {
      const pl = await api.createPlaylist(token, newName.trim()) as Playlist;
      setPlaylists((c) => [...c, { ...pl, items: [] }]);
      setNewName("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally {
      setCreating(false);
    }
  }

  async function handleSave() {
    const token = getAccessToken();
    if (!token || !selectedId) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await api.updatePlaylistItems(token, selectedId, draftItems.map((d, i) => ({ media_id: d.media_id, display_order: i, duration_sec: d.duration_sec })));
      const pls = await api.listPlaylists(token);
      setPlaylists(pls);
      setSuccess("保存しました");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("このプレイリストを削除しますか？")) return;
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deletePlaylist(token, id);
      setPlaylists((c) => c.filter((p) => p.id !== id));
      if (selectedId === id) { setSelectedId(null); setDraftItems([]); }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  const selectedPl = playlists.find((p) => p.id === selectedId) ?? null;

  // Stats for the selected playlist
  const totalSec = useMemo(() => draftItems.reduce((s, d) => {
    const dur = d.media.mime_type.startsWith("video/") ? (d.media.duration_sec ?? 0) : d.duration_sec;
    return s + dur;
  }, 0), [draftItems]);
  const videoCount = draftItems.filter((d) => d.media.mime_type.startsWith("video/")).length;
  const imageCount = draftItems.length - videoCount;
  const totalBytes = draftItems.reduce((s, d) => s + d.media.size_bytes, 0);

  // Preview playback state
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [previewIdx, setPreviewIdx] = useState(0);
  const [previewProgress, setPreviewProgress] = useState(0);

  // Clamp previewIdx when items change
  useEffect(() => {
    if (draftItems.length === 0) { setPreviewIdx(0); setPreviewProgress(0); return; }
    if (previewIdx >= draftItems.length) {
      setPreviewIdx(0);
      setPreviewProgress(0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftItems.length]);

  // Stop preview when playlist is deselected
  useEffect(() => {
    setPreviewPlaying(false);
    setPreviewIdx(0);
    setPreviewProgress(0);
  }, [selectedId]);

  // Image timing effect
  useEffect(() => {
    const item = draftItems[previewIdx];
    if (!previewPlaying || !item || !item.media.mime_type.startsWith("image/")) return;
    const dur = item.duration_sec * 1000;
    const startTime = Date.now();
    const interval = setInterval(() => {
      const progress = Math.min((Date.now() - startTime) / dur, 1);
      setPreviewProgress(progress);
      if (progress >= 1) {
        clearInterval(interval);
        const next = previewIdx + 1;
        if (next < draftItems.length) {
          setPreviewIdx(next);
          setPreviewProgress(0);
        } else {
          setPreviewPlaying(false);
          setPreviewIdx(0);
          setPreviewProgress(0);
        }
      }
    }, 50);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewPlaying, previewIdx]);

  function advancePreview() {
    const next = previewIdx + 1;
    if (next < draftItems.length) {
      setPreviewIdx(next);
      setPreviewProgress(0);
    } else {
      setPreviewPlaying(false);
      setPreviewIdx(0);
      setPreviewProgress(0);
    }
  }

  // Preview: current item
  const previewItem = draftItems[previewIdx] ?? null;

  return (
    <AdminShell
      active="playlist"
      title={selectedPl ? selectedPl.name : "プレイリスト管理"}
      breadcrumb="ホーム / コンテンツ管理 / プレイリスト"
      subtitle={selectedPl ? `${draftItems.length}件 · 合計 ${fmtDuration(totalSec)}` : undefined}
      actions={
        selectedPl ? (
          <>
            <MkBtn variant="default" size="sm" onClick={() => { setSelectedId(null); setDraftItems([]); }}>← 一覧へ</MkBtn>
            <MkBtn variant="primary" size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "保存中…" : "✓ 変更を保存"}
            </MkBtn>
          </>
        ) : undefined
      }
    >
      {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>{error}</div>}
      {success && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#eaf0e8", border: "1px solid #4a7c4e", color: "#3a6240", fontSize: 13 }}>{success}</div>}

      {!selectedPl ? (
        /* ─ LIST VIEW ─ */
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Create */}
          <MkCard>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 14 }}>新規プレイリスト作成</div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); }}
                placeholder="プレイリスト名（例：平日 昼間プレイリスト）"
                style={{ flex: 1, border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 12px", height: 34, fontSize: 12.5, color: "#2d2a24", fontFamily: '"Noto Sans JP", system-ui, sans-serif', outline: "none" }}
              />
              <MkBtn variant="primary" onClick={handleCreate} disabled={creating || !newName.trim()}>
                {creating ? "作成中…" : "+ 作成"}
              </MkBtn>
            </div>
          </MkCard>

          {/* List */}
          <MkCard padding="0">
            <div style={{ padding: "16px 20px", borderBottom: "1px solid #efece5", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15" }}>プレイリスト一覧</div>
              <span style={{ fontSize: 11.5, color: "#a8a198", fontFamily: "monospace" }}>{playlists.length}件</span>
            </div>
            {loading ? (
              <div style={{ padding: "32px 20px", textAlign: "center", color: "#a8a198" }}>読み込み中…</div>
            ) : playlists.length === 0 ? (
              <div style={{ padding: "32px 20px", textAlign: "center", color: "#a8a198" }}>プレイリストがありません</div>
            ) : (
              playlists.map((pl, i) => (
                <div
                  key={pl.id}
                  onClick={() => selectPlaylist(pl)}
                  style={{
                    display: "flex", alignItems: "center", gap: 14, padding: "14px 20px",
                    borderTop: i > 0 ? "1px solid #efece5" : "none",
                    cursor: "pointer", background: "#fffefb",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "#f4f1ea"; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "#fffefb"; }}
                >
                  <div
                    style={{
                      width: 40, height: 40, borderRadius: 7, background: "#1d1a15",
                      display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                    }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="15" y2="18"/>
                      <circle cx="20" cy="15" r="3"/><line x1="20" y1="9" x2="20" y2="12"/>
                    </svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 500, color: "#2d2a24" }}>{pl.name}</div>
                    <div style={{ fontSize: 11, color: "#a8a198", marginTop: 3, fontFamily: "monospace" }}>
                      {pl.items.length} アイテム
                      {pl.items.length > 0 && (
                        <span style={{ marginLeft: 8, color: "#b0a898" }}>
                          · {fmtDuration(pl.items.reduce((s, i) => s + i.duration_sec, 0))}
                        </span>
                      )}
                    </div>
                  </div>
                  <span style={{ fontSize: 12, color: "#a8a198" }}>編集 →</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); void handleDelete(pl.id); }}
                    style={{ background: "none", border: "none", color: "#a84238", cursor: "pointer", fontSize: 12, padding: "4px 8px" }}
                  >
                    削除
                  </button>
                </div>
              ))
            )}
          </MkCard>
        </div>
      ) : (
        /* ─ EDIT VIEW ─ */
        <div className="adm-grid-3" style={{ gap: 20 }}>
          {/* Left: item list */}
          <MkCard padding="0">
            <div style={{ padding: "16px 20px", borderBottom: "1px solid #efece5", display: "flex", alignItems: "center" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15" }}>再生順</div>
                <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>
                  {editViewMode === "list" ? "ドラッグで並び替え · 画像の表示秒数は編集可能" : "メディアをドラッグして配置、画像の右端をドラッグして長さを変更"}
                </div>
              </div>
              {/* View mode toggle */}
              <div style={{ display: "flex", border: "1px solid #d8d3c7", borderRadius: 6, overflow: "hidden", marginRight: 10 }}>
                {(["list", "timeline"] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setEditViewMode(mode)}
                    style={{
                      padding: "4px 10px", fontSize: 11,
                      background: editViewMode === mode ? "#1d1a15" : "transparent",
                      color: editViewMode === mode ? "#fffefb" : "#6b6559",
                      border: "none", cursor: "pointer",
                    }}
                  >
                    {mode === "list" ? "リスト" : "タイムライン"}
                  </button>
                ))}
              </div>
              <MkBtn size="sm" variant="default" onClick={() => document.getElementById("media-picker")?.scrollIntoView({ behavior: "smooth" })}>
                + 追加
              </MkBtn>
            </div>

            {editViewMode === "list" ? (
              /* List view */
              draftItems.length === 0 ? (
                <div style={{ padding: "32px 20px", textAlign: "center", color: "#a8a198", fontSize: 13 }}>
                  下のメディア一覧からアイテムを追加してください
                </div>
              ) : (
                draftItems.map((item, i) => (
                  <div
                    key={item.media_id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, i)}
                    onDragOver={(e) => handleDragOver(e, i)}
                    onDrop={(e) => { void handleDrop(e, i); }}
                    onDragEnd={handleDragEnd}
                    style={{
                      display: "flex", alignItems: "center", gap: 14, padding: "14px 20px",
                      borderTop: dragOver === i ? "2px dashed #c8a96e" : (i > 0 ? "1px solid #efece5" : "none"),
                      background: i === previewIdx && previewPlaying ? "#f0f6f0" : "#fffefb",
                      borderLeft: i === previewIdx && previewPlaying ? "3px solid #4a7c4e" : "3px solid transparent",
                      position: "relative",
                      opacity: dragIdx === i ? 0.4 : 1,
                      cursor: "grab",
                    }}
                  >
                    {/* Drag handle */}
                    <span style={{ fontSize: 16, color: "#c8c0b0", flexShrink: 0, userSelect: "none", lineHeight: 1 }}>⠿</span>
                    {/* Order number */}
                    <div style={{
                      width: 32, height: 32, borderRadius: 5, background: "#1d1a15", color: "#fffefb",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 12, fontWeight: 600, fontFamily: "monospace", flexShrink: 0,
                    }}>
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    {/* Thumbnail */}
                    <div style={{ width: 64, height: 40, borderRadius: 5, overflow: "hidden", background: item.media.mime_type.startsWith("video/") ? "#1d1a15" : "#f4f1ea", flexShrink: 0, border: "1px solid #efece5" }}>
                      {item.media.mime_type.startsWith("video/") ? (
                        <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fffefb" }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        </div>
                      ) : (
                        <img src={item.media.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      )}
                    </div>
                    {/* Info */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: "#2d2a24", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {item.media.filename}
                      </div>
                      <div style={{ fontSize: 10.5, color: "#a8a198", marginTop: 3, fontFamily: "monospace" }}>
                        {item.media.mime_type.startsWith("video/") ? "VIDEO" : "IMAGE"}
                      </div>
                    </div>
                    {/* Duration or timer input */}
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      {item.media.mime_type.startsWith("image/") ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 4, background: "#f4f1ea", border: "1px solid #d8d3c7", borderRadius: 5, padding: "4px 8px" }}>
                          <input
                            type="number"
                            min={1}
                            max={300}
                            value={item.duration_sec}
                            onChange={(e) => setDuration(i, Number(e.target.value))}
                            style={{ width: 28, border: "none", background: "transparent", fontSize: 12, textAlign: "right", fontFamily: "monospace", outline: "none", color: "#2d2a24" }}
                          />
                          <span style={{ fontSize: 10.5, color: "#a8a198" }}>秒</span>
                        </div>
                      ) : (
                        <span style={{ fontSize: 12, color: "#6b6559", fontFamily: "monospace", minWidth: 36, textAlign: "right" }}>動画</span>
                      )}
                    </div>
                    {/* Move buttons */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <button onClick={() => moveItem(i, -1)} disabled={i === 0} style={{ background: "none", border: "none", color: i === 0 ? "#efece5" : "#6b6559", cursor: i === 0 ? "default" : "pointer", fontSize: 11, padding: "1px 4px", lineHeight: 1 }}>▲</button>
                      <button onClick={() => moveItem(i, 1)} disabled={i === draftItems.length - 1} style={{ background: "none", border: "none", color: i === draftItems.length - 1 ? "#efece5" : "#6b6559", cursor: i === draftItems.length - 1 ? "default" : "pointer", fontSize: 11, padding: "1px 4px", lineHeight: 1 }}>▼</button>
                    </div>
                    {/* Remove */}
                    <button onClick={() => toggleMedia(item.media)} style={{ background: "none", border: "none", color: "#a8a198", cursor: "pointer", padding: 4 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  </div>
                ))
              )
            ) : (
              /* Timeline view */
              <PlaylistTimeline
                items={draftItems}
                pxPerSec={pxPerSec}
                tlDrag={tlDrag}
                timelineRef={timelineRef}
                onBlockMouseDown={(mediaId, origIndex) => (e: React.MouseEvent) => {
                  e.preventDefault();
                  setTlDrag({ kind: "reorder", mediaId, startClientX: e.clientX, origIndex, currentTargetIndex: origIndex });
                }}
                onResizeMouseDown={(mediaId, origDurationSec) => (e: React.MouseEvent) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setTlDrag({ kind: "resize", mediaId, startClientX: e.clientX, origDurationSec, currentDurationSec: origDurationSec });
                }}
                onRemove={(mediaId) => {
                  const m = draftItems.find((d) => d.media_id === mediaId)?.media;
                  if (m) toggleMedia(m);
                }}
                onZoomIn={() => setPxPerSec((v) => Math.min(60, v + 5))}
                onZoomOut={() => setPxPerSec((v) => Math.max(5, v - 5))}
              />
            )}

            {/* Media picker */}
            <div id="media-picker" style={{ padding: "16px 20px", borderTop: "1px solid #efece5" }}>
              {/* Hidden file input */}
              <input
                ref={pickerInputRef}
                type="file"
                accept="image/*,video/*"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadAndAddToMedia(f); e.target.value = ""; }}
              />
              {/* Picker header */}
              <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span>メディアを追加</span>
                <button
                  onClick={() => pickerInputRef.current?.click()}
                  style={{ fontSize: 11, padding: "4px 8px", background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 5, cursor: "pointer", color: "#6b6559" }}
                >
                  + アップロード
                </button>
              </div>
              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setPickerDragging(true); }}
                onDragLeave={() => setPickerDragging(false)}
                onDrop={(e) => { e.preventDefault(); setPickerDragging(false); const f = e.dataTransfer.files[0]; if (f) void uploadAndAddToMedia(f); }}
                onClick={() => pickerInputRef.current?.click()}
                style={{
                  border: `1.5px dashed ${pickerDragging ? "#4a7c4e" : "#d8d3c7"}`,
                  borderRadius: 8,
                  background: pickerDragging ? "#eaf0e8" : "#f4f1ea",
                  padding: "10px 14px",
                  marginBottom: 12,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  transition: "all 0.12s",
                }}
              >
                {uploading ? (
                  <span style={{ fontSize: 11.5, color: "#a8a198" }}>アップロード中…</span>
                ) : (
                  <>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round">
                      <path d="M12 3v12M7 8l5-5 5 5"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/>
                    </svg>
                    <span style={{ fontSize: 11.5, color: "#a8a198" }}>新しいファイルをここにドロップ、またはクリックしてアップロード</span>
                  </>
                )}
              </div>
              {uploadError && <div style={{ fontSize: 11, color: "#a84238", marginBottom: 8 }}>{uploadError}</div>}
              {/* Media grid */}
              {media.length === 0 ? (
                <p style={{ fontSize: 12, color: "#a8a198" }}>
                  <button onClick={() => router.push(`/${params.tenant}/admin/media`)} style={{ color: "#4a7c4e", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
                    メディア管理
                  </button>
                  からアップロードしてください
                </p>
              ) : (
                <div className="adm-grid-4" style={{ gap: 8 }}>
                  {media.map((m) => {
                    const inPl = draftItems.some((d) => d.media_id === m.id);
                    return (
                      <button
                        key={m.id}
                        onClick={() => { if (editViewMode === "list") toggleMedia(m); }}
                        onMouseDown={(e) => {
                          if (editViewMode !== "timeline") return;
                          e.preventDefault();
                          setTlDrag({ kind: "insert", sourceMediaId: m.id, startClientX: e.clientX, currentTargetIndex: draftItems.length });
                        }}
                        style={{
                          position: "relative", padding: 0, border: `2px solid ${inPl ? "#4a7c4e" : "transparent"}`,
                          borderRadius: 7, overflow: "hidden", cursor: editViewMode === "timeline" ? "grab" : "pointer", background: "none",
                        }}
                        title={editViewMode === "timeline" ? "ドラッグしてタイムラインに配置" : undefined}
                      >
                        <div style={{ aspectRatio: "16/10", background: m.mime_type.startsWith("video/") ? "#1d1a15" : "#f4f1ea" }}>
                          {m.mime_type.startsWith("video/") ? (
                            <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                            </div>
                          ) : (
                            <img src={m.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                          )}
                        </div>
                        <div style={{ padding: "4px 6px", background: "#fffefb" }}>
                          <div style={{ fontSize: 9, color: "#2d2a24", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.filename}</div>
                        </div>
                        {inPl && (
                          <div style={{ position: "absolute", top: 4, right: 4, width: 16, height: 16, borderRadius: "50%", background: "#4a7c4e", display: "flex", alignItems: "center", justifyContent: "center" }}>
                            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                          </div>
                        )}
                        {editViewMode === "timeline" && (
                          <div style={{ position: "absolute", bottom: 4, left: 4, right: 4, display: "flex", justifyContent: "center" }}>
                            <span style={{ fontSize: 8, background: "rgba(29,26,21,0.6)", color: "#fffefb", borderRadius: 3, padding: "1px 4px" }}>ドラッグで配置</span>
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </MkCard>

          {/* Right: preview + summary */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <MkCard>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 4 }}>
                <div style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: "#1d1a15" }}>プレビュー</div>
                {draftItems.length > 0 && (
                  <span style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace" }}>
                    {previewIdx + 1} / {draftItems.length}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginBottom: 12 }}>横型サイネージ (16:9)</div>
              <div style={{
                aspectRatio: "16/9", background: "#1d1a15", borderRadius: 7, overflow: "hidden",
                position: "relative",
                backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 10px, transparent 10px 20px)",
              }}>
                {previewItem ? (
                  previewItem.media.mime_type.startsWith("image/") ? (
                    <img src={previewItem.media.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  ) : (
                    <video
                      key={previewItem.media_id}
                      src={previewItem.media.url}
                      autoPlay={previewPlaying}
                      muted={false}
                      playsInline
                      onEnded={advancePreview}
                      onTimeUpdate={(e) => {
                        const v = e.currentTarget;
                        if (v.duration) setPreviewProgress(v.currentTime / v.duration);
                      }}
                      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                    />
                  )
                ) : (
                  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#fffefb", gap: 8, opacity: 0.4 }}>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.5" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                    <div style={{ fontSize: 10.5, fontFamily: "monospace" }}>アイテムなし</div>
                  </div>
                )}
                {/* Progress bar — shows progress within current item */}
                {previewItem && (
                  <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 3, background: "rgba(255,255,255,0.15)" }}>
                    <div style={{ width: `${previewProgress * 100}%`, height: "100%", background: "#4a7c4e", transition: "width 0.05s linear" }} />
                  </div>
                )}
                {/* Playlist position dots */}
                {draftItems.length > 1 && (
                  <div style={{ position: "absolute", bottom: 10, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 4 }}>
                    {draftItems.map((_, i) => (
                      <button
                        key={i}
                        onClick={() => { setPreviewIdx(i); setPreviewProgress(0); }}
                        style={{
                          width: i === previewIdx ? 16 : 5, height: 5, borderRadius: 3,
                          background: i === previewIdx ? "#4a7c4e" : "rgba(255,255,255,0.35)",
                          border: "none", cursor: "pointer", padding: 0,
                          transition: "all 0.2s",
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
              {/* Playback controls */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 12 }}>
                {/* Previous */}
                <button
                  onClick={() => { setPreviewIdx(Math.max(0, previewIdx - 1)); setPreviewProgress(0); }}
                  disabled={previewIdx === 0 || draftItems.length === 0}
                  style={{ width: 28, height: 28, borderRadius: "50%", border: "1px solid #d8d3c7", background: "#f4f1ea", cursor: previewIdx === 0 ? "default" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: previewIdx === 0 ? 0.35 : 1 }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#6b6559" strokeWidth="2.2" strokeLinecap="round"><polyline points="15 18 9 12 15 6"/></svg>
                </button>
                {/* Stop */}
                <button
                  onClick={() => { setPreviewPlaying(false); setPreviewIdx(0); setPreviewProgress(0); }}
                  disabled={draftItems.length === 0}
                  style={{ width: 28, height: 28, borderRadius: "50%", border: "1px solid #d8d3c7", background: "#f4f1ea", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: draftItems.length === 0 ? 0.35 : 1 }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="#6b6559"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
                </button>
                {/* Play / Pause */}
                <button
                  onClick={() => { if (draftItems.length === 0) return; setPreviewPlaying((p) => !p); }}
                  disabled={draftItems.length === 0}
                  style={{ width: 36, height: 36, borderRadius: "50%", border: "none", background: "#1d1a15", cursor: draftItems.length === 0 ? "default" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: draftItems.length === 0 ? 0.35 : 1 }}
                >
                  {previewPlaying ? (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="#fffefb"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>
                  ) : (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="#fffefb"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  )}
                </button>
                {/* Next */}
                <button
                  onClick={() => { setPreviewIdx(Math.min(draftItems.length - 1, previewIdx + 1)); setPreviewProgress(0); }}
                  disabled={previewIdx >= draftItems.length - 1 || draftItems.length === 0}
                  style={{ width: 28, height: 28, borderRadius: "50%", border: "1px solid #d8d3c7", background: "#f4f1ea", cursor: previewIdx >= draftItems.length - 1 ? "default" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: previewIdx >= draftItems.length - 1 ? 0.35 : 1 }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#6b6559" strokeWidth="2.2" strokeLinecap="round"><polyline points="9 18 15 12 9 6"/></svg>
                </button>
              </div>
              {previewItem && (
                <div style={{ marginTop: 8, fontSize: 10.5, color: "#a8a198", textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {previewItem.media.filename}
                </div>
              )}
            </MkCard>

            <MkCard>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 14 }}>サマリー</div>
              {[
                ["合計時間", fmtDuration(totalSec)],
                ["コンテンツ数", `${draftItems.length} 件（動画${videoCount} / 画像${imageCount}）`],
                ["総容量", formatBytes(totalBytes)],
              ].map((row, i) => (
                <div key={i} style={{ display: "flex", padding: "10px 0", borderTop: i > 0 ? "1px solid #efece5" : "none", fontSize: 12, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
                  <span style={{ flex: 1, color: "#a8a198" }}>{row[0]}</span>
                  <span style={{ color: "#2d2a24", fontWeight: 500 }}>{row[1]}</span>
                </div>
              ))}
            </MkCard>
          </div>
        </div>
      )}
    </AdminShell>
  );
}

function PlaylistTimeline({
  items,
  pxPerSec,
  tlDrag,
  timelineRef,
  onBlockMouseDown,
  onResizeMouseDown,
  onRemove,
  onZoomIn,
  onZoomOut,
}: {
  items: DraftItem[];
  pxPerSec: number;
  tlDrag: TimelineDragState | null;
  timelineRef: React.RefObject<HTMLDivElement | null>;
  onBlockMouseDown: (mediaId: string, origIndex: number) => (e: React.MouseEvent) => void;
  onResizeMouseDown: (mediaId: string, origDurationSec: number) => (e: React.MouseEvent) => void;
  onRemove: (mediaId: string) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
}) {
  function effectiveDur(d: DraftItem): number {
    if (d.media.mime_type.startsWith("video/")) return d.media.duration_sec ?? 30;
    if (tlDrag?.kind === "resize" && tlDrag.mediaId === d.media_id) return tlDrag.currentDurationSec;
    return d.duration_sec;
  }

  const totalSec = items.reduce((s, d) => s + effectiveDur(d), 0);
  const insertIdx = tlDrag && tlDrag.kind !== "resize" ? tlDrag.currentTargetIndex : null;
  const draggingMediaId = tlDrag?.kind === "reorder" ? tlDrag.mediaId : null;

  const MIN_BLOCK_WIDTH = 40;

  return (
    <div style={{ padding: "12px 20px 16px" }}>
      {/* Zoom + total duration */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: "#a8a198" }}>ズーム</span>
        <button
          onClick={onZoomOut}
          style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid #d8d3c7", background: "#f4f1ea", cursor: "pointer", fontSize: 14, lineHeight: 1, color: "#6b6559", display: "flex", alignItems: "center", justifyContent: "center" }}
        >−</button>
        <span style={{ fontSize: 11, fontFamily: "monospace", minWidth: 44, textAlign: "center", color: "#6b6559" }}>{pxPerSec}px/秒</span>
        <button
          onClick={onZoomIn}
          style={{ width: 22, height: 22, borderRadius: 4, border: "1px solid #d8d3c7", background: "#f4f1ea", cursor: "pointer", fontSize: 14, lineHeight: 1, color: "#6b6559", display: "flex", alignItems: "center", justifyContent: "center" }}
        >+</button>
        <span style={{ fontSize: 11, color: "#a8a198", marginLeft: 8 }}>合計: {fmtDuration(Math.round(totalSec))}</span>
      </div>

      {/* Timeline track */}
      <div
        ref={timelineRef}
        style={{
          overflowX: "auto",
          borderRadius: 8,
          border: "1px solid #efece5",
          background: "#f9f7f2",
          minHeight: 80,
          position: "relative",
          userSelect: "none",
        }}
      >
        {items.length === 0 ? (
          <div style={{ padding: "24px 20px", textAlign: "center", color: "#a8a198", fontSize: 12 }}>
            下のメディアをドラッグしてタイムラインに追加してください
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "stretch", height: 80, width: "max-content", minWidth: "100%" }}>
            {items.map((item, i) => {
              const isVideo = item.media.mime_type.startsWith("video/");
              const dur = effectiveDur(item);
              const blockWidth = Math.max(MIN_BLOCK_WIDTH, Math.round(dur * pxPerSec));
              const isDragging = draggingMediaId === item.media_id;

              return (
                <div key={item.media_id} style={{ display: "flex", alignItems: "stretch" }}>
                  {/* Insertion ghost before this block */}
                  {insertIdx === i && (
                    <div style={{ width: 3, flexShrink: 0, background: "#4a7c4e", borderRadius: 2, margin: "4px 0" }} />
                  )}
                  {/* Block */}
                  <div
                    onMouseDown={onBlockMouseDown(item.media_id, i)}
                    style={{
                      width: blockWidth,
                      flexShrink: 0,
                      background: isVideo ? "#2d2a24" : "#eaf0e8",
                      border: `1px solid ${isVideo ? "#3d3a34" : "#c6ddc8"}`,
                      borderLeft: i === 0 ? undefined : "none",
                      position: "relative",
                      cursor: isDragging ? "grabbing" : "grab",
                      opacity: isDragging ? 0.5 : 1,
                      overflow: "hidden",
                      display: "flex",
                      alignItems: "center",
                      transition: "opacity 0.1s",
                    }}
                  >
                    {/* Thumbnail */}
                    <div style={{ width: 36, height: "100%", flexShrink: 0, background: isVideo ? "#1d1a15" : "#f4f1ea", borderRight: `1px solid ${isVideo ? "#3d3a34" : "#c6ddc8"}`, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                      {isVideo ? (
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                      ) : (
                        <img src={item.media.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      )}
                    </div>
                    {/* Label area */}
                    <div style={{ flex: 1, minWidth: 0, padding: "0 6px" }}>
                      {blockWidth > 80 && (
                        <div style={{ fontSize: 9, color: isVideo ? "#c8c0b0" : "#3a6240", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 2 }}>
                          {item.media.filename}
                        </div>
                      )}
                      <div style={{ fontSize: 9, fontFamily: "monospace", color: isVideo ? "#8b8070" : "#5a7c5e" }}>
                        {isVideo ? `${Math.round(dur)}秒` : `${dur}秒`}
                      </div>
                    </div>
                    {/* Remove button */}
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); onRemove(item.media_id); }}
                      style={{
                        position: "absolute", top: 2, right: isVideo ? 2 : 10, width: 14, height: 14,
                        borderRadius: "50%", background: "rgba(168,66,56,0.8)", border: "none",
                        color: "#fffefb", cursor: "pointer", fontSize: 10, display: "flex", alignItems: "center", justifyContent: "center",
                      }}
                    >×</button>
                    {/* Resize handle (images only) */}
                    {!isVideo && (
                      <div
                        data-handle="resize"
                        onMouseDown={onResizeMouseDown(item.media_id, item.duration_sec)}
                        style={{
                          position: "absolute", right: 0, top: 0, bottom: 0,
                          width: 8, cursor: "ew-resize",
                          background: "rgba(74,124,78,0.4)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                        }}
                      >
                        <div style={{ width: 2, height: 16, background: "#4a7c4e", borderRadius: 1 }} />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {/* Insertion ghost at end */}
            {insertIdx === items.length && (
              <div style={{ width: 3, flexShrink: 0, background: "#4a7c4e", borderRadius: 2, margin: "4px 0" }} />
            )}
          </div>
        )}
      </div>
      {/* Time ruler */}
      {items.length > 0 && (
        <div style={{ display: "flex", marginTop: 4, paddingLeft: 0, overflowX: "hidden" }}>
          {Array.from({ length: Math.ceil(totalSec / 5) + 1 }, (_, i) => i * 5).map((sec) => (
            <div key={sec} style={{ position: "relative", width: 5 * pxPerSec, flexShrink: 0, fontSize: 8, color: "#c8c0b0", fontFamily: "monospace" }}>
              {sec}秒
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function fmtDuration(sec: number) {
  if (!sec) return "0秒";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}分 ${s}秒` : `${s}秒`;
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const v = bytes / 1024 ** i;
  return `${v >= 100 ? Math.round(v) : v.toFixed(v >= 10 ? 1 : 2)} ${units[i]}`;
}
