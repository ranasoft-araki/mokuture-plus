"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill, MkSectionTitle } from "@/components/AdminShell";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, InvitationItem, InvitationList, InviteResponse, InviteStatus, UserListItem } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { parseEmailList } from "@/lib/inviteEmails";

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';
const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

const ROLE_LABEL: Record<string, string> = { admin: "管理者", staff: "スタッフ" };

function RolePill({ role }: { role: string }) {
  if (role === "admin") return <MkPill tone="live">管理者</MkPill>;
  if (role === "staff") return <MkPill tone="info">スタッフ</MkPill>;
  return <MkPill tone="neutral">{role}</MkPill>;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// 貼り付けた宛先の下に出す「送る前の見通し」の種類
type PreviewKind = "new" | "resend" | "member" | "invalid" | "duplicate";
const PREVIEW_STYLE: Record<PreviewKind, { label: string; bg: string; fg: string; border: string }> = {
  new:       { label: "新しく招待",           bg: "#eef4ec", fg: "#3e6b42", border: "#cfe0cb" },
  resend:    { label: "招待中→送り直す",      bg: "#eef2f7", fg: "#3d5a80", border: "#cfdae8" },
  member:    { label: "ユーザー一覧に登録済み", bg: "#f3f1ec", fg: "#8a8478", border: "#e2ddd2" },
  invalid:   { label: "形式の誤り",           bg: "#fbefed", fg: "#a84238", border: "#efcfca" },
  duplicate: { label: "重複",                bg: "#f3f1ec", fg: "#8a8478", border: "#e2ddd2" },
};

const RESULT_LABEL: Record<InviteStatus, string> = {
  sent: "招待メールを送りました",
  resent: "招待中だったので、新しいリンクで送り直しました（前のリンクは使えません）",
  already_user: "既に登録されているため送りませんでした",
  invalid: "メールアドレスの形式が正しくないため送りませんでした",
  duplicate: "同じアドレスが2回入っていたため1回だけにしました",
  failed: "送れませんでした（宛先を確かめて、もう一度お試しください）",
};
const RESULT_ORDER: InviteStatus[] = ["failed", "invalid", "sent", "resent", "already_user", "duplicate"];

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #d8d3c7", borderRadius: 7,
  fontFamily: FONT_JP, background: "#faf8f4",
  boxSizing: "border-box",
};
const labelStyle: React.CSSProperties = { display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP };
const noteStyle: React.CSSProperties = { fontSize: 12, color: "#8a8478", lineHeight: 1.7, fontFamily: FONT_JP };

