"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, type AppointmentCreate, type MeetingRoom, type TenantSettings, type VisitorAppointment } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

// ── Design tokens ────────────────────────────────────────────────────────────
const FONT_JP   = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

const INPUT_STYLE: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #d8d3c7", borderRadius: 7,
  fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box", outline: "none",
};

// ── Timeline grid constants ──────────────────────────────────────────────────
const SLOT_MIN   = 15;                                   // minutes per slot
const SLOT_W     = 20;                                   // px per slot  (80 px/hour)
const DAY_START  = 8;                                    // 08:00
const DAY_END    = 20;                                   // 20:00
const TOTAL_SLOTS = (DAY_END - DAY_START) * (60 / SLOT_MIN); // 48
const LABEL_W    = 148;                                  // room label column width
const ROW_H      = 72;                                   // row height px
const WEEK_DAY_W = 130;                                  // week view day column px

// ── Types ────────────────────────────────────────────────────────────────────
type DateFilter   = "today" | "week" | "month" | "all";
type StatusFilter = "all" | "pending" | "received" | "expired";
type ViewMode     = "timeline" | "list";
type TimelineMode = "day" | "week" | "month";

interface DragCreate {
  kind: "creating"; roomId: string; rowIdx: number; startSlot: number; endSlot: number;
}
interface DragMove {
  kind: "moving"; apptId: string; origRowIdx: number; currentRowIdx: number;
  currentSlot: number; durSlots: number; slotOffset: number;
}
interface DragResize {
  kind: "resizing"; apptId: string; origDurSlots: number; currentDurSlots: number; origStartX: number;
}
type DragState = { kind: "idle" } | DragCreate | DragMove | DragResize;

