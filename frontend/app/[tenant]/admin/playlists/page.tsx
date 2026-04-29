"use client";

import { useCallback, useEffect, useState } from "react";
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
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);

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
  const totalSec = draftItems.reduce((s, d) => s + d.duration_sec, 0);
  const videoCount = draftItems.filter((d) => d.media.mime_type.startsWith("video/")).length;
  const imageCount = draftItems.length - videoCount;
  const totalBytes = draftItems.reduce((s, d) => s + d.media.size_bytes, 0);

  // Preview: first item
  const previewItem = draftItems[0] ?? null;

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
                <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>ドラッグで並び替え · 画像の表示秒数は編集可能</div>
              </div>
              <MkBtn size="sm" variant="default" onClick={() => document.getElementById("media-picker")?.scrollIntoView({ behavior: "smooth" })}>
                + 追加
              </MkBtn>
            </div>
            {draftItems.length === 0 ? (
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
                    background: "#fffefb", position: "relative",
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
            )}

            {/* Media picker */}
            <div id="media-picker" style={{ padding: "16px 20px", borderTop: "1px solid #efece5" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", marginBottom: 12 }}>メディアを追加</div>
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
                        onClick={() => toggleMedia(m)}
                        style={{
                          position: "relative", padding: 0, border: `2px solid ${inPl ? "#4a7c4e" : "transparent"}`,
                          borderRadius: 7, overflow: "hidden", cursor: "pointer", background: "none",
                        }}
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
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 4 }}>プレビュー</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginBottom: 12 }}>縦型サイネージ (9:16)</div>
              <div style={{
                aspectRatio: "9/16", background: "#1d1a15", borderRadius: 7, overflow: "hidden",
                position: "relative",
                backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 10px, transparent 10px 20px)",
              }}>
                {previewItem ? (
                  previewItem.media.mime_type.startsWith("image/") ? (
                    <img src={previewItem.media.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  ) : (
                    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#fffefb", gap: 10 }}>
                      <div style={{ width: 48, height: 48, borderRadius: "50%", border: "1.5px solid rgba(255,255,255,0.4)", background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                      </div>
                      <div style={{ fontSize: 10.5, fontFamily: "monospace", opacity: 0.7, textAlign: "center", padding: "0 12px", wordBreak: "break-all" }}>
                        {previewItem.media.filename}
                      </div>
                    </div>
                  )
                ) : (
                  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#fffefb", gap: 8, opacity: 0.4 }}>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#fffefb" strokeWidth="1.5" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                    <div style={{ fontSize: 10.5, fontFamily: "monospace" }}>アイテムなし</div>
                  </div>
                )}
                {draftItems.length > 0 && (
                  <div style={{ position: "absolute", left: 12, right: 12, bottom: 10, height: 2, background: "rgba(255,255,255,0.2)", borderRadius: 2 }}>
                    <div style={{ width: `${100 / draftItems.length}%`, height: "100%", background: "#4a7c4e", borderRadius: 2 }} />
                  </div>
                )}
              </div>
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
