"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Playlist, type Schedule } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard } from "@/components/AdminShell";

// ── Timeline view constants ────────────────────────────────────────────────
const HOUR_HEIGHT = 40; // px per hour in vertical timeline
const TIMELINE_COLORS = [
  "#4f9cf0", "#f0914f", "#4ff09c", "#f04f4f",
  "#9c4ff0", "#f0e14f", "#4ff0e1", "#f04fb0",
];

function timeToPercent(timeStr: string): number {
  const [h, m] = timeStr.split(":").map(Number);
  return ((h * 60 + (m ?? 0)) / (24 * 60)) * 100;
}

const DAYS = ["月", "火", "水", "木", "金", "土", "日"] as const;
const HOURS = Array.from({ length: 24 }, (_, i) => i);

const PALETTE = [
  { bg: "#eaf0e8", fg: "#3a6240", border: "#4a7c4e" },
  { bg: "#f7ecd9", fg: "#b8763a", border: "#b8763a" },
  { bg: "#e4eef5", fg: "#2e6b8e", border: "#2e6b8e" },
  { bg: "#f6e0dc", fg: "#a84238", border: "#a84238" },
  { bg: "#f4f1ea", fg: "#6b6559", border: "#a8a198" },
];

function timeToMinutes(t: string) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + (m ?? 0);
}

