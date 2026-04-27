"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Playlist, type Schedule } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";
import { AdminShell, MkBtn, MkCard } from "@/components/AdminShell";

const DAYS = ["月", "火", "水", "木", "金", "土", "日"] as const;
const HOURS = Array.from({ length: 24 }, (_, i) => i);

// Color palette per playlist (cycled by index)
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
    if (!confirm("このスケジュールを削除しますか？")) return;
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

  // Build a stable color map: playlist_id → palette index
  const plColorMap: Record<string, number> = {};
  let colorIdx = 0;
  schedules.forEach((s) => {
    if (!(s.playlist_id in plColorMap)) {
      plColorMap[s.playlist_id] = colorIdx++ % PALETTE.length;
    }
  });

  // For each day (0=Mon…6=Sun), gather blocks
  function getBlocksForDay(dayIndex: number) {
    return schedules.filter((s) => s.day_of_week === dayIndex || s.day_of_week === -1);
  }

  return (
    <AdminShell
      active="schedule"
      title="配信スケジュール"
      breadcrumb="ホーム / コンテンツ管理 / スケジュール"
      subtitle="曜日 × 時間帯でプレイリストを自動切替"
      actions={
        <MkBtn variant="default" size="sm" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "閉じる" : "+ 新規ブロック"}
        </MkBtn>
      }
    >
      {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238", fontSize: 13 }}>{error}</div>}
      {success && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 7, background: "#eaf0e8", border: "1px solid #4a7c4e", color: "#3a6240", fontSize: 13 }}>{success}</div>}

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

      {/* Weekly grid */}
      <MkCard padding="0">
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
                    const startMin = timeToMinutes(s.start_time);
                    const endMin = timeToMinutes(s.end_time);
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
                          overflow: "hidden", cursor: "pointer",
                        }}
                        onClick={() => void handleDelete(s.id)}
                        title="クリックで削除"
                      >
                        <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: 600 }}>{plName}</div>
                        <div style={{ fontSize: 9, opacity: 0.7, fontFamily: "monospace", marginTop: 1 }}>
                          {s.start_time} – {s.end_time}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </MkCard>

      {schedules.length === 0 && !loading && (
        <div style={{ marginTop: 16, padding: "12px 16px", background: "#f4f1ea", borderRadius: 7, borderLeft: "2px solid #4a7c4e", fontSize: 11.5, color: "#6b6559", fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
          「+ 新規ブロック」からスケジュールを追加すると、キオスクが自動的に指定時間帯のプレイリストを再生します。グリッドのブロックをクリックすると削除できます。
        </div>
      )}
    </AdminShell>
  );
}
