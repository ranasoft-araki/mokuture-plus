"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, type MeetingRoom, type MeetingRoomCreate } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

const PRESET_COLORS = [
  "#4a7c4e", "#2e6b8e", "#b8763a", "#a84238", "#7c4a7c",
  "#4a6b7c", "#6b7c4a", "#7c6b4a", "#1d1a15", "#4a4a7c",
];

const INPUT_STYLE: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #d8d3c7", borderRadius: 7,
  fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box",
  outline: "none",
};

function RoomForm({
  initial,
  onSubmit,
  onCancel,
  saving,
  error,
  submitLabel,
}: {
  initial: MeetingRoomCreate & { is_active?: boolean };
  onSubmit: (data: MeetingRoomCreate & { is_active?: boolean }) => void;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
  submitLabel: string;
}) {
  const [data, setData] = useState(initial);

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSubmit(data); }}
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ gridColumn: "span 2" }}>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
            会議室名 <span style={{ color: "#a84238" }}>*</span>
          </label>
          <input
            type="text" required value={data.name}
            onChange={(e) => setData({ ...data, name: e.target.value })}
            placeholder="例：商談ルーム A" style={INPUT_STYLE}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>場所・フロア</label>
          <input
            type="text" value={data.location ?? ""}
            onChange={(e) => setData({ ...data, location: e.target.value })}
            placeholder="例：2階" style={INPUT_STYLE}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>定員（名）</label>
          <input
            type="number" min={1} max={999} value={data.capacity ?? ""}
            onChange={(e) => setData({ ...data, capacity: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="例：6" style={INPUT_STYLE}
          />
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>カラー（カレンダー表示色）</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {PRESET_COLORS.map((c) => (
              <button
                key={c} type="button"
                onClick={() => setData({ ...data, color: c })}
                style={{
                  width: 28, height: 28, borderRadius: 7, background: c, cursor: "pointer",
                  border: data.color === c ? "2.5px solid #1d1a15" : "2px solid transparent",
                  boxShadow: data.color === c ? `0 0 0 1.5px ${c}` : "none",
                  outline: "none",
                }}
              />
            ))}
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="color" value={data.color ?? "#4a7c4e"}
                onChange={(e) => setData({ ...data, color: e.target.value })}
                style={{ width: 28, height: 28, borderRadius: 7, border: "1px solid #d8d3c7", cursor: "pointer", padding: 1 }}
              />
              <span style={{ fontSize: 11, color: "#a8a198", fontFamily: FONT_MONO }}>{data.color ?? "未設定"}</span>
            </div>
          </div>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>説明・備考</label>
          <textarea
            value={data.description ?? ""}
            onChange={(e) => setData({ ...data, description: e.target.value })}
            placeholder="プロジェクター有、ホワイトボード有など"
            rows={2}
            style={{ ...INPUT_STYLE, resize: "vertical", height: 60, lineHeight: 1.5 }}
          />
        </div>
      </div>

      {error && (
        <div style={{ fontSize: 12.5, color: "#a84238", fontFamily: FONT_JP }}>{error}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <MkBtn type="submit" variant="primary" size="sm" disabled={saving}>
          {saving ? "保存中..." : submitLabel}
        </MkBtn>
        <MkBtn variant="default" size="sm" onClick={onCancel}>キャンセル</MkBtn>
      </div>
    </form>
  );
}

function RoomCard({
  room,
  onEdit,
  onDelete,
  onToggle,
  deleting,
  toggling,
}: {
  room: MeetingRoom;
  onEdit: (room: MeetingRoom) => void;
  onDelete: (id: string) => void;
  onToggle: (id: string, active: boolean) => void;
  deleting: boolean;
  toggling: boolean;
}) {
  const color = room.color ?? "#4a7c4e";
  return (
    <div style={{
      background: "#fffefb", border: "1px solid #efece5", borderRadius: 10,
      boxShadow: "0 1px 0 rgba(29,26,21,0.03), 0 1px 2px rgba(29,26,21,0.04)",
      overflow: "hidden", opacity: room.is_active ? 1 : 0.55,
      display: "flex", flexDirection: "column",
    }}>
      {/* Color band */}
      <div style={{ height: 5, background: color }} />

      <div style={{ padding: "16px 18px", flex: 1 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10 }}>
          {/* Color dot */}
          <div style={{
            width: 36, height: 36, borderRadius: 8, background: color + "22",
            border: `1.5px solid ${color}44`, display: "flex", alignItems: "center",
            justifyContent: "center", flexShrink: 0,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="14" rx="2"/>
              <path d="M8 4v16M16 4v16M3 12h18"/>
            </svg>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {room.name}
            </div>
            {room.location && (
              <div style={{ fontSize: 12, color: "#6b6559", fontFamily: FONT_JP, marginTop: 2 }}>
                {room.location}
              </div>
            )}
          </div>
          <MkPill tone={room.is_active ? "live" : "off"}>
            {room.is_active ? "利用可能" : "停止中"}
          </MkPill>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
          {room.capacity != null && (
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
              </svg>
              <span style={{ fontSize: 12, color: "#6b6559", fontFamily: FONT_JP }}>{room.capacity} 名</span>
            </div>
          )}
          {room.description && (
            <div style={{ fontSize: 12, color: "#a8a198", fontFamily: FONT_JP, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {room.description}
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 6, borderTop: "1px solid #f4f1ea", paddingTop: 12, flexWrap: "wrap" }}>
          <MkBtn variant="default" size="sm" onClick={() => onEdit(room)}>編集</MkBtn>
          <MkBtn
            variant="ghost" size="sm" disabled={toggling}
            onClick={() => onToggle(room.id, !room.is_active)}
          >
            {room.is_active ? "停止" : "有効化"}
          </MkBtn>
          <div style={{ flex: 1 }} />
          <MkBtn variant="danger" size="sm" disabled={deleting} onClick={() => onDelete(room.id)}>
            {deleting ? "削除中..." : "削除"}
          </MkBtn>
        </div>
      </div>
    </div>
  );
}

export default function MeetingRoomsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [rooms, setRooms] = useState<MeetingRoom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [formSaving, setFormSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [editRoom, setEditRoom] = useState<MeetingRoom | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    load(token);
  }, []);

  function load(token: string) {
    setLoading(true);
    api.listMeetingRooms(token)
      .then((data) => { setRooms(data); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  async function handleCreate(data: MeetingRoomCreate) {
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true); setFormError(null);
    try {
      const created = await api.createMeetingRoom(token, data);
      setRooms((prev) => [...prev, created]);
      setShowForm(false);
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "作成に失敗しました");
    } finally {
      setFormSaving(false);
    }
  }

  async function handleUpdate(data: MeetingRoomCreate & { is_active?: boolean }) {
    if (!editRoom) return;
    const token = getAccessToken();
    if (!token) return;
    setEditSaving(true); setEditError(null);
    try {
      const updated = await api.updateMeetingRoom(token, editRoom.id, data);
      setRooms((prev) => prev.map((r) => r.id === updated.id ? updated : r));
      setEditRoom(null);
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : "更新に失敗しました");
    } finally {
      setEditSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("この会議室を削除しますか？")) return;
    const token = getAccessToken();
    if (!token) return;
    setDeletingId(id);
    try {
      await api.deleteMeetingRoom(token, id);
      setRooms((prev) => prev.filter((r) => r.id !== id));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "削除に失敗しました");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleToggle(id: string, active: boolean) {
    const token = getAccessToken();
    if (!token) return;
    setTogglingId(id);
    try {
      const updated = await api.updateMeetingRoom(token, id, { is_active: active });
      setRooms((prev) => prev.map((r) => r.id === updated.id ? updated : r));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "更新に失敗しました");
    } finally {
      setTogglingId(null);
    }
  }

  const activeCount = rooms.filter((r) => r.is_active).length;

  return (
    <AdminShell
      active="meeting_rooms"
      title="会議室管理"
      subtitle="来社予定に紐付けられる会議室・商談室の登録と管理"
      breadcrumb={`${tenant} / 会議室管理`}
      actions={
        <MkBtn variant="primary" size="sm" onClick={() => { setShowForm(true); setFormError(null); }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          会議室を追加
        </MkBtn>
      }
    >
      <div style={{ padding: "24px 28px" }}>

        {/* KPI strip */}
        <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
          {[
            { label: "登録済み会議室", value: rooms.length, unit: "室", color: "#1d1a15" },
            { label: "利用可能", value: activeCount, unit: "室", color: "#4a7c4e" },
            { label: "停止中", value: rooms.length - activeCount, unit: "室", color: "#a8a198" },
          ].map(({ label, value, unit, color }) => (
            <MkCard key={label} style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#a8a198", fontFamily: FONT_JP, marginBottom: 8 }}>{label}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                <span style={{ fontSize: 28, fontWeight: 600, color, fontFamily: '"Inter", system-ui', letterSpacing: "-0.8px", lineHeight: 1 }}>{value}</span>
                <span style={{ fontSize: 13, color: "#a8a198" }}>{unit}</span>
              </div>
            </MkCard>
          ))}
        </div>

        {/* Create form */}
        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="会議室を追加" style={{ marginBottom: 16 }} />
            <RoomForm
              initial={{ name: "", color: "#4a7c4e" }}
              onSubmit={handleCreate}
              onCancel={() => { setShowForm(false); setFormError(null); }}
              saving={formSaving}
              error={formError}
              submitLabel="追加"
            />
          </MkCard>
        )}

        {/* Room grid */}
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
            読み込み中...
          </div>
        ) : error ? (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>
            {error}
          </div>
        ) : rooms.length === 0 ? (
          <MkCard>
            <div style={{ padding: "40px 0", textAlign: "center" }}>
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d8d3c7" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 16 }}>
                <rect x="3" y="4" width="18" height="14" rx="2"/>
                <path d="M8 4v16M16 4v16M3 12h18"/>
              </svg>
              <div style={{ fontSize: 14, color: "#a8a198", fontFamily: FONT_JP, marginBottom: 8 }}>
                会議室が登録されていません
              </div>
              <div style={{ fontSize: 12.5, color: "#d8d3c7", fontFamily: FONT_JP }}>
                「会議室を追加」から登録してください
              </div>
            </div>
          </MkCard>
        ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 16,
          }}>
            {rooms.map((room) => (
              <RoomCard
                key={room.id}
                room={room}
                onEdit={setEditRoom}
                onDelete={handleDelete}
                onToggle={handleToggle}
                deleting={deletingId === room.id}
                toggling={togglingId === room.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editRoom && (
        <div
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16 }}
          onClick={() => setEditRoom(null)}
        >
          <div
            style={{ background: "#fffefb", borderRadius: 16, padding: "28px 32px", maxWidth: 520, width: "100%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)", maxHeight: "90vh", overflowY: "auto" }}
            onClick={(e) => e.stopPropagation()}
          >
            <MkSectionTitle title="会議室を編集" style={{ marginBottom: 16 }} />
            <RoomForm
              initial={{
                name: editRoom.name,
                location: editRoom.location ?? "",
                capacity: editRoom.capacity ?? undefined,
                color: editRoom.color ?? "#4a7c4e",
                description: editRoom.description ?? "",
                is_active: editRoom.is_active,
              }}
              onSubmit={handleUpdate}
              onCancel={() => setEditRoom(null)}
              saving={editSaving}
              error={editError}
              submitLabel="保存"
            />
          </div>
        </div>
      )}
    </AdminShell>
  );
}