function minutesToTime(m: number): string {
  const clamped = Math.max(0, Math.min(1439, Math.round(m / 15) * 15));
  return `${String(Math.floor(clamped / 60)).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
}

function ConfirmDialog({ open, title, description, onConfirm, onCancel, danger }: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onCancel}
    >
      <div
        style={{ background: "#fffefb", borderRadius: 12, padding: 28, width: 360, boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ fontSize: 15, fontWeight: 600, color: "#1d1a15", marginBottom: 8 }}>{title}</div>
        {description && <div style={{ fontSize: 12.5, color: "#6b6559", lineHeight: 1.6, marginBottom: 20 }}>{description}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={{ padding: "8px 16px", borderRadius: 7, border: "1px solid #d8d3c7", background: "#fffefb", fontSize: 12.5, cursor: "pointer", color: "#6b6559" }}>キャンセル</button>
          <button onClick={onConfirm} style={{ padding: "8px 16px", borderRadius: 7, border: "none", background: danger ? "#a84238" : "#4a7c4e", color: "#fffefb", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>削除</button>
        </div>
      </div>
    </div>
  );
}

type DraggingState = {
  type: "move" | "resize";
  id: string;
  startX: number;
  startY: number;
  origStartMin: number;
  origEndMin: number;
  origDay: number;
  origDayOfWeek: number;
  offsetMin: number;
  tempStartMin: number;
  tempEndMin: number;
  tempDay: number;
};

// ── Vertical Timeline component ───────────────────────────────────────────
interface VerticalTimelineProps {
  schedules: Schedule[];
  playlists: Playlist[];
  plColorMap: Record<string, number>;
  conflictIds: Set<string>;
  onDelete: (id: string) => void;
}

function VerticalTimeline({ schedules, playlists, plColorMap, conflictIds, onDelete }: VerticalTimelineProps) {
  const playlistById = Object.fromEntries(playlists.map((p) => [p.id, p]));
  const totalHeight = HOUR_HEIGHT * 24;

  const [hoveredId, setHoveredId] = useState<string | null>(null);

  function getBlocksForDay(dayIndex: number) {
    return schedules.filter((s) => s.day_of_week === dayIndex || s.day_of_week === -1);
  }

  return (
    <MkCard padding="0">
      <div style={{ overflowX: "auto" }}>
        {/* Header row: time gutter + day columns */}
        <div style={{ display: "flex", minWidth: 680 }}>
          {/* Time gutter header */}
          <div style={{ width: 52, flexShrink: 0, borderRight: "1px solid #efece5", background: "#f4f1ea" }} />
          {/* Day headers */}
          {DAYS.map((day, di) => {
            const isWeekend = di >= 5;
            return (
              <div
                key={day}
                style={{
                  flex: 1,
                  textAlign: "center",
                  padding: "10px 4px",
                  fontSize: 12.5,
                  fontWeight: 700,
                  color: isWeekend ? "#a84238" : "#2d2a24",
                  fontFamily: '"Noto Sans JP", system-ui, sans-serif',
                  borderLeft: di > 0 ? "1px solid #efece5" : undefined,
                  background: isWeekend ? "#fdf5f4" : "#f4f1ea",
                  borderBottom: "1px solid #efece5",
                }}
              >
                {day}
              </div>
            );
          })}
        </div>

        {/* Grid body */}
        <div style={{ display: "flex", position: "relative", minWidth: 680 }}>
          {/* Time gutter */}
          <div style={{ width: 52, flexShrink: 0, borderRight: "1px solid #efece5", background: "#fafaf8", position: "relative", height: totalHeight }}>
            {HOURS.map((h) => (
              <div
                key={h}
                style={{
                  position: "absolute",
                  top: h * HOUR_HEIGHT - 7,
                  right: 6,
                  fontSize: 9.5,
                  color: "#a8a198",
                  fontFamily: "monospace",
                  lineHeight: 1,
                  userSelect: "none",
                }}
              >
                {String(h).padStart(2, "0")}:00
              </div>
            ))}
            {/* 24:00 label */}
            <div style={{ position: "absolute", top: totalHeight - 7, right: 6, fontSize: 9.5, color: "#a8a198", fontFamily: "monospace", lineHeight: 1, userSelect: "none" }}>
              24:00
            </div>
          </div>

          {/* Day columns */}
          {DAYS.map((day, di) => {
            const dayBlocks = getBlocksForDay(di);
            const isWeekend = di >= 5;
            return (
              <div
                key={day}
                style={{
                  flex: 1,
                  position: "relative",
                  height: totalHeight,
                  borderLeft: di > 0 ? "1px solid #efece5" : undefined,
                  background: isWeekend ? "#fdf9f8" : "#fffefb",
                }}
              >
                {/* Hour grid lines */}
                {HOURS.map((h) => (
                  <div
                    key={h}
                    style={{
                      position: "absolute",
                      top: h * HOUR_HEIGHT,
                      left: 0,
                      right: 0,
                      borderTop: h === 0 ? "none" : h % 6 === 0 ? "1px solid #d8d3c7" : "1px solid #efece5",
                    }}
                  />
                ))}

                {/* Schedule blocks */}
                {dayBlocks.map((s) => {
                  const topPct = timeToPercent(s.start_time);
                  const heightPct = timeToPercent(s.end_time) - topPct;
                  const topPx = (topPct / 100) * totalHeight;
                  const heightPx = Math.max(16, (heightPct / 100) * totalHeight);
                  const colorHex = TIMELINE_COLORS[(plColorMap[s.playlist_id] ?? 0) % TIMELINE_COLORS.length];
                  const plName = playlistById[s.playlist_id]?.name ?? "不明";
                  const isHovered = hoveredId === s.id;
                  const isConflict = conflictIds.has(s.id);

                  return (
                    <div
                      key={s.id}
                      style={{
                        position: "absolute",
                        top: topPx + 1,
                        left: 3,
                        right: 3,
                        height: heightPx - 2,
                        background: colorHex + "28",
                        border: `2px solid ${colorHex}`,
                        borderRadius: 5,
                        padding: "3px 5px",
                        overflow: "hidden",
                        cursor: "pointer",
                        fontSize: 9.5,
                        fontFamily: '"Noto Sans JP", system-ui, sans-serif',
                        color: "#2d2a24",
                        transition: "opacity 0.12s, box-shadow 0.12s",
                        opacity: isHovered ? 1 : 0.88,
                        boxShadow: isHovered ? `0 4px 16px ${colorHex}55` : "none",
                        zIndex: isHovered ? 10 : 1,
                        userSelect: "none",
                      }}
                      onMouseEnter={() => setHoveredId(s.id)}
                      onMouseLeave={() => setHoveredId(null)}
                      onClick={() => onDelete(s.id)}
                      title={`${plName}\n${s.start_time} – ${s.end_time}\nクリックで削除`}
                    >
                      {/* Color accent bar */}
                      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: colorHex, borderRadius: "3px 0 0 3px" }} />
                      <div style={{ marginLeft: 5, overflow: "hidden" }}>
                        {heightPx >= 20 && (
                          <div style={{ fontWeight: 700, fontSize: 9, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: colorHex, display: "flex", alignItems: "center", gap: 3 }}>
                            {plName}
                            {isConflict && (
                              <span style={{ fontSize: 8, fontWeight: 700, background: "#fde84e", color: "#7a5f0a", borderRadius: 2, padding: "0 3px", flexShrink: 0 }}>重複</span>
                            )}
                          </div>
                        )}
                        {heightPx >= 32 && (
                          <div style={{ fontSize: 8.5, opacity: 0.75, fontFamily: "monospace", marginTop: 1, whiteSpace: "nowrap" }}>
                            {s.start_time}–{s.end_time}
                          </div>
                        )}
                      </div>

                      {/* Hover tooltip overlay */}
                      {isHovered && (
                        <div style={{
                          position: "absolute",
                          bottom: "calc(100% + 6px)",
                          left: "50%",
                          transform: "translateX(-50%)",
                          background: "#1d1a15",
                          color: "#fffefb",
                          borderRadius: 6,
                          padding: "6px 10px",
                          fontSize: 10.5,
                          whiteSpace: "nowrap",
                          zIndex: 50,
                          boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
                          fontFamily: '"Noto Sans JP", system-ui, sans-serif',
                          pointerEvents: "none",
                        }}>
                          <div style={{ fontWeight: 700, marginBottom: 2 }}>{plName}</div>
                          <div style={{ opacity: 0.8, fontFamily: "monospace" }}>{s.start_time} – {s.end_time}</div>
                          <div style={{ opacity: 0.6, fontSize: 9.5, marginTop: 3 }}>クリックで削除</div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </MkCard>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────
export default function AdminSchedulesPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [formPlaylistId, setFormPlaylistId] = useState("");
  const [formDow, setFormDow] = useState("-1");
  const [formStart, setFormStart] = useState("09:00");
  const [formEnd, setFormEnd] = useState("18:00");
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const [viewMode, setViewMode] = useState<"list" | "timeline">("list");

  const [confirmTarget, setConfirmTarget] = useState<string | null>(null);
  const [dragging, setDragging] = useState<DraggingState | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const schedulesRef = useRef<Schedule[]>([]);

  const load = useCallback(async (token: string) => {
    setLoading(true);
    try {
      const [ss, pls] = await Promise.all([api.listSchedules(token), api.listPlaylists(token)]);
      setSchedules(ss);
      setPlaylists(pls);
      if (pls.length > 0) setFormPlaylistId((cur) => cur || pls[0].id);
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

  useEffect(() => { schedulesRef.current = schedules; }, [schedules]);

  // Drag event handlers
  useEffect(() => {
    if (!dragging) return;

    const ROW_HEIGHT_ESTIMATE = 58;

    const onMouseMove = (e: MouseEvent) => {
      if (!gridRef.current) return;
      const rect = gridRef.current.getBoundingClientRect();
      const DAY_LABEL_WIDTH = 60;
      const gridWidth = rect.width - DAY_LABEL_WIDTH;
      const relX = e.clientX - rect.left - DAY_LABEL_WIDTH;
      const fraction = Math.max(0, Math.min(1, relX / gridWidth));
      const minuteAtCursor = fraction * 1440;

      if (dragging.type === "move") {
        const duration = dragging.origEndMin - dragging.origStartMin;
        let newStart = Math.round((minuteAtCursor - dragging.offsetMin) / 15) * 15;
        newStart = Math.max(0, Math.min(1440 - duration, newStart));
        const newEnd = newStart + duration;

        // Calculate day from Y position
        const headerHeight = 41; // approx header row height
        const relY = e.clientY - rect.top - headerHeight;
        const rowHeight = (rect.height - headerHeight) / 7;
        const newDay = Math.max(0, Math.min(6, Math.floor(relY / rowHeight)));

        setDragging((d) => d ? { ...d, tempStartMin: newStart, tempEndMin: newEnd, tempDay: newDay } : null);
      } else {
        // resize
        let newEnd = Math.round(minuteAtCursor / 15) * 15;
        newEnd = Math.max(dragging.origStartMin + 15, Math.min(1440, newEnd));
        setDragging((d) => d ? { ...d, tempEndMin: newEnd } : null);
      }
    };

    const onMouseUp = async () => {
      if (!dragging) return;
      const token = getAccessToken();
      if (!token) return;

      const { id, tempStartMin, tempEndMin, tempDay, origStartMin, origEndMin, origDay, origDayOfWeek } = dragging;
      setDragging(null);

      // No change — for daily schedules ignore row movement (day_of_week stays -1)
      const dayUnchanged = origDayOfWeek === -1 || tempDay === origDay;
      if (tempStartMin === origStartMin && tempEndMin === origEndMin && dayUnchanged) return;

      const sched = schedulesRef.current.find((s) => s.id === id);
      if (!sched) return;

      const finalDow = origDayOfWeek === -1 ? -1 : tempDay;
      try {
        await api.deleteSchedule(token, id);
        const created = await api.createSchedule(token, {
          playlist_id: sched.playlist_id,
          day_of_week: finalDow,
          start_time: minutesToTime(tempStartMin),
          end_time: minutesToTime(tempEndMin),
        });
        const newSchedule: Schedule = {
          id: created.id,
          playlist_id: sched.playlist_id,
          day_of_week: finalDow,
          start_time: minutesToTime(tempStartMin),
          end_time: minutesToTime(tempEndMin),
        };
        setSchedules((prev) => [...prev.filter((s) => s.id !== id), newSchedule]);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "移動に失敗しました");
        await load(token);
      }
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging]);

  async function handleCreate() {
    const token = getAccessToken();
    if (!token || !formPlaylistId) return;
    setCreating(true);
    setError("");
    setSuccess("");
    try {
      await api.createSchedule(token, { playlist_id: formPlaylistId, day_of_week: Number(formDow), start_time: formStart, end_time: formEnd });
      const ss = await api.listSchedules(token);
      setSchedules(ss);
      setSuccess("スケジュールを追加しました");
      setShowForm(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "追加に失敗しました");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    const token = getAccessToken();
    if (!token) return;
    try {
      await api.deleteSchedule(token, id);
      setSchedules((c) => c.filter((s) => s.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  const playlistById = Object.fromEntries(playlists.map((p) => [p.id, p]));

  const plColorMap: Record<string, number> = {};
  let colorIdx = 0;
  schedules.forEach((s) => {
    if (!(s.playlist_id in plColorMap)) {
      plColorMap[s.playlist_id] = colorIdx++ % PALETTE.length;
    }
  });

  function getBlocksForDay(dayIndex: number) {
    return schedules.filter((s) => s.day_of_week === dayIndex || s.day_of_week === -1);
  }

  const conflictIds = new Set<string>();
  for (let di = 0; di < 7; di++) {
    const blocks = getBlocksForDay(di);
    for (let a = 0; a < blocks.length; a++) {
      for (let b = a + 1; b < blocks.length; b++) {
        const aStart = timeToMinutes(blocks[a].start_time);
        const aEnd = timeToMinutes(blocks[a].end_time);
        const bStart = timeToMinutes(blocks[b].start_time);
        const bEnd = timeToMinutes(blocks[b].end_time);
        if (aStart < bEnd && bStart < aEnd) {
          conflictIds.add(blocks[a].id);
          conflictIds.add(blocks[b].id);
        }
      }
    }
  }

  return (
    <AdminShell
      active="schedule"
      title="配信スケジュール"
      breadcrumb="ホーム / コンテンツ管理 / スケジュール"
      subtitle="曜日 × 時間帯でプレイリストを自動切替"
    >
      {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>{error}</div>}
      {success && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#eaf0e8", border: "1px solid #4a7c4e", color: "#3a6240", fontSize: 13 }}>{success}</div>}
      {conflictIds.size > 0 && (
        <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#fdf7e3", border: "1px solid #c9a83a", color: "#7a5f0a", fontSize: 12.5, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 15 }}>⚠</span>
          <span>時間帯が重複しているスケジュールがあります。黄色のバッジが付いたブロックを確認してください。</span>
        </div>
      )}

      {/* Action bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, gap: 12 }}>
        {/* View mode toggle */}
        <div style={{ display: "flex", border: "1px solid #d8d3c7", borderRadius: 8, overflow: "hidden", background: "#f4f1ea" }}>
          {(["list", "timeline"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              style={{
                padding: "6px 16px",
                fontSize: 12,
                fontWeight: viewMode === mode ? 700 : 400,
                color: viewMode === mode ? "#fffefb" : "#6b6559",
                background: viewMode === mode ? "#4a7c4e" : "transparent",
                border: "none",
                cursor: "pointer",
                fontFamily: '"Noto Sans JP", system-ui, sans-serif',
                transition: "background 0.15s",
              }}
            >
              {mode === "list" ? "リスト表示" : "タイムライン表示"}
            </button>
          ))}
        </div>

        <MkBtn variant="default" size="sm" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "閉じる" : "+ 新規ブロック"}
        </MkBtn>
      </div>

      {/* Add form */}
      {showForm && (
        <MkCard style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 16 }}>新規スケジュールブロック</div>
          {playlists.length === 0 ? (
            <p style={{ fontSize: 12, color: "#a8a198" }}>
              <button onClick={() => router.push(`/${params.tenant}/admin/playlists`)} style={{ color: "#4a7c4e", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
                プレイリスト
              </button>
              を先に作成してください
            </p>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr auto", gap: 12, alignItems: "end" }}>
              <div>
                <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>プレイリスト</label>
                <select
                  value={formPlaylistId}
                  onChange={(e) => setFormPlaylistId(e.target.value)}
                  style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 10px", height: 34, fontSize: 12.5, color: "#2d2a24", background: "#fffefb", outline: "none", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
                >
                  {playlists.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>曜日</label>
                <select
                  value={formDow}
                  onChange={(e) => setFormDow(e.target.value)}
                  style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 10px", height: 34, fontSize: 12.5, color: "#2d2a24", background: "#fffefb", outline: "none", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}
                >
                  <option value="-1">毎日</option>
                  {DAYS.map((d, i) => <option key={i} value={i}>{d}曜</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>開始時刻</label>
                <input type="time" value={formStart} onChange={(e) => setFormStart(e.target.value)} style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 10px", height: 34, fontSize: 12.5, color: "#2d2a24", outline: "none" }} />
              </div>
              <div>
                <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>終了時刻</label>
                <input type="time" value={formEnd} onChange={(e) => setFormEnd(e.target.value)} style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, padding: "0 10px", height: 34, fontSize: 12.5, color: "#2d2a24", outline: "none" }} />
              </div>
              <MkBtn variant="primary" onClick={handleCreate} disabled={creating}>
                {creating ? "追加中…" : "追加"}
              </MkBtn>
            </div>
          )}
        </MkCard>
      )}

      {/* Legend */}
      {schedules.length > 0 && (
        <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
          {playlists.filter((p) => p.id in plColorMap).map((p) => {
            const c = PALETTE[plColorMap[p.id]];
            return (
              <div
                key={p.id}
                style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "6px 12px",
                  background: "#fffefb", border: "1px solid #efece5", borderRadius: 999,
                }}
              >
                <span style={{ width: 10, height: 10, borderRadius: 2, background: c.border, flexShrink: 0 }} />
                <span style={{ fontSize: 11.5, color: "#2d2a24", fontWeight: 500, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>{p.name}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Vertical timeline view */}
      {viewMode === "timeline" && (
        <VerticalTimeline
          schedules={schedules}
          playlists={playlists}
          plColorMap={plColorMap}
          conflictIds={conflictIds}
          onDelete={(id) => setConfirmTarget(id)}
        />
      )}

      {/* Weekly grid (list view) */}
      {viewMode === "list" && <MkCard padding="0">
        <div ref={gridRef}>
          {/* Hour header */}
          <div style={{ display: "grid", gridTemplateColumns: "60px 1fr", borderBottom: "1px solid #efece5", background: "#f4f1ea" }}>
            <div style={{ padding: "10px 12px", fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", letterSpacing: "0.4px" }}>HOUR</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(24, 1fr)" }}>
              {HOURS.map((h) => (
                <div key={h} style={{ padding: "10px 0", fontSize: 10, color: "#a8a198", fontFamily: "monospace", textAlign: "center", borderLeft: h % 6 === 0 ? "1px solid #efece5" : "none" }}>
                  {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
                </div>
              ))}
            </div>
          </div>

          {/* Day rows */}
          {DAYS.map((day, di) => {
            const dayBlocks = getBlocksForDay(di);
            const isWeekend = di >= 5;
            return (
              <div
                key={day}
                style={{
                  display: "grid", gridTemplateColumns: "60px 1fr", alignItems: "stretch",
                  borderTop: "1px solid #efece5", minHeight: 58,
                }}
              >
                <div style={{
                  padding: "16px 12px", fontSize: 13, fontWeight: 600, color: "#2d2a24",
                  fontFamily: '"Noto Sans JP", system-ui, sans-serif',
                  display: "flex", alignItems: "center",
                  borderRight: "1px solid #efece5",
                  background: isWeekend ? "#f4f1ea" : "#fffefb",
                }}>
                  {day}
                  {isWeekend && <span style={{ fontSize: 9, color: "#a8a198", marginLeft: 6, fontFamily: "monospace" }}>WKND</span>}
                </div>
                <div style={{ position: "relative", display: "grid", gridTemplateColumns: "repeat(24, 1fr)", padding: "6px 0" }}>
                  {/* Grid lines */}
                  {HOURS.map((h) => (
                    <div key={h} style={{ borderLeft: h > 0 && h % 3 === 0 ? "1px solid #efece5" : "none" }} />
                  ))}
                  {/* Schedule blocks */}
                  <div style={{ position: "absolute", inset: "6px 0", display: "flex" }}>
                    {dayBlocks.length === 0 ? null : dayBlocks.map((s) => {
                      const isDraggingThis = dragging?.id === s.id;
                      const isGhostRow = isDraggingThis && dragging?.origDay !== di;

                      // When dragging this block, show in temp day row only
                      if (isDraggingThis && dragging?.tempDay !== di) return null;

                      const startMin = isDraggingThis ? dragging!.tempStartMin : timeToMinutes(s.start_time);
                      const endMin = isDraggingThis ? dragging!.tempEndMin : timeToMinutes(s.end_time);
                      const totalMin = 24 * 60;
                      const left = `${(startMin / totalMin) * 100}%`;
                      const width = `${((endMin - startMin) / totalMin) * 100}%`;
                      const c = PALETTE[plColorMap[s.playlist_id] ?? 0];
                      const plName = playlistById[s.playlist_id]?.name ?? "不明";

                      return (
                        <div
                          key={s.id}
                          style={{
                            position: "absolute", left, width,
                            top: 0, bottom: 0,
                            background: c.bg, color: c.fg,
                            borderLeft: `3px solid ${c.border}`,
                            borderRadius: "0 5px 5px 0",
                            padding: "4px 8px",
                            fontSize: 10.5, fontFamily: '"Noto Sans JP", system-ui, sans-serif', fontWeight: 500,
                            display: "flex", flexDirection: "column", justifyContent: "center",
                            overflow: "hidden",
                            cursor: isDraggingThis ? "grabbing" : "grab",
                            opacity: isDraggingThis ? 0.85 : 1,
                            userSelect: "none",
                            boxShadow: isDraggingThis ? "0 4px 12px rgba(0,0,0,0.15)" : "none",
                          }}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            if (!gridRef.current) return;
                            const rect = gridRef.current.getBoundingClientRect();
                            const DAY_LABEL_WIDTH = 60;
                            const gridWidth = rect.width - DAY_LABEL_WIDTH;
                            const startMin0 = timeToMinutes(s.start_time);
                            const endMin0 = timeToMinutes(s.end_time);
                            const blockLeftPx = (startMin0 / 1440) * gridWidth;
                            const clickRelX = e.clientX - rect.left - DAY_LABEL_WIDTH;
                            const offsetMin = Math.round(((clickRelX - blockLeftPx) / gridWidth) * 1440);
                            setDragging({
                              type: "move",
                              id: s.id,
                              startX: e.clientX,
                              startY: e.clientY,
                              origStartMin: startMin0,
                              origEndMin: endMin0,
                              origDay: di,
                              origDayOfWeek: s.day_of_week,
                              offsetMin: Math.max(0, offsetMin),
                              tempStartMin: startMin0,
                              tempEndMin: endMin0,
                              tempDay: di,
                            });
                          }}
                          onClick={(e) => {
                            if (dragging) return;
                            e.stopPropagation();
                            setConfirmTarget(s.id);
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 4, overflow: "hidden" }}>
                            <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 600, flex: 1, minWidth: 0 }}>{plName}</div>
                            {conflictIds.has(s.id) && (
                              <span style={{ flexShrink: 0, fontSize: 9, fontWeight: 700, background: "#fde84e", color: "#7a5f0a", borderRadius: 3, padding: "1px 4px", lineHeight: 1.4 }}>重複</span>
                            )}
                          </div>
                          <div style={{ fontSize: 9, opacity: 0.7, fontFamily: "monospace", marginTop: 1 }}>
                            {isDraggingThis ? `${minutesToTime(dragging!.tempStartMin)} – ${minutesToTime(dragging!.tempEndMin)}` : `${s.start_time} – ${s.end_time}`}
                          </div>
                          {/* Resize handle */}
                          <div
                            style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 8, cursor: "ew-resize", background: "rgba(0,0,0,0.12)", borderRadius: "0 5px 5px 0" }}
                            onMouseDown={(e) => {
                              e.stopPropagation();
                              e.preventDefault();
                              const startMin0 = timeToMinutes(s.start_time);
                              const endMin0 = timeToMinutes(s.end_time);
                              setDragging({
                                type: "resize",
                                id: s.id,
                                startX: e.clientX,
                                startY: e.clientY,
                                origStartMin: startMin0,
                                origEndMin: endMin0,
                                origDay: di,
                                origDayOfWeek: s.day_of_week,
                                offsetMin: 0,
                                tempStartMin: startMin0,
                                tempEndMin: endMin0,
                                tempDay: di,
                              });
                            }}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </MkCard>}

      {schedules.length === 0 && !loading && (
        <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
          「+ 新規ブロック」からスケジュールを追加すると、キオスクが自動的に指定時間帯のプレイリストを再生します。ブロックはドラッグで移動・右端でリサイズできます。
        </div>
      )}

      <ConfirmDialog
        open={confirmTarget !== null}
        title="スケジュールを削除しますか？"
        description="この操作は取り消せません。"
        onConfirm={async () => {
          if (confirmTarget) {
            await handleDelete(confirmTarget);
            setConfirmTarget(null);
          }
        }}
        onCancel={() => setConfirmTarget(null)}
        danger
      />
    </AdminShell>
  );
}
