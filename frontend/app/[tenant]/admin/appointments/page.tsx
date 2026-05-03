"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { api, type AppointmentCreate, type TenantSettings, type VisitorAppointment } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

function StatusBadge({ status }: { status: string }) {
  if (status === "received") return <MkPill tone="live">チェックイン済</MkPill>;
  if (status === "expired")  return <MkPill tone="neutral">期限切れ</MkPill>;
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

export default function AppointmentsPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [appointments, setAppointments] = useState<VisitorAppointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<AppointmentCreate>({ visitor_name: "", scheduled_at: "" });
  const [formSaving, setFormSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [staffList, setStaffList] = useState<string[]>([]);
  const [purposeList, setPurposeList] = useState<string[]>([]);

  const [qrAppt, setQrAppt] = useState<VisitorAppointment | null>(null);
  const printRef = useRef<HTMLDivElement>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    load(token);
    api.getTenantSettings(token).then((s: TenantSettings) => {
      if (s.staff_list) setStaffList(s.staff_list.split(",").map((v) => v.trim()).filter(Boolean));
      if (s.purpose_list) setPurposeList(s.purpose_list.split(",").map((v) => v.trim()).filter(Boolean));
    }).catch(() => {});
  }, []);

  function load(token: string) {
    setLoading(true);
    api.listAppointments(token)
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

  function openForm() {
    resetForm();
    setShowForm(true);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true);
    setFormError(null);
    try {
      const created = await api.createAppointment(token, {
        ...formData,
        scheduled_at: new Date(formData.scheduled_at).toISOString(),
      });
      setAppointments((prev) => [created, ...prev].sort(
        (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
      ));
      setShowForm(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally {
      setFormSaving(false);
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

  return (
    <AdminShell
      active="appointments"
      title="来社予定管理"
      subtitle="来訪者の予定を事前登録し、QRコードを発行します"
      breadcrumb={`${tenant} / 受付`}
      actions={
        <MkBtn variant="primary" size="sm" onClick={openForm}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          予定を追加
        </MkBtn>
      }
    >
      <div style={{ padding: "24px 28px", maxWidth: 960 }}>

        {/* 新規作成フォーム */}
        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="来社予定を追加" />
            <form onSubmit={handleCreate}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>氏名 *</label>
                  <input
                    type="text"
                    required
                    value={formData.visitor_name}
                    onChange={(e) => setFormData((p) => ({ ...p, visitor_name: e.target.value }))}
                    style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>会社名</label>
                  <input
                    type="text"
                    value={formData.company ?? ""}
                    onChange={(e) => setFormData((p) => ({ ...p, company: e.target.value }))}
                    style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>目的</label>
                  {purposeList.length > 0 ? (
                    <select
                      value={formData.purpose ?? ""}
                      onChange={(e) => setFormData((p) => ({ ...p, purpose: e.target.value }))}
                      style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                    >
                      <option value="">未選択</option>
                      {purposeList.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={formData.purpose ?? ""}
                      onChange={(e) => setFormData((p) => ({ ...p, purpose: e.target.value }))}
                      style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                    />
                  )}
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>担当者</label>
                  {staffList.length > 0 ? (
                    <select
                      value={formData.staff ?? ""}
                      onChange={(e) => setFormData((p) => ({ ...p, staff: e.target.value }))}
                      style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                    >
                      <option value="">未選択</option>
                      {staffList.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={formData.staff ?? ""}
                      onChange={(e) => setFormData((p) => ({ ...p, staff: e.target.value }))}
                      style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                    />
                  )}
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>来社日時 *</label>
                  <input
                    type="datetime-local"
                    required
                    value={formData.scheduled_at}
                    onChange={(e) => setFormData((p) => ({ ...p, scheduled_at: e.target.value }))}
                    style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>メモ</label>
                  <input
                    type="text"
                    value={formData.notes ?? ""}
                    onChange={(e) => setFormData((p) => ({ ...p, notes: e.target.value }))}
                    style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4", boxSizing: "border-box" }}
                  />
                </div>
              </div>
              {formError && (
                <div style={{ fontSize: 12.5, color: "#a84238", marginBottom: 12, fontFamily: FONT_JP }}>{formError}</div>
              )}
              <div style={{ display: "flex", gap: 10 }}>
                <MkBtn type="submit" variant="primary" size="sm" disabled={formSaving}>
                  {formSaving ? "作成中..." : "作成"}
                </MkBtn>
                <MkBtn variant="default" size="sm" onClick={() => { setShowForm(false); setFormError(null); }}>
                  キャンセル
                </MkBtn>
              </div>
            </form>
          </MkCard>
        )}

        {/* 一覧テーブル */}
        <MkCard padding="0">
          <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #efece5" }}>
            <MkSectionTitle title="予定一覧" subtitle={`${appointments.length} 件`} style={{ marginBottom: 0 }} />
          </div>

          {loading ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>読み込み中...</div>
          ) : error ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>{error}</div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
              来社予定がありません。「予定を追加」から登録してください。
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #efece5" }}>
                    {["来社日時", "氏名", "会社", "担当", "目的", "ステータス", "QR", "操作"].map((h) => (
                      <th
                        key={h}
                        style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, color: "#a8a198", fontWeight: 600, letterSpacing: "0.4px", textTransform: "uppercase", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {appointments.map((appt, idx) => (
                    <tr
                      key={appt.id}
                      style={{ borderBottom: idx < appointments.length - 1 ? "1px solid #efece5" : "none" }}
                    >
                      <td style={{ padding: "12px 16px", fontSize: 12.5, color: "#1d1a15", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                        {fmtDatetime(appt.scheduled_at)}
                      </td>
                      <td style={{ padding: "12px 16px", fontSize: 13, color: "#1d1a15", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                        {appt.visitor_name}
                      </td>
                      <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                        {appt.company ?? "—"}
                      </td>
                      <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                        {appt.staff ?? "—"}
                      </td>
                      <td style={{ padding: "12px 16px", fontSize: 13, color: "#6b6559", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                        {appt.purpose ?? "—"}
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <StatusBadge status={appt.status} />
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <MkBtn variant="default" size="sm" onClick={() => setQrAppt(appt)}>
                          QR表示
                        </MkBtn>
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <MkBtn
                          variant="danger"
                          size="sm"
                          disabled={deletingId === appt.id}
                          onClick={() => handleDelete(appt.id)}
                        >
                          {deletingId === appt.id ? "削除中..." : "削除"}
                        </MkBtn>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </MkCard>
      </div>

      {/* QRモーダル */}
      {qrAppt && (
        <div
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex",
            alignItems: "center", justifyContent: "center", zIndex: 1000,
          }}
          onClick={() => setQrAppt(null)}
        >
          <div
            style={{ background: "#fffefb", borderRadius: 20, padding: "40px 48px", maxWidth: 480, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div ref={printRef} style={{ textAlign: "center" }}>
              <div style={{ marginBottom: 20 }}>
                <QRCodeSVG
                  value={`appt:${qrAppt.token}`}
                  size={200}
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
              <p style={{ margin: "16px 0 0", fontSize: 11, color: "#c8c3b8", fontFamily: FONT_MONO, wordBreak: "break-all" }}>
                予約コード: {qrAppt.token}
              </p>
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 28, justifyContent: "center" }}>
              <MkBtn variant="primary" size="sm" onClick={handlePrint}>
                印刷
              </MkBtn>
              <MkBtn variant="default" size="sm" onClick={() => setQrAppt(null)}>
                閉じる
              </MkBtn>
            </div>
          </div>
        </div>
      )}
    </AdminShell>
  );
}