function InviteCard({
  users,
  invites,
  onSent,
  onClose,
}: {
  users: UserListItem[];
  invites: InvitationList | null;
  onSent: (res: InviteResponse) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [role, setRole] = useState("staff");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InviteResponse | null>(null);

  const memberSet = useMemo(() => new Set(users.map((u) => u.email.toLowerCase())), [users]);
  const pendingSet = useMemo(
    () => new Set((invites?.invitations ?? []).map((i) => i.email.toLowerCase())),
    [invites],
  );

  const parsed = useMemo(() => parseEmailList(text), [text]);
  const preview = useMemo(
    () => parsed.entries.map((e) => {
      let kind: PreviewKind;
      if (e.status === "invalid") kind = "invalid";
      else if (e.status === "duplicate") kind = "duplicate";
      else if (memberSet.has(e.email.toLowerCase())) kind = "member";
      else if (pendingSet.has(e.email.toLowerCase())) kind = "resend";
      else kind = "new";
      return { email: e.email, kind };
    }),
    [parsed, memberSet, pendingSet],
  );
  const counts = preview.reduce<Record<PreviewKind, number>>(
    (acc, p) => { acc[p.kind] += 1; return acc; },
    { new: 0, resend: 0, member: 0, invalid: 0, duplicate: 0 },
  );
  // 送るのは 新しく招待＋送り直し。ほかのテナントに登録済みのアドレスは送ってみるまで分からない(サーバーが送らずに返す)。
  const toSend = preview.filter((p) => p.kind === "new" || p.kind === "resend").map((p) => p.email);

  const smtpOff = invites !== null && !invites.smtp_enabled;
  const remaining = invites?.mail_remaining ?? 0;
  const limit = invites?.mail_limit ?? 30;
  const maxPerRequest = invites?.max_per_request ?? 100;
  const overQuota = toSend.length > remaining;
  const overMax = parsed.entries.length > maxPerRequest;
  const canSend = !smtpOff && invites !== null && toSend.length > 0 && !overQuota && !overMax && !sending;

  async function send() {
    const token = getAccessToken();
    if (!token || !canSend) return;
    setSending(true);
    setError(null);
    setResult(null);
    try {
      // 形式の誤り・重複・登録済みも送り、結果の一覧に理由つきで並べてもらう(画面と判定がずれても気づける)
      const res = await api.inviteUsers(token, parsed.entries.map((e) => e.email), role);
      setResult(res);
      // 送れなかったものだけ入力欄に残す(直して押し直せるように)
      const retry = res.results.filter((r) => r.status === "failed" || r.status === "invalid").map((r) => r.email);
      setText(retry.join("\n"));
      onSent(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "招待メールの送信に失敗しました");
    } finally {
      setSending(false);
    }
  }

  return (
    <MkCard style={{ marginBottom: 20 }}>
      <MkSectionTitle title="メールで招待する" subtitle="招待された人は、メールのリンクから自分でパスワードを決めて登録します" />

      {smtpOff && (
        <div style={{ ...noteStyle, color: "#a84238", background: "#fbefed", border: "1px solid #efcfca", borderRadius: 8, padding: "10px 12px", marginBottom: 14 }}>
          メール送信が設定されていないため、招待メールを送れません。運営にSMTPの設定をご依頼ください。
          それまでは右上の「パスワードを決めて追加」からユーザーを追加できます。
        </div>
      )}

      <label style={labelStyle} htmlFor="invite-emails">招待する人のメールアドレス（まとめて貼り付けできます）</label>
      <textarea
        id="invite-emails"
        value={text}
        onChange={(e) => { setText(e.target.value); setResult(null); setError(null); }}
        rows={6}
        disabled={smtpOff}
        placeholder={"taro@example.co.jp\nhanako@example.co.jp, jiro@example.co.jp\n山田 花子 <yamada@example.co.jp>"}
        style={{ ...inputStyle, fontFamily: FONT_MONO, fontSize: 12.5, lineHeight: 1.6, resize: "vertical" }}
      />
      <div style={{ ...noteStyle, marginTop: 6, marginBottom: 14 }}>
        改行・カンマ（,）・読点（、）・セミコロン（;）・タブ・空白のどれで区切っても読み取ります。
        Excel の列や、Outlook・Gmail の宛先欄（「名前 &lt;アドレス&gt;」の形）からそのままコピーして貼れます。
      </div>

      <div className="adm-toolbar" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 14 }}>
        <div>
          <label style={labelStyle} htmlFor="invite-role">招待する人の権限</label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            disabled={smtpOff}
            style={{ ...inputStyle, width: "auto", minWidth: 180 }}
          >
            <option value="staff">スタッフ</option>
            <option value="admin">管理者</option>
          </select>
        </div>
        <div style={{ ...noteStyle, flex: "1 1 220px", minWidth: 0 }}>
          ここで招待する人は全員この権限になります。登録後に「ユーザー一覧」で1人ずつ変えられます。
        </div>
      </div>

      {preview.length > 0 && (
        <div style={{ border: "1px solid #efece5", borderRadius: 10, padding: "12px 14px", marginBottom: 14, background: "#fdfcf9" }}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12.5, fontFamily: FONT_JP, color: "#4a463d", marginBottom: 10 }}>
            <span>読み取ったアドレス <b>{preview.length}</b> 件</span>
            <span style={{ color: "#3e6b42" }}>送る <b>{toSend.length}</b> 件</span>
            {counts.resend > 0 && <span style={{ color: "#3d5a80" }}>うち送り直し {counts.resend} 件</span>}
            {counts.member > 0 && <span style={{ color: "#8a8478" }}>登録済み {counts.member} 件（送りません）</span>}
            {counts.duplicate > 0 && <span style={{ color: "#8a8478" }}>重複 {counts.duplicate} 件（1回だけ送ります）</span>}
            {counts.invalid > 0 && <span style={{ color: "#a84238" }}>形式の誤り {counts.invalid} 件（送りません）</span>}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 180, overflowY: "auto" }}>
            {preview.map((p, i) => {
              const s = PREVIEW_STYLE[p.kind];
              return (
                <span
                  key={`${p.email}-${i}`}
                  title={s.label}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%",
                    padding: "3px 9px", borderRadius: 999, fontSize: 12, fontFamily: FONT_MONO,
                    background: s.bg, color: s.fg, border: `1px solid ${s.border}`, wordBreak: "break-all",
                  }}
                >
                  {p.email}
                  {p.kind !== "new" && <span style={{ fontFamily: FONT_JP, fontSize: 10.5, opacity: 0.85 }}>{s.label}</span>}
                </span>
              );
            })}
          </div>
          {parsed.skipped.length > 0 && (
            <div style={{ ...noteStyle, marginTop: 10 }}>
              「@」を含まない語 {parsed.skipped.length} 個（名前など）はメールアドレスではないので読み飛ばしました：
              <span style={{ fontFamily: FONT_MONO, wordBreak: "break-all" }}> {parsed.skipped.slice(0, 12).join("、")}{parsed.skipped.length > 12 ? " …" : ""}</span>
            </div>
          )}
          {counts.resend > 0 && (
            <div style={{ ...noteStyle, marginTop: 6 }}>
              「招待中→送り直す」は、下の「招待中」に既にあるアドレスです。新しいリンクで送り直し、前に送ったリンクは使えなくなります。
            </div>
          )}
        </div>
      )}

      {invites && !smtpOff && (
        <div style={{ ...noteStyle, marginBottom: 12, color: overQuota ? "#a84238" : "#8a8478" }}>
          招待メールは、来社予定のQRメールなどと合わせて1時間に{limit}通まで送れます（いま送れるのはあと {remaining} 通）。
          {overQuota && ` 送る宛先が${toSend.length}件あるため送れません。宛先を減らすか、しばらく待ってからお試しください。`}
          {overMax && ` 一度に読み取れるのは${maxPerRequest}件までです。`}
          {" "}招待のリンクは送ってから{invites.expire_days}日間使えます。
        </div>
      )}

      {error && <div style={{ fontSize: 12.5, color: "#a84238", marginBottom: 12, fontFamily: FONT_JP }}>{error}</div>}

      {result && (
        <div style={{ border: "1px solid #efece5", borderRadius: 10, padding: "12px 14px", marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", fontFamily: FONT_JP, marginBottom: 8 }}>送信の結果</div>
          {RESULT_ORDER.filter((st) => (result.counts[st] ?? 0) > 0).map((st) => (
            <div key={st} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12.5, fontFamily: FONT_JP, color: st === "failed" || st === "invalid" ? "#a84238" : "#4a463d" }}>
                {RESULT_LABEL[st]}（{result.counts[st]} 件）
              </div>
              <div style={{ fontSize: 12, fontFamily: FONT_MONO, color: "#6b6559", wordBreak: "break-all", lineHeight: 1.7 }}>
                {result.results.filter((r) => r.status === st).map((r) => r.email).join("、")}
              </div>
            </div>
          ))}
          {(result.counts.failed ?? 0) + (result.counts.invalid ?? 0) > 0 && (
            <div style={noteStyle}>送れなかったアドレスは入力欄に残してあります。直してからもう一度押してください。</div>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <MkBtn variant="primary" size="sm" disabled={!canSend} onClick={send}>
          {sending ? "送信中..." : toSend.length > 0 ? `${toSend.length}件に招待メールを送る` : "招待メールを送る"}
        </MkBtn>
        <MkBtn variant="default" size="sm" onClick={onClose}>閉じる</MkBtn>
      </div>
    </MkCard>
  );
}

export default function AdminUsersPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";

  const [users, setUsers] = useState<UserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState("staff");
  const [formError, setFormError] = useState<string | null>(null);
  const [formSaving, setFormSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [modal, setModal] = useState<{ msg: string; action: () => Promise<void>; confirmLabel?: string } | null>(null);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [pwResetId, setPwResetId] = useState<string | null>(null);
  const [pwResetValue, setPwResetValue] = useState("");
  const [pwResetSaving, setPwResetSaving] = useState(false);
  const [pwResetError, setPwResetError] = useState<string | null>(null);
  const [pwResetSuccess, setPwResetSuccess] = useState<string | null>(null);
  const [isManager, setIsManager] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [invites, setInvites] = useState<InvitationList | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteBusyId, setInviteBusyId] = useState<string | null>(null);
  const [inviteNotice, setInviteNotice] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    let manager = false;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      // マウント後のクライアント専用初期化（トークンから自分のIDと権限を読む）
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentUserId(payload.sub ?? null);
      manager = payload.role === "admin" || payload.role === "superadmin";
    } catch {}
    setIsManager(manager);
    load(token);
    if (manager) loadInvites(token);
  }, []);

  function load(token: string) {
    setLoading(true);
    api.listUsers(token)
      .then((data) => { setUsers(data); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  function loadInvites(token: string) {
    api.listInvitations(token)
      .then((data) => { setInvites(data); setInviteError(null); })
      .catch((e: Error) => setInviteError(e.message));
  }

  function handleInviteSent() {
    const token = getAccessToken();
    if (token) loadInvites(token);
  }

  async function handleResend(inv: InvitationItem) {
    const token = getAccessToken();
    if (!token) return;
    setInviteBusyId(inv.id);
    setInviteError(null);
    setInviteNotice(null);
    try {
      await api.resendInvitation(token, inv.id);
      setInviteNotice(`${inv.email} へ新しいリンクで送り直しました。前に送ったリンクは使えなくなりました。`);
      loadInvites(token);
    } catch (e: unknown) {
      setInviteError(e instanceof Error ? e.message : "送り直しに失敗しました");
    } finally {
      setInviteBusyId(null);
    }
  }

  function handleCancelInvite(inv: InvitationItem) {
    setModal({
      msg: `${inv.email} への招待を取り消しますか？送った招待メールのリンクは使えなくなります。`,
      confirmLabel: "取り消す",
      action: async () => {
        const token = getAccessToken();
        if (!token) return;
        setInviteBusyId(inv.id);
        setInviteError(null);
        setInviteNotice(null);
        try {
          await api.cancelInvitation(token, inv.id);
          loadInvites(token);
        } catch (e: unknown) {
          setInviteError(e instanceof Error ? e.message : "取り消しに失敗しました");
        } finally {
          setInviteBusyId(null);
        }
      },
    });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setFormSaving(true);
    setFormError(null);
    try {
      const created = await api.createUser(token, { email: formEmail, password: formPassword, role: formRole });
      setUsers((prev) => [created, ...prev]);
      setShowForm(false);
      setFormEmail("");
      setFormPassword("");
      setFormRole("staff");
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "作成に失敗しました");
    } finally {
      setFormSaving(false);
    }
  }

  function handleDelete(userId: string) {
    setModal({
      msg: "このユーザーを削除しますか？",
      action: async () => {
        const token = getAccessToken();
        if (!token) return;
        setDeletingId(userId);
        try {
          await api.deleteUser(token, userId);
          setUsers((prev) => prev.filter((u) => u.id !== userId));
        } catch (e: unknown) {
          setError(e instanceof Error ? e.message : "削除に失敗しました");
        } finally {
          setDeletingId(null);
        }
      },
    });
  }

  async function handleRoleChange(userId: string, role: string) {
    const token = getAccessToken();
    if (!token) return;
    try {
      const updated = await api.updateUserRole(token, userId, role);
      setUsers((prev) => prev.map((u) => u.id === userId ? updated : u));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "ロール変更に失敗しました");
    }
  }

  function openPwReset(userId: string) {
    setPwResetId(userId);
    setPwResetValue("");
    setPwResetError(null);
    setPwResetSuccess(null);
  }

  async function handlePasswordReset(e: React.FormEvent, userId: string) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    setPwResetSaving(true);
    setPwResetError(null);
    try {
      await api.resetUserPassword(token, userId, pwResetValue);
      setPwResetSuccess(userId);
      setPwResetValue("");
      setTimeout(() => { setPwResetSuccess(null); setPwResetId(null); }, 2000);
    } catch (err: unknown) {
      setPwResetError(err instanceof Error ? err.message : "パスワードのリセットに失敗しました");
    } finally {
      setPwResetSaving(false);
    }
  }

  return (
    <>
    {modal && (
      <ConfirmModal
        message={modal.msg}
        confirmLabel={modal.confirmLabel}
        onConfirm={async () => { const action = modal.action; setModal(null); await action(); }}
        onCancel={() => setModal(null)}
      />
    )}
    <AdminShell
      active="users"
      title="ユーザー管理"
      subtitle="テナントのユーザーを管理します"
      breadcrumb={`${tenant} / 設定`}
      actions={
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isManager && (
            <MkBtn variant="primary" size="sm" onClick={() => { setShowInvite((v) => !v); setShowForm(false); }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3 7 12 13 21 7"/>
              </svg>
              メールで招待
            </MkBtn>
          )}
          <MkBtn variant="default" size="sm" onClick={() => { setShowForm((v) => !v); setShowInvite(false); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            パスワードを決めて追加
          </MkBtn>
        </div>
      }
    >
      <div style={{ padding: "24px 28px", maxWidth: 860 }}>
        {showInvite && isManager && (
          <InviteCard
            users={users}
            invites={invites}
            onSent={handleInviteSent}
            onClose={() => setShowInvite(false)}
          />
        )}

        {showForm && (
          <MkCard style={{ marginBottom: 20 }}>
            <MkSectionTitle title="パスワードを決めて追加" subtitle="メールを送らずに、ここで決めたパスワードを本人に伝えて使ってもらいます" />
            <form onSubmit={handleCreate}>
              <div className="adm-cols-2" style={{ marginBottom: 12 }}>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                    メールアドレス
                  </label>
                  <input
                    type="email"
                    required
                    value={formEmail}
                    onChange={(e) => setFormEmail(e.target.value)}
                    style={{
                      width: "100%", padding: "8px 10px", fontSize: 13,
                      border: "1px solid #d8d3c7", borderRadius: 7,
                      fontFamily: FONT_JP, background: "#faf8f4",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                    パスワード（8文字以上）
                  </label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={formPassword}
                    onChange={(e) => setFormPassword(e.target.value)}
                    style={{
                      width: "100%", padding: "8px 10px", fontSize: 13,
                      border: "1px solid #d8d3c7", borderRadius: 7,
                      fontFamily: FONT_JP, background: "#faf8f4",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 11.5, color: "#6b6559", marginBottom: 5, fontFamily: FONT_JP }}>
                  ロール
                </label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value)}
                  style={{
                    padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7",
                    borderRadius: 7, fontFamily: FONT_JP, background: "#faf8f4",
                    minWidth: 180,
                  }}
                >
                  <option value="staff">スタッフ</option>
                  <option value="admin">管理者</option>
                </select>
              </div>
              {formError && (
                <div style={{ fontSize: 12.5, color: "#a84238", marginBottom: 12, fontFamily: FONT_JP }}>
                  {formError}
                </div>
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

        <MkCard padding="0">
          <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #efece5" }}>
            <MkSectionTitle
              title="ユーザー一覧"
              subtitle={`${users.length} 名`}
              style={{ marginBottom: 0 }}
            />
          </div>

          {loading ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
              読み込み中...
            </div>
          ) : error ? (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#a84238", fontFamily: FONT_JP }}>
              {error}
            </div>
          ) : users.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#a8a198", fontFamily: FONT_JP }}>
              ユーザーがいません
            </div>
          ) : (
            <div className="adm-scroll-x">
            <table style={{ width: "100%", minWidth: 600, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #efece5" }}>
                  {["メールアドレス", "ロール", "作成日", "操作"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 20px", textAlign: "left",
                        fontSize: 11, color: "#a8a198", fontWeight: 600,
                        letterSpacing: "0.4px", textTransform: "uppercase",
                        fontFamily: FONT_MONO,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u, idx) => (
                  <tr
                    key={u.id}
                    style={{
                      borderBottom: idx < users.length - 1 ? "1px solid #efece5" : "none",
                      background: "transparent",
                    }}
                  >
                    <td style={{ padding: "12px 20px", fontSize: 13, color: "#1d1a15", fontFamily: FONT_JP }}>
                      {u.email}
                      {u.id === currentUserId && (
                        <span style={{ marginLeft: 8, fontSize: 10.5, color: "#a8a198", fontFamily: FONT_MONO }}>（自分）</span>
                      )}
                    </td>
                    <td style={{ padding: "12px 20px" }}>
                      {u.id === currentUserId ? (
                        <RolePill role={u.role} />
                      ) : (
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value)}
                          style={{
                            padding: "4px 8px", fontSize: 12, border: "1px solid #d8d3c7",
                            borderRadius: 6, fontFamily: FONT_JP, background: "#faf8f4",
                            cursor: "pointer",
                          }}
                        >
                          <option value="staff">スタッフ</option>
                          <option value="admin">管理者</option>
                        </select>
                      )}
                    </td>
                    <td style={{ padding: "12px 20px", fontSize: 12, color: "#6b6559", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>
                      {new Date(u.created_at).toLocaleDateString("ja-JP")}
                    </td>
                    <td style={{ padding: "12px 20px" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        {u.id !== currentUserId && (
                          pwResetId === u.id ? (
                            <form onSubmit={(e) => handlePasswordReset(e, u.id)} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                              <input
                                type="password"
                                required
                                minLength={8}
                                placeholder="新パスワード (8文字以上)"
                                value={pwResetValue}
                                onChange={(e) => setPwResetValue(e.target.value)}
                                style={{
                                  padding: "4px 8px", fontSize: 12, border: "1px solid #d8d3c7",
                                  borderRadius: 6, fontFamily: FONT_JP, background: "#faf8f4", maxWidth: 180, width: "100%",
                                }}
                              />
                              <MkBtn type="submit" variant="primary" size="sm" disabled={pwResetSaving}>
                                {pwResetSuccess === u.id ? "完了" : pwResetSaving ? "保存中..." : "保存"}
                              </MkBtn>
                              <MkBtn variant="default" size="sm" onClick={() => { setPwResetId(null); setPwResetError(null); }}>
                                ×
                              </MkBtn>
                              {pwResetError && pwResetId === u.id && (
                                <span style={{ fontSize: 11.5, color: "#a84238", fontFamily: FONT_JP }}>{pwResetError}</span>
                              )}
                            </form>
                          ) : (
                            <MkBtn variant="default" size="sm" onClick={() => openPwReset(u.id)}>
                              PW変更
                            </MkBtn>
                          )
                        )}
                        <MkBtn
                          variant="danger"
                          size="sm"
                          disabled={u.id === currentUserId || deletingId === u.id}
                          onClick={() => handleDelete(u.id)}
                        >
                          {deletingId === u.id ? "削除中..." : "削除"}
                        </MkBtn>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </MkCard>

        {isManager && (invites?.invitations.length || inviteError || inviteNotice) ? (
          <MkCard padding="0" style={{ marginTop: 20 }}>
            <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #efece5" }}>
              <MkSectionTitle
                title="招待中"
                subtitle={`招待メールを送り、まだ登録していない人 ${invites?.invitations.length ?? 0} 名。登録すると「ユーザー一覧」に移ります`}
                style={{ marginBottom: 0 }}
              />
            </div>
            {(inviteError || inviteNotice) && (
              <div style={{ padding: "10px 20px", fontSize: 12.5, fontFamily: FONT_JP, color: inviteError ? "#a84238" : "#3e6b42" }}>
                {inviteError ?? inviteNotice}
              </div>
            )}
            {invites && invites.invitations.length > 0 && (
              <div className="adm-scroll-x">
                <table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #efece5" }}>
                      {["メールアドレス", "権限", "送った日時", "リンクの期限", "操作"].map((h) => (
                        <th key={h} style={{ padding: "10px 20px", textAlign: "left", fontSize: 11, color: "#a8a198", fontWeight: 600, fontFamily: FONT_JP, whiteSpace: "nowrap" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {invites.invitations.map((inv, idx) => (
                      <tr key={inv.id} style={{ borderBottom: idx < invites.invitations.length - 1 ? "1px solid #efece5" : "none" }}>
                        <td style={{ padding: "12px 20px", fontSize: 13, color: "#1d1a15", fontFamily: FONT_JP, wordBreak: "break-all" }}>{inv.email}</td>
                        <td style={{ padding: "12px 20px", fontSize: 12.5, color: "#4a463d", fontFamily: FONT_JP, whiteSpace: "nowrap" }}>{ROLE_LABEL[inv.role] ?? inv.role}</td>
                        <td style={{ padding: "12px 20px", fontSize: 12, color: "#6b6559", fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>{fmtDateTime(inv.sent_at ?? inv.created_at)}</td>
                        <td style={{ padding: "12px 20px", whiteSpace: "nowrap" }}>
                          {inv.expired
                            ? <MkPill tone="error">期限切れ</MkPill>
                            : <span style={{ fontSize: 12, color: "#6b6559", fontFamily: FONT_MONO }}>{fmtDateTime(inv.expires_at)} まで</span>}
                        </td>
                        <td style={{ padding: "12px 20px" }}>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <MkBtn
                              variant="default"
                              size="sm"
                              disabled={inviteBusyId === inv.id || !invites.smtp_enabled}
                              onClick={() => handleResend(inv)}
                            >
                              {inviteBusyId === inv.id ? "処理中..." : "送り直す"}
                            </MkBtn>
                            <MkBtn variant="danger" size="sm" disabled={inviteBusyId === inv.id} onClick={() => handleCancelInvite(inv)}>
                              取り消す
                            </MkBtn>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </MkCard>
        ) : null}
      </div>
    </AdminShell>
    </>
  );
}