// ── Helpers ──────────────────────────────────────────────────────────────────
function padZ(n: number) { return String(n).padStart(2, "0"); }
function dateToStr(d: Date) { return `${d.getFullYear()}-${padZ(d.getMonth() + 1)}-${padZ(d.getDate())}`; }
function fmtDatetime(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}/${padZ(d.getMonth() + 1)}/${padZ(d.getDate())} ${padZ(d.getHours())}:${padZ(d.getMinutes())}`;
}
function toLocalDatetimeValue(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${padZ(d.getMonth() + 1)}-${padZ(d.getDate())}T${padZ(d.getHours())}:${padZ(d.getMinutes())}`;
}
function fmtDateJP(d: Date) {
  const DAYS = ["日", "月", "火", "水", "木", "金", "土"];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 (${DAYS[d.getDay()]})`;
}
function shiftDate(d: Date, days: number): Date {
  const r = new Date(d); r.setDate(r.getDate() + days); return r;
}
// ローカル時刻をタイムゾーンなしISO文字列に変換（バックエンドはnai ve datetimeを期待するため toISOString() 禁止）
function localDtStr(d: Date): string {
  return `${d.getFullYear()}-${padZ(d.getMonth()+1)}-${padZ(d.getDate())}T${padZ(d.getHours())}:${padZ(d.getMinutes())}:00`;
}
function getWeekStart(d: Date): Date {
  const r = new Date(d); r.setHours(0, 0, 0, 0);
  const dow = r.getDay();
  r.setDate(r.getDate() - (dow === 0 ? 6 : dow - 1));
  return r;
}
function getTimelineRange(mode: TimelineMode, date: Date): { from: string; to: string } {
  if (mode === "day") { const s = dateToStr(date); return { from: s, to: s }; }
  if (mode === "week") {
    const ws = getWeekStart(date);
    const we = new Date(ws); we.setDate(ws.getDate() + 6);
    return { from: dateToStr(ws), to: dateToStr(we) };
  }
  const s = new Date(date.getFullYear(), date.getMonth(), 1);
  const e = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  return { from: dateToStr(s), to: dateToStr(e) };
}
function slotToHM(slot: number): [number, number] {
  const total = DAY_START * 60 + slot * SLOT_MIN;
  return [Math.floor(total / 60), total % 60];
}
function slotToTimeStr(slot: number): string {
  const [h, m] = slotToHM(slot);
  return `${padZ(h)}:${padZ(m)}`;
}
function dateTimeToSlot(d: Date): number {
  return (d.getHours() * 60 + d.getMinutes() - DAY_START * 60) / SLOT_MIN;
}
function slotsForDuration(min: number): number { return Math.max(1, Math.round(min / SLOT_MIN)); }
function slotsToMin(slots: number): number { return slots * SLOT_MIN; }
function roomColor(r: MeetingRoom) { return r.color ?? "#4a7c4e"; }

// ── StatusBadge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  if (status === "received") return <MkPill tone="live">チェックイン済</MkPill>;
  if (status === "expired")  return <MkPill tone="off">期限切れ</MkPill>;
  return <MkPill tone="info">待機中</MkPill>;
}

// ── AppointmentForm ──────────────────────────────────────────────────────────
function AppointmentForm({
  data, onChange, onSubmit, onCancel, saving, error, submitLabel, staffList, purposeList, rooms,
}: {
  data: AppointmentCreate;
  onChange: (d: AppointmentCreate) => void;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  saving: boolean; error: string | null; submitLabel: string;
  staffList: string[]; purposeList: string[]; rooms: MeetingRoom[];
}) {
  const endTimeValue = (() => {
    if (!data.scheduled_at) return "";
    const start = new Date(data.scheduled_at);
    if (isNaN(start.getTime())) return "";
    const end = new Date(start.getTime() + (data.duration_minutes ?? 60) * 60000);
    return `${end.getFullYear()}-${padZ(end.getMonth() + 1)}-${padZ(end.getDate())}T${padZ(end.getHours())}:${padZ(end.getMinutes())}`;
  })();

  function handleStartChange(v: string) {
    if (!v) { onChange({ ...data, scheduled_at: v }); return; }
    const newStart = new Date(v);
    if (!isNaN(newStart.getTime()) && endTimeValue) {
      const end = new Date(endTimeValue);
      const diff = Math.round((end.getTime() - newStart.getTime()) / 60000);
      if (diff >= SLOT_MIN) { onChange({ ...data, scheduled_at: v, duration_minutes: diff }); return; }
    }
    onChange({ ...data, scheduled_at: v });
  }

  function handleEndChange(v: string) {
    if (!v || !data.scheduled_at) return;
    const start = new Date(data.scheduled_at);
    const end   = new Date(v);
    if (isNaN(start.getTime()) || isNaN(end.getTime())) return;
    const diff = Math.round((end.getTime() - start.getTime()) / 60000);
    onChange({ ...data, duration_minutes: Math.max(SLOT_MIN, diff) });
  }

  return (
    <form onSubmit={onSubmit}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
            氏名 <span style={{ color: "#a84238" }}>*</span>
          </label>
          <input type="text" required value={data.visitor_name}
            onChange={e => onChange({ ...data, visitor_name: e.target.value })}
            style={INPUT_STYLE} placeholder="例：佐々木 美咲" />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>会社名</label>
          <input type="text" value={data.company ?? ""}
            onChange={e => onChange({ ...data, company: e.target.value })}
            style={INPUT_STYLE} placeholder="例：アルチザン株式会社" />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>目的</label>
          {purposeList.length > 0 ? (
            <select value={data.purpose ?? ""} onChange={e => onChange({ ...data, purpose: e.target.value })} style={INPUT_STYLE}>
              <option value="">未選択</option>
              {purposeList.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input type="text" value={data.purpose ?? ""}
              onChange={e => onChange({ ...data, purpose: e.target.value })}
              style={INPUT_STYLE} placeholder="例：打ち合わせ" />
          )}
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>担当者</label>
          {staffList.length > 0 ? (
            <select value={data.staff ?? ""} onChange={e => onChange({ ...data, staff: e.target.value })} style={INPUT_STYLE}>
              <option value="">未選択</option>
              {staffList.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input type="text" value={data.staff ?? ""}
              onChange={e => onChange({ ...data, staff: e.target.value })}
              style={INPUT_STYLE} placeholder="例：田中" />
          )}
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
            来社開始 <span style={{ color: "#a84238" }}>*</span>
          </label>
          <input type="datetime-local" required value={data.scheduled_at}
            onChange={e => handleStartChange(e.target.value)}
            style={INPUT_STYLE} />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>来社終了</label>
          <input type="datetime-local" value={endTimeValue}
            onChange={e => handleEndChange(e.target.value)}
            style={INPUT_STYLE} />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>会議室</label>
          <select
            value={data.meeting_room_id ?? ""}
            onChange={e => onChange({ ...data, meeting_room_id: e.target.value || undefined })}
            style={INPUT_STYLE}
          >
            <option value="">未指定</option>
            {rooms.filter(r => r.is_active).map(r => (
              <option key={r.id} value={r.id}>{r.name}{r.location ? ` (${r.location})` : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>メモ</label>
          <input type="text" value={data.notes ?? ""}
            onChange={e => onChange({ ...data, notes: e.target.value })}
            style={INPUT_STYLE} placeholder="任意のメモ" />
        </div>
      </div>
      {error && <div style={{ fontSize: 12.5, color: "#a84238", marginBottom: 12, fontFamily: FONT_JP }}>{error}</div>}
      <div style={{ display: "flex", gap: 10 }}>
        <MkBtn type="submit" variant="primary" size="sm" disabled={saving}>
          {saving ? "保存中..." : submitLabel}
        </MkBtn>
        <MkBtn variant="default" size="sm" onClick={onCancel}>キャンセル</MkBtn>
      </div>
    </form>
  );
}

// ── DayView ──────────────────────────────────────────────────────────────────
function DayView({ rooms, appts, onCreateRange, onMoveBlock, onResizeBlock, onEditBlock }: {
  rooms: MeetingRoom[];
  appts: VisitorAppointment[];
  onCreateRange: (roomId: string, startSlot: number, endSlot: number) => void;
  onMoveBlock: (apptId: string, newSlot: number, newRoomId: string) => Promise<void>;
  onResizeBlock: (apptId: string, durationMin: number) => Promise<void>;
  onEditBlock: (appt: VisitorAppointment) => void;
}) {
  const gridRef    = useRef<HTMLDivElement>(null);
  const dragRef    = useRef<DragState>({ kind: "idle" });
  const hovRowRef  = useRef(0);
  const [, setTick] = useState(0);
  const reTick     = useCallback(() => setTick(t => t + 1), []);

  function clientXToSlot(clientX: number): number {
    const rect = gridRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.max(0, Math.min(TOTAL_SLOTS - 1, Math.floor((clientX - rect.left - LABEL_W) / SLOT_W)));
  }

  function startCreate(e: React.MouseEvent, rowIdx: number) {
    if (e.button !== 0) return;
    const slot = clientXToSlot(e.clientX);
    dragRef.current = { kind: "creating", roomId: rooms[rowIdx].id, rowIdx, startSlot: slot, endSlot: slot };
    reTick();
    const onMove = (ev: MouseEvent) => {
      if (dragRef.current.kind !== "creating") return;
      (dragRef.current as DragCreate).endSlot = clientXToSlot(ev.clientX);
      reTick();
    };
    const onUp = () => {
      if (dragRef.current.kind === "creating") {
        const { roomId, startSlot, endSlot } = dragRef.current as DragCreate;
        const s = Math.min(startSlot, endSlot);
        const e2 = Math.max(startSlot, endSlot) + 1;
        onCreateRange(roomId, s, e2);
      }
      dragRef.current = { kind: "idle" }; reTick();
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function startMove(e: React.MouseEvent, appt: VisitorAppointment, rowIdx: number) {
    if (e.button !== 0) return;
    const startSlot  = Math.max(0, Math.round(dateTimeToSlot(new Date(appt.scheduled_at))));
    const durSlots   = slotsForDuration(appt.duration_minutes ?? 60);
    const blockLeft  = LABEL_W + startSlot * SLOT_W;
    const slotOffset = Math.max(0, Math.floor((e.clientX - (gridRef.current?.getBoundingClientRect().left ?? 0) - blockLeft) / SLOT_W));

    dragRef.current = { kind: "moving", apptId: appt.id, origRowIdx: rowIdx, currentRowIdx: rowIdx, currentSlot: startSlot, durSlots, slotOffset };
    reTick();
    const onMove = (ev: MouseEvent) => {
      if (dragRef.current.kind !== "moving") return;
      const d = dragRef.current as DragMove;
      const rawSlot = clientXToSlot(ev.clientX) - d.slotOffset;
      d.currentSlot   = Math.max(0, Math.min(TOTAL_SLOTS - d.durSlots, rawSlot));
      d.currentRowIdx = hovRowRef.current;
      reTick();
    };
    const onUp = async () => {
      if (dragRef.current.kind === "moving") {
        const { apptId, currentSlot, currentRowIdx } = dragRef.current as DragMove;
        await onMoveBlock(apptId, currentSlot, rooms[currentRowIdx]?.id ?? appt.meeting_room_id ?? "");
      }
      dragRef.current = { kind: "idle" }; reTick();
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function startResize(e: React.MouseEvent, appt: VisitorAppointment) {
    if (e.button !== 0) return;
    e.stopPropagation();
    const origDurSlots = slotsForDuration(appt.duration_minutes ?? 60);
    const origStartX   = e.clientX;
    dragRef.current = { kind: "resizing", apptId: appt.id, origDurSlots, currentDurSlots: origDurSlots, origStartX };
    reTick();
    const onMove = (ev: MouseEvent) => {
      if (dragRef.current.kind !== "resizing") return;
      const d = dragRef.current as DragResize;
      const delta = Math.round((ev.clientX - d.origStartX) / SLOT_W);
      d.currentDurSlots = Math.max(1, d.origDurSlots + delta);
      reTick();
    };
    const onUp = async () => {
      if (dragRef.current.kind === "resizing") {
        const { apptId, currentDurSlots } = dragRef.current as DragResize;
        await onResizeBlock(apptId, slotsToMin(currentDurSlots));
      }
      dragRef.current = { kind: "idle" }; reTick();
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  const drag = dragRef.current;

  return (
    <div ref={gridRef} style={{ minWidth: LABEL_W + TOTAL_SLOTS * SLOT_W, userSelect: "none", cursor: drag.kind !== "idle" ? "grabbing" : "default" }}>
      {/* Hour header */}
      <div style={{
        display: "grid", gridTemplateColumns: `${LABEL_W}px repeat(${TOTAL_SLOTS}, ${SLOT_W}px)`,
        borderBottom: "1px solid #efece5", background: "#faf8f4",
        position: "sticky", top: 0, zIndex: 2,
      }}>
        <div style={{ padding: "7px 10px", fontSize: 9.5, color: "#a8a198", fontFamily: FONT_MONO, letterSpacing: 0.4, borderRight: "1px solid #efece5" }}>ROOM</div>
        {Array.from({ length: TOTAL_SLOTS }, (_, si) => (
          <div key={si} style={{
            padding: "7px 0 7px 3px", fontSize: 9.5, color: "#a8a198", fontFamily: FONT_MONO,
            borderLeft: si % 4 === 0 ? "1px solid #efece5" : "none",
          }}>
            {si % 4 === 0 ? `${padZ(DAY_START + si / 4)}` : ""}
          </div>
        ))}
      </div>

      {/* Room rows */}
      {rooms.map((room, ri) => {
        const roomAppts    = appts.filter(a => a.meeting_room_id === room.id);
        const isCreatingHere = drag.kind === "creating" && (drag as DragCreate).roomId === room.id;
        const isMovingHere   = drag.kind === "moving"   && (drag as DragMove).currentRowIdx === ri;
        const rc = roomColor(room);

        return (
          <div key={room.id}
            onMouseEnter={() => { hovRowRef.current = ri; }}
            style={{ display: "grid", gridTemplateColumns: `${LABEL_W}px repeat(${TOTAL_SLOTS}, ${SLOT_W}px)`, borderTop: "1px solid #efece5", position: "relative", minHeight: ROW_H }}
          >
            {/* Sticky label */}
            <div style={{ padding: "0 10px", display: "flex", alignItems: "center", gap: 7, borderRight: "1px solid #efece5", background: "#faf8f4", position: "sticky", left: 0, zIndex: 1 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: rc, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, lineHeight: 1.3 }}>{room.name}</div>
                {room.location && <div style={{ fontSize: 10, color: "#a8a198", fontFamily: FONT_JP }}>{room.location}</div>}
              </div>
            </div>

            {/* Clickable slot cells */}
            {Array.from({ length: TOTAL_SLOTS }, (_, si) => (
              <div key={si}
                onMouseDown={e => startCreate(e, ri)}
                style={{
                  borderLeft: si % 4 === 0 ? "1px solid #efece5" : "1px solid #f4f1ea",
                  cursor: drag.kind === "creating" ? "crosshair" : "crosshair",
                  minHeight: ROW_H,
                }}
              />
            ))}

            {/* Drag-create selection overlay */}
            {isCreatingHere && (() => {
              const d = drag as DragCreate;
              const s = Math.min(d.startSlot, d.endSlot);
              const e2 = Math.max(d.startSlot, d.endSlot);
              const w = (e2 - s + 1) * SLOT_W;
              return (
                <div style={{
                  position: "absolute", left: LABEL_W + s * SLOT_W, width: w,
                  top: 6, height: ROW_H - 12,
                  background: rc + "33", border: `2px solid ${rc}`, borderRadius: 6,
                  pointerEvents: "none", zIndex: 3,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {w >= 40 && <span style={{ fontSize: 10, color: rc, fontFamily: FONT_MONO, fontWeight: 700 }}>{slotToTimeStr(s)}–{slotToTimeStr(e2 + 1)}</span>}
                </div>
              );
            })()}

            {/* Drag-move ghost */}
            {isMovingHere && (() => {
              const d = drag as DragMove;
              return (
                <div style={{
                  position: "absolute", left: LABEL_W + d.currentSlot * SLOT_W, width: d.durSlots * SLOT_W - 4,
                  top: 6, height: ROW_H - 12,
                  background: rc + "44", border: `2px dashed ${rc}`, borderRadius: 6,
                  pointerEvents: "none", zIndex: 3,
                }} />
              );
            })()}

            {/* Appointment blocks */}
            {roomAppts.map(appt => {
              const startDt   = new Date(appt.scheduled_at);
              const startSlot = Math.round(dateTimeToSlot(startDt));
              if (startSlot < 0 || startSlot >= TOTAL_SLOTS) return null;
              const isMovingThis   = drag.kind === "moving"   && (drag as DragMove).apptId   === appt.id;
              const isResizingThis = drag.kind === "resizing" && (drag as DragResize).apptId === appt.id;
              const durSlots = isResizingThis
                ? (drag as DragResize).currentDurSlots
                : slotsForDuration(appt.duration_minutes ?? 60);
              const maxSlots = TOTAL_SLOTS - startSlot;
              const blockW = Math.max(SLOT_W - 4, Math.min(durSlots * SLOT_W - 4, maxSlots * SLOT_W - 4));

              return (
                <div key={appt.id}
                  onMouseDown={e => startMove(e, appt, ri)}
                  style={{
                    position: "absolute",
                    left: LABEL_W + startSlot * SLOT_W,
                    width: blockW,
                    top: 6, height: ROW_H - 12,
                    background: rc + "22",
                    borderLeft: `3px solid ${rc}`,
                    borderRadius: "0 6px 6px 0",
                    padding: "3px 14px 3px 6px",
                    cursor: isMovingThis ? "grabbing" : "grab",
                    opacity: isMovingThis ? 0.3 : 1,
                    overflow: "hidden",
                    zIndex: isMovingThis ? 0 : 2,
                    boxShadow: "0 1px 4px rgba(0,0,0,0.07)",
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#1d1a15", fontFamily: FONT_JP, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {appt.visitor_name}
                  </div>
                  {durSlots >= 2 && (
                    <div style={{ fontSize: 9.5, color: "#6b6559", fontFamily: FONT_MONO }}>
                      {padZ(startDt.getHours())}:{padZ(startDt.getMinutes())}
                      {appt.staff ? ` · ${appt.staff}` : ""}
                    </div>
                  )}
                  {/* Edit click area (pencil icon) */}
                  <div
                    onClick={e => { e.stopPropagation(); onEditBlock(appt); }}
                    style={{ position: "absolute", top: 3, right: 12, fontSize: 11, color: rc, cursor: "pointer", opacity: 0.8 }}
                    title="編集"
                  >✎</div>
                  {/* Resize handle */}
                  <div
                    onMouseDown={e => startResize(e, appt)}
                    style={{
                      position: "absolute", right: 0, top: 0, bottom: 0, width: 8,
                      cursor: "ew-resize", background: rc + "55",
                      borderRadius: "0 6px 6px 0",
                    }}
                  />
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ── WeekView ─────────────────────────────────────────────────────────────────
const DAY_LABELS_JA = ["月", "火", "水", "木", "金", "土", "日"];

function WeekView({ weekStart, rooms, appts, onCellClick, onBlockEdit, onDayBlockMove }: {
  weekStart: Date;
  rooms: MeetingRoom[];
  appts: VisitorAppointment[];
  onCellClick: (roomId: string, day: Date) => void;
  onBlockEdit: (appt: VisitorAppointment) => void;
  onDayBlockMove: (apptId: string, newDay: Date) => Promise<void>;
}) {
  const weekDays = Array.from({ length: 7 }, (_, i) => shiftDate(weekStart, i));
  const dragApptIdRef = useRef<string | null>(null);
  const today = dateToStr(new Date());

  return (
    <div style={{ minWidth: LABEL_W + 7 * WEEK_DAY_W }}>
      {/* Day header */}
      <div style={{ display: "grid", gridTemplateColumns: `${LABEL_W}px repeat(7, ${WEEK_DAY_W}px)`, borderBottom: "1px solid #efece5", background: "#faf8f4", position: "sticky", top: 0, zIndex: 2 }}>
        <div style={{ padding: "7px 10px", fontSize: 9.5, color: "#a8a198", fontFamily: FONT_MONO, borderRight: "1px solid #efece5" }}>ROOM</div>
        {weekDays.map((d, di) => {
          const isToday = dateToStr(d) === today;
          return (
            <div key={di} style={{ padding: "5px 4px", textAlign: "center", borderLeft: "1px solid #efece5" }}>
              <div style={{ fontSize: 9.5, color: "#a8a198", fontFamily: FONT_MONO }}>{DAY_LABELS_JA[di]}</div>
              <div style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 24, height: 24, borderRadius: "50%", margin: "2px auto 0",
                background: isToday ? "#4a7c4e" : "transparent",
                fontSize: 13, fontWeight: 600,
                color: isToday ? "#fff" : "#1d1a15", fontFamily: FONT_JP,
              }}>{d.getDate()}</div>
            </div>
          );
        })}
      </div>

      {/* Room rows */}
      {rooms.map((room, ri) => {
        const rc = roomColor(room);
        return (
          <div key={room.id} style={{ display: "grid", gridTemplateColumns: `${LABEL_W}px repeat(7, ${WEEK_DAY_W}px)`, borderTop: "1px solid #efece5", minHeight: 80 }}>
            <div style={{ padding: "0 10px", display: "flex", alignItems: "center", gap: 7, borderRight: "1px solid #efece5", background: "#faf8f4", position: "sticky", left: 0, zIndex: 1 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: rc, flexShrink: 0 }} />
              <div style={{ fontSize: 11.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP }}>{room.name}</div>
            </div>
            {weekDays.map((day, di) => {
              const ds = dateToStr(day);
              const isWeekend = day.getDay() === 0 || day.getDay() === 6;
              const dayAppts = appts.filter(a => a.meeting_room_id === room.id && a.scheduled_at.startsWith(ds));
              return (
                <div key={di}
                  style={{ borderLeft: "1px solid #efece5", padding: "4px 3px", minHeight: 80, background: isWeekend ? "#faf8f4" : "transparent", cursor: "pointer" }}
                  onClick={() => onCellClick(room.id, day)}
                  onDragOver={e => e.preventDefault()}
                  onDrop={async e => {
                    e.preventDefault();
                    if (!dragApptIdRef.current) return;
                    await onDayBlockMove(dragApptIdRef.current, day);
                    dragApptIdRef.current = null;
                  }}
                >
                  {dayAppts.map(appt => (
                    <div key={appt.id}
                      draggable
                      onDragStart={e => { e.stopPropagation(); dragApptIdRef.current = appt.id; }}
                      onDragEnd={() => { dragApptIdRef.current = null; }}
                      onClick={e => { e.stopPropagation(); onBlockEdit(appt); }}
                      style={{
                        padding: "2px 5px 2px 7px", marginBottom: 2,
                        background: rc + "22", borderLeft: `3px solid ${rc}`,
                        borderRadius: "0 4px 4px 0", fontSize: 10.5, fontFamily: FONT_JP,
                        cursor: "grab", overflow: "hidden",
                      }}
                    >
                      <div style={{ fontWeight: 600, color: "#1d1a15", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{appt.visitor_name}</div>
                      <div style={{ fontSize: 9.5, color: "#6b6559", fontFamily: FONT_MONO }}>
                        {padZ(new Date(appt.scheduled_at).getHours())}:{padZ(new Date(appt.scheduled_at).getMinutes())}
                        {appt.duration_minutes ? `–${(() => { const e = new Date(new Date(appt.scheduled_at).getTime() + appt.duration_minutes * 60000); return `${padZ(e.getHours())}:${padZ(e.getMinutes())}`; })()}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ── MonthView ─────────────────────────────────────────────────────────────────
function MonthView({ date, appts, rooms, onDayClick, onBlockEdit, onDayBlockMove }: {
  date: Date;
  appts: VisitorAppointment[];
  rooms: MeetingRoom[];
  onDayClick: (day: Date) => void;
  onBlockEdit: (appt: VisitorAppointment) => void;
  onDayBlockMove: (apptId: string, newDay: Date) => Promise<void>;
}) {
  const year = date.getFullYear(), month = date.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay  = new Date(year, month + 1, 0);
  const startOffset = firstDay.getDay() === 0 ? 6 : firstDay.getDay() - 1;
  const totalCells  = Math.ceil((startOffset + lastDay.getDate()) / 7) * 7;
  const cells: (Date | null)[] = Array.from({ length: totalCells }, (_, i) => {
    const n = i - startOffset + 1;
    return n >= 1 && n <= lastDay.getDate() ? new Date(year, month, n) : null;
  });
  const dragApptIdRef = useRef<string | null>(null);
  const today = dateToStr(new Date());

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", borderBottom: "1px solid #efece5", background: "#faf8f4" }}>
        {DAY_LABELS_JA.map(d => (
          <div key={d} style={{ padding: "7px 0", textAlign: "center", fontSize: 10.5, color: "#a8a198", fontFamily: FONT_MONO }}>{d}</div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)" }}>
        {cells.map((day, ci) => {
          if (!day) return (
            <div key={ci} style={{ minHeight: 90, background: "#f7f5f0", borderTop: "1px solid #efece5", borderLeft: ci % 7 !== 0 ? "1px solid #efece5" : "none" }} />
          );
          const ds = dateToStr(day);
          const isToday   = ds === today;
          const isWeekend = day.getDay() === 0 || day.getDay() === 6;
          const dayAppts  = appts.filter(a => a.scheduled_at.startsWith(ds) && a.meeting_room_id);
          return (
            <div key={ci}
              style={{ minHeight: 90, borderTop: "1px solid #efece5", borderLeft: ci % 7 !== 0 ? "1px solid #efece5" : "none", padding: "4px", background: isWeekend ? "#faf8f4" : "#fffefb", cursor: "pointer" }}
              onClick={() => onDayClick(day)}
              onDragOver={e => e.preventDefault()}
              onDrop={async e => {
                e.preventDefault();
                if (!dragApptIdRef.current) return;
                await onDayBlockMove(dragApptIdRef.current, day);
                dragApptIdRef.current = null;
              }}
            >
              <div style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 22, height: 22, borderRadius: "50%",
                background: isToday ? "#4a7c4e" : "transparent",
                fontSize: 12, fontWeight: isToday ? 700 : 400,
                color: isToday ? "#fff" : "#1d1a15", fontFamily: FONT_JP, marginBottom: 3,
              }}>{day.getDate()}</div>
              {dayAppts.slice(0, 3).map(appt => {
                const room = rooms.find(r => r.id === appt.meeting_room_id);
                const rc = roomColor(room ?? { color: null } as MeetingRoom);
                return (
                  <div key={appt.id}
                    draggable
                    onDragStart={e => { e.stopPropagation(); dragApptIdRef.current = appt.id; }}
                    onDragEnd={() => { dragApptIdRef.current = null; }}
                    onClick={e => { e.stopPropagation(); onBlockEdit(appt); }}
                    style={{ padding: "1px 5px 1px 6px", marginBottom: 1, background: rc + "22", borderLeft: `3px solid ${rc}`, borderRadius: "0 3px 3px 0", fontSize: 10, fontFamily: FONT_JP, cursor: "grab", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                  >
                    {appt.visitor_name}
                  </div>
                );
              })}
              {dayAppts.length > 3 && <div style={{ fontSize: 10, color: "#a8a198", fontFamily: FONT_JP }}>+{dayAppts.length - 3}件</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function AppointmentsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  // List state
  const [appointments, setAppointments] = useState<VisitorAppointment[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [dateFilter,   setDateFilter]   = useState<DateFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  // View mode
  const [viewMode,     setViewMode]     = useState<ViewMode>("list");
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("day");

  // Timeline data
  const [timelineDate, setTimelineDate] = useState<Date>(() => { const d = new Date(); d.setHours(0,0,0,0); return d; });
  const [timelineAppts, setTimelineAppts] = useState<VisitorAppointment[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);

  // Form
  const [showForm,   setShowForm]   = useState(false);
  const [formData,   setFormData]   = useState<AppointmentCreate>({ visitor_name: "", scheduled_at: "" });
  const [formSaving, setFormSaving] = useState(false);
  const [formError,  setFormError]  = useState<string | null>(null);

  // Settings / rooms
  const [staffList,   setStaffList]   = useState<string[]>([]);
  const [purposeList, setPurposeList] = useState<string[]>([]);
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);

  // QR
  const [qrAppt, setQrAppt] = useState<VisitorAppointment | null>(null);
  const printRef = useRef<HTMLDivElement>(null);

  // Edit / delete
  const [deletingId,    setDeletingId]    = useState<string | null>(null);
  const [editAppt,      setEditAppt]      = useState<VisitorAppointment | null>(null);
  const [editFormData,  setEditFormData]  = useState<AppointmentCreate>({ visitor_name: "", scheduled_at: "" });
  const [editSaving,    setEditSaving]    = useState(false);
  const [editError,     setEditError]     = useState<string | null>(null);

  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  // Initial load
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    loadList(token);
    api.getTenantSettings(token).then((s: TenantSettings) => {
      if (s.staff_list)   setStaffList(s.staff_list.split(",").map(v => v.trim()).filter(Boolean));
      if (s.purpose_list) setPurposeList(s.purpose_list.split(",").map(v => v.trim()).filter(Boolean));
    }).catch(() => {});
    api.listMeetingRooms(token).then(setRooms).catch(() => {});
  }, []);

  // List reload on filter change
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    loadList(token);
  }, [dateFilter, statusFilter]);

  // Timeline data reload
  useEffect(() => {
    if (viewMode !== "timeline") return;
    const token = getAccessToken();
    if (!token) return;
    const { from, to } = getTimelineRange(timelineMode, timelineDate);
    setTimelineLoading(true);
    api.listAppointments(token, { date_from: from, date_to: to })
      .then(setTimelineAppts).catch(() => {}).finally(() => setTimelineLoading(false));
  }, [viewMode, timelineMode, timelineDate]);

  function getDateRange(filter: DateFilter): { from?: string; to?: string } {
    const now = new Date();
    const fmt = (d: Date) => `${d.getFullYear()}-${padZ(d.getMonth() + 1)}-${padZ(d.getDate())}`;
    if (filter === "today") { const t = fmt(now); return { from: t, to: t }; }
    if (filter === "week")  { const s = new Date(now); s.setDate(now.getDate() - now.getDay()); return { from: fmt(s), to: fmt(now) }; }
    if (filter === "month") { return { from: fmt(new Date(now.getFullYear(), now.getMonth(), 1)), to: fmt(now) }; }
    return {};
  }

  function loadList(token: string) {
    setLoading(true);
    const { from, to } = getDateRange(dateFilter);
    api.listAppointments(token, { status: statusFilter !== "all" ? statusFilter : undefined, date_from: from, date_to: to })
      .then(data => { setAppointments(data); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  function resetForm() {
    const now = new Date();
    now.setMinutes(0, 0, 0);
    now.setHours(now.getHours() + 1);
    setFormData({ visitor_name: "", scheduled_at: `${now.getFullYear()}-${padZ(now.getMonth() + 1)}-${padZ(now.getDate())}T${padZ(now.getHours())}:00`, duration_minutes: 60 });
    setFormError(null);
  }

  // ── Timeline create from DayView drag ──
  function handleDayCreateRange(roomId: string, startSlot: number, endSlot: number) {
    const [sh, sm] = slotToHM(startSlot);
    const d = timelineDate;
    const ds = `${d.getFullYear()}-${padZ(d.getMonth() + 1)}-${padZ(d.getDate())}`;
    setFormData({ visitor_name: "", scheduled_at: `${ds}T${padZ(sh)}:${padZ(sm)}`, meeting_room_id: roomId, duration_minutes: Math.max(SLOT_MIN, slotsToMin(endSlot - startSlot)) });
    setFormError(null);
    setShowForm(true);
  }

  // ── Timeline create from WeekView cell click ──
  function handleWeekCellClick(roomId: string, day: Date) {
    const h = Math.max(DAY_START, Math.min(DAY_END - 1, new Date().getHours() + 1));
    const ds = `${day.getFullYear()}-${padZ(day.getMonth() + 1)}-${padZ(day.getDate())}`;
    setFormData({ visitor_name: "", scheduled_at: `${ds}T${padZ(h)}:00`, meeting_room_id: roomId, duration_minutes: 60 });
    setFormError(null);
    setShowForm(true);
  }

  // ── Month day click → drill into day view ──
  function handleMonthDayClick(day: Date) {
    setTimelineDate(day);
    setTimelineMode("day");
  }

  // ── DayView move ──
  async function handleDayMoveBlock(apptId: string, newSlot: number, newRoomId: string) {
    const appt = timelineAppts.find(a => a.id === apptId);
    if (!appt) return;
    const [h, m] = slotToHM(newSlot);
    const newDt = new Date(timelineDate);
    newDt.setHours(h, m, 0, 0);
    const newRoom = rooms.find(r => r.id === newRoomId) ?? null;
    const optimistic = { ...appt, scheduled_at: localDtStr(newDt), meeting_room_id: newRoomId, meeting_room: newRoom };
    patchTimeline(apptId, optimistic);
    const token = getAccessToken();
    if (!token) return;
    try {
      const updated = await api.updateAppointment(token, apptId, { scheduled_at: localDtStr(newDt), meeting_room_id: newRoomId });
      patchTimeline(apptId, updated); patchList(apptId, updated);
    } catch { patchTimeline(apptId, appt); patchList(apptId, appt); alert("移動に失敗しました"); }
  }

  // ── DayView resize ──
  async function handleDayResizeBlock(apptId: string, durationMin: number) {
    const appt = timelineAppts.find(a => a.id === apptId);
    if (!appt) return;
    const optimistic = { ...appt, duration_minutes: durationMin };
    patchTimeline(apptId, optimistic);
    const token = getAccessToken();
    if (!token) return;
    try {
      const updated = await api.updateAppointment(token, apptId, { duration_minutes: durationMin });
      patchTimeline(apptId, updated); patchList(apptId, updated);
    } catch { patchTimeline(apptId, appt); patchList(apptId, appt); alert("リサイズに失敗しました"); }
  }

  // ── Cross-day move (week / month drag-drop) ──
  async function handleDayBlockMove(apptId: string, newDay: Date) {
    const appt = timelineAppts.find(a => a.id === apptId);
    if (!appt) return;
    const orig = new Date(appt.scheduled_at);
    const newDt = new Date(newDay);
    newDt.setHours(orig.getHours(), orig.getMinutes(), 0, 0);
    const optimistic = { ...appt, scheduled_at: localDtStr(newDt) };
    patchTimeline(apptId, optimistic);
    const token = getAccessToken();
    if (!token) return;
    try {
      const updated = await api.updateAppointment(token, apptId, { scheduled_at: localDtStr(newDt) });
      patchTimeline(apptId, updated); patchList(apptId, updated);
    } catch { patchTimeline(apptId, appt); patchList(apptId, appt); alert("移動に失敗しました"); }
  }

  function patchTimeline(id: string, next: VisitorAppointment) {
    setTimelineAppts(prev => prev.map(a => a.id === id ? next : a));
  }
  function patchList(id: string, next: VisitorAppointment) {
    setAppointments(prev => prev.map(a => a.id === id ? next : a));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true); setFormError(null);
    try {
      const created = await api.createAppointment(token, formData);
      setAppointments(prev => [...prev, created].sort((a, b) => +new Date(a.scheduled_at) - +new Date(b.scheduled_at)));
      setTimelineAppts(prev => [...prev, created].sort((a, b) => +new Date(a.scheduled_at) - +new Date(b.scheduled_at)));
      setShowForm(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally { setFormSaving(false); }
  }

  function openEdit(appt: VisitorAppointment) {
    setEditFormData({
      visitor_name: appt.visitor_name, company: appt.company ?? "", purpose: appt.purpose ?? "",
      staff: appt.staff ?? "", scheduled_at: toLocalDatetimeValue(appt.scheduled_at),
      notes: appt.notes ?? "", meeting_room_id: appt.meeting_room_id ?? undefined,
      duration_minutes: appt.duration_minutes ?? 60,
    });
    setEditError(null); setEditAppt(appt);
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token || !editAppt) return;
    setEditSaving(true); setEditError(null);
    try {
      const updated = await api.updateAppointment(token, editAppt.id, editFormData);
      patchList(editAppt.id, updated); patchTimeline(editAppt.id, updated);
      setEditAppt(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally { setEditSaving(false); }
  }

  async function handleDelete(id: string) {
    if (!confirm("この来社予定を削除しますか？")) return;
    const token = getAccessToken();
    if (!token) return;
    setDeletingId(id);
    try {
      await api.deleteAppointment(token, id);
      setAppointments(prev => prev.filter(a => a.id !== id));
      setTimelineAppts(prev => prev.filter(a => a.id !== id));
    } catch (err: unknown) { alert(err instanceof Error ? err.message : "削除に失敗しました"); }
    finally { setDeletingId(null); }
  }

  function handlePrint() {
    if (!qrAppt) return;
    const content = printRef.current?.innerHTML ?? "";
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(`<html><head><title>来社予定QR</title><style>body{font-family:"Noto Sans JP",sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#fff}.card{border:1px solid #d8d3c7;border-radius:16px;padding:40px;text-align:center;max-width:360px}h2{margin:0 0 8px;font-size:22px;color:#1d1a15}p{margin:4px 0;font-size:14px;color:#6b6559}</style></head><body><div class="card">${content}</div></body></html>`);
    win.document.close(); win.print();
  }

  // ── Navigation ──
  const weekStart = getWeekStart(timelineDate);
  function navPrev() {
    if (timelineMode === "day")   setTimelineDate(d => shiftDate(d, -1));
    else if (timelineMode === "week")  setTimelineDate(d => shiftDate(d, -7));
    else setTimelineDate(d => new Date(d.getFullYear(), d.getMonth() - 1, 1));
  }
  function navNext() {
    if (timelineMode === "day")   setTimelineDate(d => shiftDate(d, 1));
    else if (timelineMode === "week")  setTimelineDate(d => shiftDate(d, 7));
    else setTimelineDate(d => new Date(d.getFullYear(), d.getMonth() + 1, 1));
  }
  function getNavLabel(): string {
    if (timelineMode === "day")  return fmtDateJP(timelineDate);
    if (timelineMode === "week") {
      const we = shiftDate(weekStart, 6);
      return `${weekStart.getMonth() + 1}/${weekStart.getDate()} – ${we.getMonth() + 1}/${we.getDate()}`;
    }
    return `${timelineDate.getFullYear()}年${timelineDate.getMonth() + 1}月`;
  }

  // ── Style helpers ──
  const segStyle = (active: boolean): React.CSSProperties => ({
    padding: "6px 14px", fontSize: 12, fontFamily: FONT_JP,
    background: active ? "#1d1a15" : "#fffefb",
    color: active ? "#fffefb" : "#6b6559",
    border: "none", cursor: "pointer", fontWeight: active ? 600 : 400,
  });
  const filterTabStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 12px", fontSize: 11.5, fontFamily: FONT_JP,
    background: active ? "#1d1a15" : "#fffefb",
    color: active ? "#fffefb" : "#6b6559",
    border: `1px solid ${active ? "#1d1a15" : "#d8d3c7"}`,
    borderRadius: 999, cursor: "pointer", fontWeight: active ? 600 : 400,
  });
  const navBtnStyle: React.CSSProperties = {
    padding: "6px 14px", fontSize: 12.5, fontFamily: FONT_JP,
    background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 8, cursor: "pointer", color: "#2d2a24",
  };

  const activeRooms = rooms.filter(r => r.is_active);
  const DATE_TABS:   { id: DateFilter;   label: string }[] = [{ id: "today", label: "今日" }, { id: "week", label: "今週" }, { id: "month", label: "今月" }, { id: "all", label: "全期間" }];
  const STATUS_TABS: { id: StatusFilter; label: string }[] = [{ id: "all", label: "全て" }, { id: "pending", label: "待機中" }, { id: "received", label: "チェックイン済" }, { id: "expired", label: "期限切れ" }];

  return (
    <AdminShell
      active="appointments"
      title="来社予定管理"
      subtitle="来訪者の予定を事前登録し、QRコードを発行します"
      breadcrumb={`${tenant} / 来社予定管理`}
      actions={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", border: "1px solid #d8d3c7", borderRadius: 8, overflow: "hidden" }}>
            <button style={segStyle(viewMode === "timeline")} onClick={() => setViewMode("timeline")}>タイムライン</button>
            <button style={{ ...segStyle(viewMode === "list"), borderLeft: "1px solid #d8d3c7" }} onClick={() => setViewMode("list")}>一覧</button>
          </div>
          <MkBtn variant="primary" size="sm" onClick={() => { resetForm(); setShowForm(true); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            予定を追加
          </MkBtn>
        </div>
      }
    >
      <div style={{ padding: isMobile ? "16px 12px" : "24px 28px" }}>

        {/* Shared create form */}
        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="来社予定を追加" />
            <AppointmentForm data={formData} onChange={setFormData} onSubmit={handleCreate}
              onCancel={() => { setShowForm(false); setFormError(null); }}
              saving={formSaving} error={formError} submitLabel="作成"
              staffList={staffList} purposeList={purposeList} rooms={rooms} />
          </MkCard>
        )}

        {viewMode === "timeline" ? (
          /* ════════════ TIMELINE ════════════ */
          <div>
            {/* Navigation row */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
              {/* Day/Week/Month mode */}
              <div style={{ display: "flex", border: "1px solid #d8d3c7", borderRadius: 8, overflow: "hidden" }}>
                {(["day", "week", "month"] as TimelineMode[]).map((m, i) => (
                  <button key={m} style={{ ...segStyle(timelineMode === m), borderLeft: i > 0 ? "1px solid #d8d3c7" : "none" }} onClick={() => setTimelineMode(m)}>
                    {{ day: "日", week: "週", month: "月" }[m]}
                  </button>
                ))}
              </div>

              <div style={{ width: 1, height: 20, background: "#d8d3c7" }} />

              {/* Date navigation */}
              <button style={navBtnStyle} onClick={navPrev}>← 前{timelineMode === "day" ? "日" : timelineMode === "week" ? "週" : "月"}</button>
              <span style={{ fontSize: 13.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, minWidth: 180, textAlign: "center" }}>
                {getNavLabel()}
              </span>
              <button style={navBtnStyle} onClick={navNext}>翌{timelineMode === "day" ? "日" : timelineMode === "week" ? "週" : "月"} →</button>
              <button style={{ ...navBtnStyle, color: "#4a7c4e", fontWeight: 600 }}
                onClick={() => { const d = new Date(); d.setHours(0,0,0,0); setTimelineDate(d); }}>
                今日
              </button>
              {timelineLoading && <span style={{ fontSize: 11.5, color: "#a8a198", fontFamily: FONT_JP }}>読み込み中...</span>}
            </div>

            {/* Timeline grid */}
            <MkCard padding="0" style={{ overflowX: "auto" }}>
              {activeRooms.length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                  会議室がありません。<a href={`/${tenant}/admin/meeting-rooms`} style={{ color: "#4a7c4e" }}>会議室管理</a>から追加してください。
                </div>
              ) : timelineMode === "day" ? (
                <DayView
                  rooms={activeRooms} appts={timelineAppts}
                  onCreateRange={handleDayCreateRange}
                  onMoveBlock={handleDayMoveBlock}
                  onResizeBlock={handleDayResizeBlock}
                  onEditBlock={openEdit}
                />
              ) : timelineMode === "week" ? (
                <WeekView
                  weekStart={weekStart} rooms={activeRooms} appts={timelineAppts}
                  onCellClick={handleWeekCellClick}
                  onBlockEdit={openEdit}
                  onDayBlockMove={handleDayBlockMove}
                />
              ) : (
                <MonthView
                  date={timelineDate} appts={timelineAppts} rooms={rooms}
                  onDayClick={handleMonthDayClick}
                  onBlockEdit={openEdit}
                  onDayBlockMove={handleDayBlockMove}
                />
              )}
            </MkCard>

            {/* Room-less appointments footnote (day mode) */}
            {timelineMode === "day" && timelineAppts.some(a => !a.meeting_room_id) && (
              <div style={{ marginTop: 10, padding: "8px 12px", background: "#faf8f4", border: "1px solid #efece5", borderRadius: 8, fontSize: 11.5, color: "#6b6559", fontFamily: FONT_JP }}>
                ※ 会議室未指定の予定 {timelineAppts.filter(a => !a.meeting_room_id).length} 件はタイムラインに表示されません。一覧モードで確認してください。
              </div>
            )}
          </div>
        ) : (
          /* ════════════ LIST ════════════ */
          <div>
            <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ display: "flex", gap: 4 }}>
                {DATE_TABS.map(t => <button key={t.id} style={filterTabStyle(dateFilter === t.id)} onClick={() => setDateFilter(t.id)}>{t.label}</button>)}
              </div>
              <div style={{ width: 1, height: 20, background: "#d8d3c7" }} />
              <div style={{ display: "flex", gap: 4 }}>
                {STATUS_TABS.map(t => <button key={t.id} style={filterTabStyle(statusFilter === t.id)} onClick={() => setStatusFilter(t.id)}>{t.label}</button>)}
              </div>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_JP }}>{appointments.length} 件</span>
            </div>

            <MkCard padding="0">
              {loading ? (
                <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>読み込み中...</div>
              ) : error ? (
                <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>{error}</div>
              ) : appointments.length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                  {dateFilter !== "all" || statusFilter !== "all" ? "条件に一致する来社予定がありません" : "来社予定がありません。「予定を追加」から登録してください。"}
                </div>
              ) : isMobile ? (
                <div>
                  {appointments.map((appt, idx) => (
                    <div key={appt.id} style={{ padding: 16, borderBottom: idx < appointments.length - 1 ? "1px solid #efece5" : "none" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                        <div>
                          <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP }}>{appt.visitor_name}</div>
                          {appt.company && <div style={{ fontSize: 12.5, color: "#6b6559", fontFamily: FONT_JP }}>{appt.company}</div>}
                        </div>
                        <StatusBadge status={appt.status} />
                      </div>
                      <div style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_MONO, marginBottom: 4 }}>{fmtDatetime(appt.scheduled_at)}</div>
                      {appt.meeting_room && (
                        <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
                          <div style={{ width: 8, height: 8, borderRadius: 2, background: appt.meeting_room.color ?? "#4a7c4e" }} />
                          <span style={{ fontSize: 12, color: "#6b6559", fontFamily: FONT_JP }}>{appt.meeting_room.name}</span>
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6 }}>
                        <MkBtn variant="default" size="sm" onClick={() => setQrAppt(appt)}>QR</MkBtn>
                        <MkBtn variant="default" size="sm" onClick={() => openEdit(appt)}>編集</MkBtn>
                        <MkBtn variant="danger" size="sm" disabled={deletingId === appt.id} onClick={() => handleDelete(appt.id)}>
                          {deletingId === appt.id ? "削除中..." : "削除"}
                        </MkBtn>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #efece5", background: "#faf8f4" }}>
                      {["来社日時", "氏名", "会社", "担当", "目的", "会議室", "時間", "ステータス", "操作"].map(h => (
                        <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 10.5, color: "#a8a198", fontWeight: 600, fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {appointments.map((appt, idx) => (
                      <tr key={appt.id} style={{ borderBottom: idx < appointments.length - 1 ? "1px solid #efece5" : "none" }}>
                        <td style={{ padding: "10px 12px", fontSize: 12.5, color: "#1d1a15", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>{fmtDatetime(appt.scheduled_at)}</td>
                        <td style={{ padding: "10px 12px", fontSize: 13, fontWeight: 500, color: "#1d1a15", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>{appt.visitor_name}</td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{appt.company ?? "—"}</td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>{appt.staff ?? "—"}</td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>{appt.purpose ?? "—"}</td>
                        <td style={{ padding: "10px 12px" }}>
                          {appt.meeting_room ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <div style={{ width: 8, height: 8, borderRadius: 2, background: appt.meeting_room.color ?? "#4a7c4e" }} />
                              <span style={{ fontSize: 12.5, color: "#2d2a24", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>{appt.meeting_room.name}</span>
                            </div>
                          ) : <span style={{ fontSize: 12.5, color: "#d8d3c7" }}>—</span>}
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 12, color: "#a8a198", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                          {appt.duration_minutes ? `${appt.duration_minutes}分` : "—"}
                        </td>
                        <td style={{ padding: "10px 12px" }}><StatusBadge status={appt.status} /></td>
                        <td style={{ padding: "10px 12px" }}>
                          <div style={{ display: "flex", gap: 5 }}>
                            <MkBtn variant="default" size="sm" onClick={() => setQrAppt(appt)}>QR</MkBtn>
                            <MkBtn variant="default" size="sm" onClick={() => openEdit(appt)}>編集</MkBtn>
                            <MkBtn variant="danger" size="sm" disabled={deletingId === appt.id} onClick={() => handleDelete(appt.id)}>
                              {deletingId === appt.id ? "削除中..." : "削除"}
                            </MkBtn>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </MkCard>
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editAppt && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: isMobile ? 16 : 0 }}
          onClick={() => setEditAppt(null)}>
          <div style={{ background: "#fffefb", borderRadius: 20, padding: isMobile ? "24px 20px" : "32px 36px", maxWidth: 580, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)", maxHeight: "90vh", overflowY: "auto" }}
            onClick={e => e.stopPropagation()}>
            <MkSectionTitle title="来社予定を編集" style={{ marginBottom: 20 }} />
            <AppointmentForm data={editFormData} onChange={setEditFormData} onSubmit={handleUpdate}
              onCancel={() => setEditAppt(null)}
              saving={editSaving} error={editError} submitLabel="保存"
              staffList={staffList} purposeList={purposeList} rooms={rooms} />
          </div>
        </div>
      )}

      {/* QR modal */}
      {qrAppt && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: isMobile ? 16 : 0 }}
          onClick={() => setQrAppt(null)}>
          <div style={{ background: "#fffefb", borderRadius: 20, padding: isMobile ? "28px 24px" : "40px 48px", maxWidth: 480, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
            onClick={e => e.stopPropagation()}>
            <div ref={printRef} style={{ textAlign: "center" }}>
              <div style={{ marginBottom: 20 }}>
                <QRCodeSVG value={`appt:${qrAppt.token}`} size={isMobile ? 160 : 200} level="M"
                  style={{ border: "1px solid #efece5", borderRadius: 8, padding: 8, background: "#fff" }} />
              </div>
              <h2 style={{ margin: "0 0 6px", fontSize: 20, fontWeight: 700, color: "#1d1a15", fontFamily: FONT_JP }}>{qrAppt.visitor_name} 様</h2>
              {qrAppt.company && <p style={{ margin: "0 0 4px", fontSize: 14, color: "#6b6559", fontFamily: FONT_JP }}>{qrAppt.company}</p>}
              <p style={{ margin: "0 0 4px", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>来社日時：{fmtDatetime(qrAppt.scheduled_at)}</p>
              {qrAppt.staff && <p style={{ margin: "0 0 4px", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>担当：{qrAppt.staff}</p>}
              {qrAppt.meeting_room && (
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: "8px 0 0", padding: "5px 12px", background: "#f4f1ea", borderRadius: 999, border: "1px solid #efece5" }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: qrAppt.meeting_room.color ?? "#4a7c4e" }} />
                  <span style={{ fontSize: 12.5, color: "#2d2a24", fontFamily: FONT_JP, fontWeight: 500 }}>
                    {qrAppt.meeting_room.name}{qrAppt.meeting_room.location ? ` · ${qrAppt.meeting_room.location}` : ""}
                  </span>
                </div>
              )}
              <p style={{ margin: "16px 0 0", fontSize: 11, color: "#c8c3b8", fontFamily: FONT_MONO, wordBreak: "break-all" }}>予約コード: {qrAppt.token}</p>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 28, justifyContent: "center" }}>
              <MkBtn variant="primary" size="sm" onClick={handlePrint}>印刷</MkBtn>
              <MkBtn variant="default" size="sm" onClick={() => setQrAppt(null)}>閉じる</MkBtn>
            </div>
          </div>
        </div>
      )}
    </AdminShell>
  );
}
