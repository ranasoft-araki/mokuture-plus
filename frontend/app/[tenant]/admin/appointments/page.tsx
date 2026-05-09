"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, type AppointmentCreate, type MeetingRoom, type TenantSettings, type VisitorAppointment } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

const INPUT_STYLE: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #d8d3c7", borderRadius: 7,
  fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box",
  outline: "none",
};

type DateFilter = "today" | "week" | "month" | "all";
type StatusFilter = "all" | "pending" | "received" | "expired";
type ViewMode = "timeline" | "list";

// Timeline grid constants
const HOURS = Array.from({ length: 13 }, (_, i) => i + 8); // 08–20
const SLOT_W = 80;
const LABEL_W = 148;
const ROW_H = 68;

function StatusBadge({ status }: { status: string }) {
  if (status === "received") return <MkPill tone="live">チェックイン済</MkPill>;
  if (status === "expired") return <MkPill tone="off">期限切れ</MkPill>;
  return <MkPill tone="info">待機中</MkPill>;
}

function fmtDatetime(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function toLocalDatetimeValue(iso: string) {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDateJP(d: Date) {
  const DAYS = ["日", "月", "火", "水", "木", "金", "土"];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 (${DAYS[d.getDay()]})`;
}

function shiftDate(d: Date, days: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + days);
  return r;
}

function getDateRange(filter: DateFilter): { from: string | undefined; to: string | undefined } {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  if (filter === "today") {
    const t = fmt(now);
    return { from: t, to: t };
  }
  if (filter === "week") {
    const start = new Date(now);
    start.setDate(now.getDate() - now.getDay());
    return { from: fmt(start), to: fmt(now) };
  }
  if (filter === "month") {
    const start = new Date(now.getFullYear(), now.getMonth(), 1);
    return { from: fmt(start), to: fmt(now) };
  }
  return { from: undefined, to: undefined };
}

function AppointmentForm({
  data,
  onChange,
  onSubmit,
  onCancel,
  saving,
  error,
  submitLabel,
  staffList,
  purposeList,
  rooms,
}: {
  data: AppointmentCreate;
  onChange: (d: AppointmentCreate) => void;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
  submitLabel: string;
  staffList: string[];
  purposeList: string[];
  rooms: MeetingRoom[];
}) {
  return (
    <form onSubmit={onSubmit}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
            氏名 <span style={{ color: "#a84238" }}>*</span>
          </label>
          <input type="text" required value={data.visitor_name}
            onChange={(e) => onChange({ ...data, visitor_name: e.target.value })}
            style={INPUT_STYLE} placeholder="例：佐々木 美咲" />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>会社名</label>
          <input type="text" value={data.company ?? ""}
            onChange={(e) => onChange({ ...data, company: e.target.value })}
            style={INPUT_STYLE} placeholder="例：アルチザン株式会社" />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>目的</label>
          {purposeList.length > 0 ? (
            <select value={data.purpose ?? ""} onChange={(e) => onChange({ ...data, purpose: e.target.value })} style={INPUT_STYLE}>
              <option value="">未選択</option>
              {purposeList.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input type="text" value={data.purpose ?? ""}
              onChange={(e) => onChange({ ...data, purpose: e.target.value })}
              style={INPUT_STYLE} placeholder="例：打ち合わせ" />
          )}
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>担当者</label>
          {staffList.length > 0 ? (
            <select value={data.staff ?? ""} onChange={(e) => onChange({ ...data, staff: e.target.value })} style={INPUT_STYLE}>
              <option value="">未選択</option>
              {staffList.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input type="text" value={data.staff ?? ""}
              onChange={(e) => onChange({ ...data, staff: e.target.value })}
              style={INPUT_STYLE} placeholder="例：田中" />
          )}
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
            来社日時 <span style={{ color: "#a84238" }}>*</span>
          </label>
          <input type="datetime-local" required value={data.scheduled_at}
            onChange={(e) => onChange({ ...data, scheduled_at: e.target.value })}
            style={INPUT_STYLE} />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>会議室</label>
          <select
            value={data.meeting_room_id ?? ""}
            onChange={(e) => onChange({ ...data, meeting_room_id: e.target.value || undefined })}
            style={INPUT_STYLE}
          >
            <option value="">未指定</option>
            {rooms.filter((r) => r.is_active).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}{r.location ? ` (${r.location})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>メモ</label>
          <input type="text" value={data.notes ?? ""}
            onChange={(e) => onChange({ ...data, notes: e.target.value })}
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

export default function AppointmentsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [appointments, setAppointments] = useState<VisitorAppointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [viewMode, setViewMode] = useState<ViewMode>("list");

  // Timeline state
  const [timelineDate, setTimelineDate] = useState<Date>(() => {
    const d = new Date(); d.setHours(0, 0, 0, 0); return d;
  });
  const [timelineAppts, setTimelineAppts] = useState<VisitorAppointment[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [hoveredCell, setHoveredCell] = useState<{ roomId: string; hour: number } | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<AppointmentCreate>({ visitor_name: "", scheduled_at: "" });
  const [formSaving, setFormSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [staffList, setStaffList] = useState<string[]>([]);
  const [purposeList, setPurposeList] = useState<string[]>([]);
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);

  const [qrAppt, setQrAppt] = useState<VisitorAppointment | null>(null);
  const printRef = useRef<HTMLDivElement>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [editAppt, setEditAppt] = useState<VisitorAppointment | null>(null);
  const [editFormData, setEditFormData] = useState<AppointmentCreate>({ visitor_name: "", scheduled_at: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    load(token);
    api.getTenantSettings(token).then((s: TenantSettings) => {
      if (s.staff_list) setStaffList(s.staff_list.split(",").map((v) => v.trim()).filter(Boolean));
      if (s.purpose_list) setPurposeList(s.purpose_list.split(",").map((v) => v.trim()).filter(Boolean));
    }).catch(() => {});
    api.listMeetingRooms(token).then(setRooms).catch(() => {});
  }, []);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    load(token);
  }, [dateFilter, statusFilter]);

  // Load timeline data when in timeline mode or date changes
  useEffect(() => {
    if (viewMode !== "timeline") return;
    const token = getAccessToken();
    if (!token) return;
    const pad = (n: number) => String(n).padStart(2, "0");
    const dateStr = `${timelineDate.getFullYear()}-${pad(timelineDate.getMonth() + 1)}-${pad(timelineDate.getDate())}`;
    setTimelineLoading(true);
    api.listAppointments(token, { date_from: dateStr, date_to: dateStr })
      .then(setTimelineAppts)
      .catch(() => {})
      .finally(() => setTimelineLoading(false));
  }, [viewMode, timelineDate]);

  function load(token: string) {
    setLoading(true);
    const { from, to } = getDateRange(dateFilter);
    api.listAppointments(token, {
      status: statusFilter !== "all" ? statusFilter : undefined,
      date_from: from,
      date_to: to,
    })
      .then((data) => { setAppointments(data); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  function resetForm() {
    const now = new Date();
    now.setMinutes(0, 0, 0);
    now.setHours(now.getHours() + 1);
    const pad = (n: number) => String(n).padStart(2, "0");
    const defaultDt = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:00`;
    setFormData({ visitor_name: "", scheduled_at: defaultDt });
    setFormError(null);
  }

  function handleCellClick(roomId: string, hour: number) {
    const pad = (n: number) => String(n).padStart(2, "0");
    const d = timelineDate;
    const dateStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    setFormData({
      visitor_name: "",
      scheduled_at: `${dateStr}T${pad(hour)}:00`,
      meeting_room_id: roomId,
    });
    setFormError(null);
    setShowForm(true);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true); setFormError(null);
    try {
      const created = await api.createAppointment(token, {
        ...formData,
        scheduled_at: new Date(formData.scheduled_at).toISOString(),
      });
      setAppointments((prev) => [created, ...prev].sort(
        (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
      ));
      // Also update timeline view if active
      if (viewMode === "timeline") {
        setTimelineAppts((prev) => [...prev, created].sort(
          (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
        ));
      }
      setShowForm(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally {
      setFormSaving(false);
    }
  }

  function openEdit(appt: VisitorAppointment) {
    setEditFormData({
      visitor_name: appt.visitor_name,
      company: appt.company ?? "",
      purpose: appt.purpose ?? "",
      staff: appt.staff ?? "",
      scheduled_at: toLocalDatetimeValue(appt.scheduled_at),
      notes: appt.notes ?? "",
      meeting_room_id: appt.meeting_room_id ?? undefined,
    });
    setEditError(null);
    setEditAppt(appt);
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token || !editAppt) return;
    setEditSaving(true); setEditError(null);
    try {
      const updated = await api.updateAppointment(token, editAppt.id, {
        ...editFormData,
        scheduled_at: new Date(editFormData.scheduled_at).toISOString(),
      });
      setAppointments((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)).sort(
          (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
        )
      );
      setTimelineAppts((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)).sort(
          (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
        )
      );
      setEditAppt(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setEditSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("この来社予定を削除しますか？")) return;
    const token = getAccessToken();
    if (!token) return;
    setDeletingId(id);
    try {
      await api.deleteAppointment(token, id);
      setAppointments((prev) => prev.filter((a) => a.id !== id));
      setTimelineAppts((prev) => prev.filter((a) => a.id !== id));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "削除に失敗しました");
    } finally {
      setDeletingId(null);
    }
  }

  function handlePrint() {
    if (!qrAppt) return;
    const printContent = printRef.current?.innerHTML ?? "";
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(`
      <html><head><title>来社予定QR</title>
      <style>
        body { font-family: "Noto Sans JP", sans-serif; display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; background:#fff; }
        .card { border:1px solid #d8d3c7; border-radius:16px; padding:40px; text-align:center; max-width:360px; }
        h2 { margin:0 0 8px; font-size:22px; color:#1d1a15; }
        p { margin:4px 0; font-size:14px; color:#6b6559; }
        .code { font-family:monospace; font-size:11px; color:#a8a198; margin-top:16px; word-break:break-all; }
      </style></head>
      <body><div class="card">${printContent}</div></body></html>
    `);
    win.document.close();
    win.print();
  }

  const DATE_TABS: { id: DateFilter; label: string }[] = [
    { id: "today", label: "今日" },
    { id: "week", label: "今週" },
    { id: "month", label: "今月" },
    { id: "all", label: "全期間" },
  ];

  const STATUS_TABS: { id: StatusFilter; label: string }[] = [
    { id: "all", label: "全て" },
    { id: "pending", label: "待機中" },
    { id: "received", label: "チェックイン済" },
    { id: "expired", label: "期限切れ" },
  ];

  const FilterTabStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 12px", fontSize: 11.5, fontFamily: FONT_JP,
    background: active ? "#1d1a15" : "#fffefb",
    color: active ? "#fffefb" : "#6b6559",
    border: `1px solid ${active ? "#1d1a15" : "#d8d3c7"}`,
    borderRadius: 999, cursor: "pointer", fontWeight: active ? 600 : 400,
    transition: "all 0.1s",
  });

  const segStyle = (active: boolean): React.CSSProperties => ({
    padding: "6px 14px", fontSize: 12, fontFamily: FONT_JP,
    background: active ? "#1d1a15" : "#fffefb",
    color: active ? "#fffefb" : "#6b6559",
    border: "none", cursor: "pointer", fontWeight: active ? 600 : 400,
    transition: "all 0.1s",
  });

  const activeRooms = rooms.filter((r) => r.is_active);

  return (
    <AdminShell
      active="appointments"
      title="来社予定管理"
      subtitle="来訪者の予定を事前登録し、QRコードを発行します"
      breadcrumb={`${tenant} / 来社予定管理`}
      actions={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* View mode segment */}
          <div style={{ display: "flex", border: "1px solid #d8d3c7", borderRadius: 8, overflow: "hidden" }}>
            <button style={segStyle(viewMode === "timeline")} onClick={() => setViewMode("timeline")}>
              タイムライン
            </button>
            <button style={{ ...segStyle(viewMode === "list"), borderLeft: "1px solid #d8d3c7" }} onClick={() => setViewMode("list")}>
              一覧
            </button>
          </div>
          {/* Add appointment button (always visible) */}
          <MkBtn variant="primary" size="sm" onClick={() => { resetForm(); setShowForm(true); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            予定を追加
          </MkBtn>
        </div>
      }
    >
      <div style={{ padding: isMobile ? "16px 12px" : "24px 28px" }}>

        {/* New appointment form (shared between modes) */}
        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="来社予定を追加" />
            <AppointmentForm
              data={formData} onChange={setFormData}
              onSubmit={handleCreate}
              onCancel={() => { setShowForm(false); setFormError(null); }}
              saving={formSaving} error={formError}
              submitLabel="作成"
              staffList={staffList} purposeList={purposeList} rooms={rooms}
            />
          </MkCard>
        )}

        {viewMode === "timeline" ? (
          /* ── TIMELINE MODE ── */
          <div>
            {/* Date navigation */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
              <button
                style={{ padding: "6px 14px", fontSize: 12.5, fontFamily: FONT_JP, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 8, cursor: "pointer", color: "#2d2a24" }}
                onClick={() => setTimelineDate((d) => shiftDate(d, -1))}
              >
                ← 前日
              </button>
              <span style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, minWidth: 220, textAlign: "center" }}>
                {fmtDateJP(timelineDate)}
              </span>
              <button
                style={{ padding: "6px 14px", fontSize: 12.5, fontFamily: FONT_JP, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 8, cursor: "pointer", color: "#2d2a24" }}
                onClick={() => setTimelineDate((d) => shiftDate(d, 1))}
              >
                翌日 →
              </button>
              <button
                style={{ padding: "6px 14px", fontSize: 12.5, fontFamily: FONT_JP, background: "#f4f1ea", border: "1px solid #d8d3c7", borderRadius: 8, cursor: "pointer", color: "#4a7c4e", fontWeight: 600 }}
                onClick={() => { const d = new Date(); d.setHours(0,0,0,0); setTimelineDate(d); }}
              >
                今日
              </button>
              {timelineLoading && (
                <span style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_JP }}>読み込み中...</span>
              )}
            </div>

            {/* Timeline grid */}
            <MkCard padding="0" style={{ overflowX: "auto" }}>
              {activeRooms.length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                  会議室がありません。<a href={`/${tenant}/admin/meeting-rooms`} style={{ color: "#4a7c4e" }}>会議室管理</a>から追加してください。
                </div>
              ) : (
                <div style={{ minWidth: LABEL_W + HOURS.length * SLOT_W }}>
                  {/* Header: hour labels */}
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: `${LABEL_W}px repeat(${HOURS.length}, ${SLOT_W}px)`,
                    borderBottom: "1px solid #efece5",
                    background: "#faf8f4",
                    position: "sticky",
                    top: 0,
                    zIndex: 2,
                  }}>
                    <div style={{ padding: "8px 12px", fontSize: 10, color: "#a8a198", fontFamily: FONT_MONO, letterSpacing: "0.4px", borderRight: "1px solid #efece5" }}>
                      ROOM
                    </div>
                    {HOURS.map((h) => (
                      <div key={h} style={{
                        padding: "8px 0",
                        fontSize: 10.5,
                        color: "#a8a198",
                        fontFamily: FONT_MONO,
                        textAlign: "center",
                        borderLeft: "1px solid #efece5",
                      }}>
                        {String(h).padStart(2, "0")}:00
                      </div>
                    ))}
                  </div>

                  {/* Room rows */}
                  {activeRooms.map((room, ri) => (
                    <div
                      key={room.id}
                      style={{
                        display: "grid",
                        gridTemplateColumns: `${LABEL_W}px repeat(${HOURS.length}, ${SLOT_W}px)`,
                        borderTop: ri > 0 ? "1px solid #efece5" : "none",
                        position: "relative",
                        minHeight: ROW_H,
                      }}
                    >
                      {/* Room label */}
                      <div style={{
                        padding: "0 12px",
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        borderRight: "1px solid #efece5",
                        background: "#faf8f4",
                        position: "sticky",
                        left: 0,
                        zIndex: 1,
                      }}>
                        <div style={{ width: 8, height: 8, borderRadius: 2, background: room.color ?? "#4a7c4e", flexShrink: 0 }} />
                        <div>
                          <div style={{ fontSize: 12.5, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, lineHeight: 1.3 }}>
                            {room.name}
                          </div>
                          {room.location && (
                            <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: FONT_JP }}>
                              {room.location}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Clickable hour cells */}
                      {HOURS.map((h) => (
                        <div
                          key={h}
                          onClick={() => handleCellClick(room.id, h)}
                          onMouseEnter={() => setHoveredCell({ roomId: room.id, hour: h })}
                          onMouseLeave={() => setHoveredCell(null)}
                          style={{
                            borderLeft: "1px solid #efece5",
                            cursor: "pointer",
                            background: hoveredCell?.roomId === room.id && hoveredCell?.hour === h
                              ? "#f4f1ea"
                              : "transparent",
                            transition: "background 0.1s",
                            minHeight: ROW_H,
                          }}
                        />
                      ))}

                      {/* Appointment blocks (absolute overlay) */}
                      {timelineAppts
                        .filter((a) => a.meeting_room_id === room.id)
                        .map((appt) => {
                          const start = new Date(appt.scheduled_at);
                          const startH = start.getHours() + start.getMinutes() / 60;
                          if (startH < 8 || startH >= 21) return null;
                          const left = LABEL_W + (startH - 8) * SLOT_W + 2;
                          const roomColor = room.color ?? "#4a7c4e";
                          return (
                            <div
                              key={appt.id}
                              onClick={(e) => { e.stopPropagation(); openEdit(appt); }}
                              style={{
                                position: "absolute",
                                left,
                                top: 6,
                                width: SLOT_W - 6,
                                height: ROW_H - 12,
                                background: roomColor + "22",
                                borderLeft: `3px solid ${roomColor}`,
                                borderRadius: "0 6px 6px 0",
                                padding: "4px 7px",
                                cursor: "pointer",
                                overflow: "hidden",
                                zIndex: 1,
                                boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
                              }}
                            >
                              <div style={{ fontSize: 11.5, fontWeight: 700, color: "#1d1a15", fontFamily: FONT_JP, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                {appt.visitor_name}
                              </div>
                              <div style={{ fontSize: 10, color: "#6b6559", fontFamily: FONT_MONO, marginTop: 1 }}>
                                {String(start.getHours()).padStart(2, "0")}:{String(start.getMinutes()).padStart(2, "0")}
                              </div>
                              {appt.staff && (
                                <div style={{ fontSize: 10, color: "#a8a198", fontFamily: FONT_JP, marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {appt.staff}
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  ))}
                </div>
              )}
            </MkCard>

            {/* Room-less appointments note */}
            {timelineAppts.some((a) => !a.meeting_room_id) && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "#faf8f4", border: "1px solid #efece5", borderRadius: 10, fontSize: 12, color: "#6b6559", fontFamily: FONT_JP }}>
                ※ 会議室未指定の予定 {timelineAppts.filter((a) => !a.meeting_room_id).length} 件はタイムラインに表示されません。一覧モードで確認してください。
              </div>
            )}
          </div>
        ) : (
          /* ── LIST MODE ── */
          <div>
            {/* Filter row */}
            <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ display: "flex", gap: 4 }}>
                {DATE_TABS.map((t) => (
                  <button key={t.id} style={FilterTabStyle(dateFilter === t.id)} onClick={() => setDateFilter(t.id)}>
                    {t.label}
                  </button>
                ))}
              </div>

              <div style={{ width: 1, height: 20, background: "#d8d3c7" }} />

              <div style={{ display: "flex", gap: 4 }}>
                {STATUS_TABS.map((t) => (
                  <button key={t.id} style={FilterTabStyle(statusFilter === t.id)} onClick={() => setStatusFilter(t.id)}>
                    {t.label}
                  </button>
                ))}
              </div>

              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_JP }}>
                {appointments.length} 件
              </span>
            </div>

            {/* List / table */}
            <MkCard padding="0">
              {loading ? (
                <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>読み込み中...</div>
              ) : error ? (
                <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>{error}</div>
              ) : appointments.length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                  {dateFilter !== "all" || statusFilter !== "all"
                    ? "条件に一致する来社予定がありません"
                    : "来社予定がありません。「予定を追加」から登録してください。"}
                </div>
              ) : isMobile ? (
                /* Mobile: card layout */
                <div>
                  {appointments.map((appt, idx) => (
                    <div key={appt.id} style={{ padding: "16px", borderBottom: idx < appointments.length - 1 ? "1px solid #efece5" : "none" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6, gap: 8 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP }}>{appt.visitor_name}</div>
                          {appt.company && <div style={{ fontSize: 12.5, color: "#6b6559", fontFamily: FONT_JP, marginTop: 1 }}>{appt.company}</div>}
                        </div>
                        <StatusBadge status={appt.status} />
                      </div>
                      <div style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_MONO, marginBottom: 4 }}>
                        {fmtDatetime(appt.scheduled_at)}
                      </div>
                      {(appt.staff || appt.purpose) && (
                        <div style={{ fontSize: 12.5, color: "#6b6559", fontFamily: FONT_JP, marginBottom: 4 }}>
                          {[appt.staff, appt.purpose].filter(Boolean).join(" / ")}
                        </div>
                      )}
                      {appt.meeting_room && (
                        <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 8 }}>
                          <div style={{ width: 8, height: 8, borderRadius: 2, background: appt.meeting_room.color ?? "#4a7c4e", flexShrink: 0 }} />
                          <span style={{ fontSize: 12, color: "#6b6559", fontFamily: FONT_JP }}>{appt.meeting_room.name}</span>
                        </div>
                      )}
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <MkBtn variant="default" size="sm" onClick={() => setQrAppt(appt)}>QR表示</MkBtn>
                        <MkBtn variant="default" size="sm" onClick={() => openEdit(appt)}>編集</MkBtn>
                        <MkBtn variant="danger" size="sm" disabled={deletingId === appt.id} onClick={() => handleDelete(appt.id)}>
                          {deletingId === appt.id ? "削除中..." : "削除"}
                        </MkBtn>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                /* Desktop: table layout */
                <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "auto" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #efece5", background: "#faf8f4" }}>
                      {["来社日時", "氏名", "会社", "担当", "目的", "会議室", "ステータス", "操作"].map((h) => (
                        <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 10.5, color: "#a8a198", fontWeight: 600, letterSpacing: "0.4px", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {appointments.map((appt, idx) => (
                      <tr key={appt.id} style={{ borderBottom: idx < appointments.length - 1 ? "1px solid #efece5" : "none" }}>
                        <td style={{ padding: "10px 12px", fontSize: 12.5, color: "#1d1a15", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                          {fmtDatetime(appt.scheduled_at)}
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#1d1a15", fontFamily: FONT_JP, fontWeight: 500, whiteSpace: "nowrap" }}>
                          {appt.visitor_name}
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {appt.company ?? "—"}
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                          {appt.staff ?? "—"}
                        </td>
                        <td style={{ padding: "10px 12px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                          {appt.purpose ?? "—"}
                        </td>
                        <td style={{ padding: "10px 12px" }}>
                          {appt.meeting_room ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <div style={{ width: 8, height: 8, borderRadius: 2, background: appt.meeting_room.color ?? "#4a7c4e", flexShrink: 0 }} />
                              <span style={{ fontSize: 12.5, color: "#2d2a24", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                                {appt.meeting_room.name}
                              </span>
                            </div>
                          ) : (
                            <span style={{ fontSize: 12.5, color: "#d8d3c7", fontFamily: FONT_JP }}>—</span>
                          )}
                        </td>
                        <td style={{ padding: "10px 12px" }}>
                          <StatusBadge status={appt.status} />
                        </td>
                        <td style={{ padding: "10px 12px" }}>
                          <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
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
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: isMobile ? "16px" : 0 }}
          onClick={() => setEditAppt(null)}
        >
          <div
            style={{ background: "#fffefb", borderRadius: 20, padding: isMobile ? "24px 20px" : "32px 36px", maxWidth: 560, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)", maxHeight: "90vh", overflowY: "auto" }}
            onClick={(e) => e.stopPropagation()}
          >
            <MkSectionTitle title="来社予定を編集" style={{ marginBottom: 20 }} />
            <AppointmentForm
              data={editFormData} onChange={setEditFormData}
              onSubmit={handleUpdate}
              onCancel={() => setEditAppt(null)}
              saving={editSaving} error={editError}
              submitLabel="保存"
              staffList={staffList} purposeList={purposeList} rooms={rooms}
            />
          </div>
        </div>
      )}

      {/* QR modal */}
      {qrAppt && (
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: isMobile ? "16px" : 0 }}
          onClick={() => setQrAppt(null)}
        >
          <div
            style={{ background: "#fffefb", borderRadius: 20, padding: isMobile ? "28px 24px" : "40px 48px", maxWidth: 480, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div ref={printRef} style={{ textAlign: "center" }}>
              <div style={{ marginBottom: 20 }}>
                <QRCodeSVG
                  value={`appt:${qrAppt.token}`}
                  size={isMobile ? 160 : 200}
                  level="M"
                  style={{ border: "1px solid #efece5", borderRadius: 8, padding: 8, background: "#fff" }}
                />
              </div>
              <h2 style={{ margin: "0 0 6px", fontSize: 20, fontWeight: 700, color: "#1d1a15", fontFamily: FONT_JP }}>
                {qrAppt.visitor_name} 様
              </h2>
              {qrAppt.company && (
                <p style={{ margin: "0 0 4px", fontSize: 14, color: "#6b6559", fontFamily: FONT_JP }}>{qrAppt.company}</p>
              )}
              <p style={{ margin: "0 0 4px", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                来社日時：{fmtDatetime(qrAppt.scheduled_at)}
              </p>
              {qrAppt.staff && (
                <p style={{ margin: "0 0 4px", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
                  担当：{qrAppt.staff}
                </p>
              )}
              {qrAppt.meeting_room && (
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: "8px 0 0", padding: "5px 12px", background: "#f4f1ea", borderRadius: 999, border: "1px solid #efece5" }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: qrAppt.meeting_room.color ?? "#4a7c4e" }} />
                  <span style={{ fontSize: 12.5, color: "#2d2a24", fontFamily: FONT_JP, fontWeight: 500 }}>
                    {qrAppt.meeting_room.name}
                    {qrAppt.meeting_room.location ? ` · ${qrAppt.meeting_room.location}` : ""}
                  </span>
                </div>
              )}
              <p style={{ margin: "16px 0 0", fontSize: 11, color: "#c8c3b8", fontFamily: FONT_MONO, wordBreak: "break-all" }}>
                予約コード: {qrAppt.token}
              </p>
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
