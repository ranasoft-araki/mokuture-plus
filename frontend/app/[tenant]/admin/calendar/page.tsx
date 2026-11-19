"use client";

// Google カレンダー連携(来社予定 ⇔ Google カレンダー)。→ CLAUDE.md「Google カレンダー連携」節。
// 連携できる Google アカウントは 1 つ。方向は「mokuture+ → Google」「Google → mokuture+」のどちらか一方。

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkPill } from "@/components/AdminShell";
import { api, GoogleCalendarItem, GoogleCalendarStatus, GoogleCalendarSyncResult } from "@/lib/api";
import { getAccessToken, getRole } from "@/lib/auth";

type Direction = "to_google" | "from_google";
type Notice = "connected" | "denied" | "error" | "scope" | "mismatch";

const NOTICE_TEXT: Record<Notice, { tone: "ok" | "warn" | "error"; text: string }> = {
  connected: { tone: "ok", text: "Google アカウントを連携しました。下の「同期の設定」で連携の方向とカレンダーを選んで保存してください。" },
  denied: { tone: "warn", text: "Google アカウントの連携がキャンセルされました。" },
  error: { tone: "error", text: "Google アカウントの連携に失敗しました。お手数ですが、もう一度お試しください。" },
  mismatch: { tone: "error", text: "連携を始めた人と、いまログインしている人が違うため、連携しませんでした。連携したい人がログインして、この画面の「Googleアカウントで連携」から始めてください。" },
  scope: { tone: "error", text: "連携に必要な許可が足りませんでした。Google の確認画面で「カレンダーの予定の表示と編集」と「カレンダーの一覧の表示」の両方にチェックを入れたまま「続行」を押してください。" },
};

const BOX = { padding: "14px 16px", background: "#f4f1ea", borderRadius: 8, border: "1px solid #efece5" } as const;
const HINT = { fontSize: 11.5, color: "#8a8478", lineHeight: 1.7, marginTop: 6 } as const;
const LABEL = { fontSize: 12.5, fontWeight: 600, color: "#2d2a24", marginBottom: 8 } as const;

function Banner({ tone, children }: { tone: "ok" | "warn" | "error"; children: React.ReactNode }) {
  const c = {
    ok: { bg: "#eaf0e8", bd: "rgba(74,124,78,0.25)", fg: "#3a6240" },
    warn: { bg: "#fef6e4", bd: "rgba(180,130,0,0.25)", fg: "#7a5c00" },
    error: { bg: "#f6e0dc", bd: "rgba(168,66,56,0.3)", fg: "#a84238" },
  }[tone];
  return (
    <div style={{ marginBottom: 14, padding: "10px 14px", background: c.bg, border: `1px solid ${c.bd}`, borderRadius: 8, color: c.fg, fontSize: 12, lineHeight: 1.7 }}>
      {children}
    </div>
  );
}

function GoogleMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function calendarLabel(c: GoogleCalendarItem): string {
  return c.primary ? `${c.name}（メインのカレンダー）` : c.name;
}

function syncSummary(r: GoogleCalendarSyncResult, direction: Direction | null): string {
  const parts: string[] = [];
  if (direction === "to_google") {
    parts.push(`書き出し ${r.pushed}件`);
    if (r.removed) parts.push(`Google から削除 ${r.removed}件`);
  } else {
    parts.push(`新しく取り込み ${r.imported}件`, `変更を反映 ${r.updated}件`);
    if (r.removed) parts.push(`来社予定から削除 ${r.removed}件`);
  }
  if (r.failed) parts.push(`失敗 ${r.failed}件`);
  return parts.join(" / ");
}

export default function AdminCalendarPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";
  const token = getAccessToken() ?? "";
  const isAdmin = (() => { const r = getRole(); return r === "admin" || r === "superadmin" || r === null; })();

  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const [calendars, setCalendars] = useState<GoogleCalendarItem[] | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState("");

  const [direction, setDirection] = useState<Direction | null>(null);
  const [calendarId, setCalendarId] = useState("");
  const [keyword, setKeyword] = useState("来社");
  const [colors, setColors] = useState<string[]>([]);
  const [defaultStaff, setDefaultStaff] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveDone, setSaveDone] = useState("");

  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  const applyStatus = useCallback((s: GoogleCalendarStatus) => {
    setStatus(s);
    setDirection(s.direction);
    setCalendarId(s.calendar_id ?? "");
    // 取り込みをまだ保存していないときは「来社」を入れておく(空欄だとカレンダーの全予定が来社予定になるため)。
    // 書き出しで保存したあとに取り込みへ切り替える場合もここに入る(書き出しでは言葉を保存しない)。
    setKeyword(s.direction === "from_google" ? s.import_keyword : (s.import_keyword || "来社"));
    setColors(s.direction === "from_google" ? (s.import_colors ?? []) : []);
    setDefaultStaff(s.default_staff);
  }, []);

  const loadStatus = useCallback(async () => {
    if (!token) return;
    try {
      applyStatus(await api.getGoogleCalendarStatus(token));
      setLoadError("");
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : "連携の状態を読み込めませんでした");
    }
  }, [token, applyStatus]);

  const loadCalendars = useCallback(async () => {
    if (!token) return;
    setCalLoading(true);
    setCalError("");
    try {
      setCalendars((await api.listGoogleCalendars(token)).calendars);
    } catch (e: unknown) {
      setCalError(e instanceof Error ? e.message : "カレンダーの一覧を読み込めませんでした");
    } finally {
      setCalLoading(false);
    }
  }, [token]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const flag = url.searchParams.get("google");
    if (flag === "connected" || flag === "denied" || flag === "error" || flag === "scope" || flag === "mismatch") {
      setNotice(flag);
      url.searchParams.delete("google");
      window.history.replaceState({}, "", url.pathname + url.search);
    }
    loadStatus();
  }, [loadStatus]);

  const usable = !!status?.connected && status.status === "active";
  useEffect(() => {
    if (usable && isAdmin && calendars === null && !calLoading) loadCalendars();
  }, [usable, isAdmin, calendars, calLoading, loadCalendars]);

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError("");
    try {
      const res = await api.getGoogleCalendarOAuthUrl(token);
      if (!res.enabled || !res.authorize_url) {
        setConnectError("この環境では Google カレンダー連携は現在ご利用いただけません。運営にお問い合わせください。");
        setConnecting(false);
        return;
      }
      window.location.href = res.authorize_url;
    } catch (e: unknown) {
      setConnectError(e instanceof Error ? e.message : "連携を始められませんでした");
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.disconnectGoogleCalendar(token);
      setConfirmDisconnect(false);
      setCalendars(null);
      setNotice(null);
      await loadStatus();
    } catch (e: unknown) {
      setConnectError(e instanceof Error ? e.message : "連携を解除できませんでした");
    } finally {
      setDisconnecting(false);
    }
  };

  const selectedCal = useMemo(() => calendars?.find((c) => c.id === calendarId) ?? null, [calendars, calendarId]);
  const savedCalName = status?.calendar_name ?? "";
  const changingCalendar = !!status?.calendar_id && calendarId !== "" && calendarId !== status.calendar_id;
  const changingDirection = !!status?.direction && direction !== null && direction !== status.direction;

  // 保存すると何が起きるかを、保存の前に見せる(取り消せない変化があるため)
  const consequences: string[] = [];
  if (status?.direction === "to_google" && direction === "to_google" && changingCalendar) {
    consequences.push(`前のカレンダー（${savedCalName}）に書き出したこれからの予定は消して、新しいカレンダーに書き直します。`);
  }
  if (status?.direction === "from_google" && direction === "from_google" && changingCalendar) {
    consequences.push(`前のカレンダー（${savedCalName}）から取り込んだ、まだ受付していないこれからの予定は「来社予定」から消えます。`);
  }
  if (changingDirection && direction === "from_google") {
    consequences.push("これまで Google カレンダーに書き出した予定は、Google カレンダーにそのまま残ります。");
  }
  const sameColors = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
  if (status?.direction === "from_google" && direction === "from_google" && !changingCalendar
      && (keyword.trim() !== (status.import_keyword || "") || !sameColors(colors, status.import_colors ?? []))) {
    consequences.push("取り込む条件を変えると、これまで取り込んだ予定のうち新しい条件に合わないもの（まだ受付していない予定）は、続けて行う同期で「来社予定」から消えます。");
  }
  if (changingDirection && direction === "to_google") {
    consequences.push("これまで取り込んだ予定は「来社予定」に残りますが、Google カレンダーへは書き出しません（元の予定が Google カレンダーにあるため）。");
  }

  const canSave = !!direction && !!calendarId && !(direction === "to_google" && selectedCal && !selectedCal.writable);

  const handleSave = async () => {
    if (!direction || !calendarId) return;
    setSaving(true);
    setSaveError("");
    setSaveDone("");
    try {
      const s = await api.saveGoogleCalendarSettings(token, {
        direction, calendar_id: calendarId,
        import_keyword: direction === "from_google" ? keyword : "",
        import_colors: direction === "from_google" ? colors : [],
        default_staff: direction === "from_google" ? defaultStaff : "",
      });
      applyStatus(s);
      const removed = s.removed_imports ? `（前のカレンダーから取り込んだ予定 ${s.removed_imports}件を「来社予定」から消しました）` : "";
      setSaveDone(`保存しました。続けて同期しています${removed}。`);
      // 同期はサーバーの裏で進む。少し待ってから状況を読み直す。
      window.setTimeout(() => { loadStatus(); setSaveDone(""); }, 5000);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "保存できませんでした");
    } finally {
      setSaving(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg("");
    try {
      const s = await api.syncGoogleCalendar(token);
      applyStatus(s);
      setSyncMsg(`同期しました：${syncSummary(s.result, s.direction)}`);
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : "同期できませんでした");
    } finally {
      setSyncing(false);
    }
  };

  const mine = (calendars ?? []).filter((c) => c.group === "mine");
  const others = (calendars ?? []).filter((c) => c.group === "other");
  const calOption = (c: GoogleCalendarItem) => {
    const blocked = direction === "to_google" && !c.writable;
    return (
      <option key={c.id} value={c.id} disabled={blocked}>
        {calendarLabel(c)}{blocked ? "（閲覧のみ・書き出せません）" : ""}
      </option>
    );
  };

  const dirCard = (value: Direction, title: string, body: string) => {
    const on = direction === value;
    return (
      <button
        type="button"
        onClick={() => setDirection(value)}
        style={{
          textAlign: "left", padding: "14px 16px", borderRadius: 9, cursor: "pointer",
          border: on ? "2px solid #4a7c4e" : "1px solid #d8d3c7", background: on ? "#f3f7f1" : "#fffefb",
          display: "flex", gap: 10, alignItems: "flex-start", flex: "1 1 260px", minWidth: 0,
        }}
      >
        <span style={{ width: 16, height: 16, borderRadius: "50%", border: on ? "5px solid #4a7c4e" : "2px solid #c8c3b8", flexShrink: 0, marginTop: 2, background: "#fffefb" }} />
        <span>
          <span style={{ display: "block", fontSize: 13.5, fontWeight: 600, color: "#1d1a15", marginBottom: 4 }}>{title}</span>
          <span style={{ display: "block", fontSize: 11.5, color: "#6b6559", lineHeight: 1.7 }}>{body}</span>
        </span>
      </button>
    );
  };

  return (
    <AdminShell active="calendar" title="カレンダー連携" subtitle="「来社予定」を Google カレンダーと連携します">
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 820 }}>
        {loadError && <Banner tone="error">{loadError}</Banner>}

        {/* ── Google アカウント ── */}
        <MkCard>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
            <div style={{ width: 40, height: 40, borderRadius: 7, background: "#f7f4ef", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <GoogleMark size={22} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15" }}>Google アカウント</div>
              <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>連携できる Google アカウントは 1 つです。このアカウントで見られるカレンダーから、同期するカレンダーを 1 つ選びます</div>
            </div>
            <MkPill tone={status?.status === "reauth_required" ? "error" : status?.connected ? "live" : "off"}>
              {status?.status === "reauth_required" ? "要再連携" : status?.connected ? "連携済" : "未連携"}
            </MkPill>
          </div>

          {notice && <Banner tone={NOTICE_TEXT[notice].tone}>{NOTICE_TEXT[notice].text}</Banner>}
          {connectError && <Banner tone="error">{connectError}</Banner>}

          {status?.enabled === false ? (
            <div style={{ ...BOX, fontSize: 12.5, color: "#6b6559", lineHeight: 1.6 }}>
              この環境では Google カレンダー連携は現在ご利用いただけません。<br />ご利用をご希望の場合は運営までお問い合わせください。
            </div>
          ) : status?.connected ? (
            <>
              <div style={{ ...BOX, display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                  <div style={{ fontSize: 11, color: "#a8a198", width: 96, flexShrink: 0 }}>連携中のアカウント</div>
                  <div style={{ fontSize: 13, color: "#1d1a15", fontWeight: 500, wordBreak: "break-all" }}>{status.account_email || "—"}</div>
                </div>
              </div>
              {status.status === "reauth_required" && (
                <div style={{ marginTop: 12 }}>
                  <Banner tone="error">{status.last_error || "Google アカウントの連携が切れました。もう一度連携してください。"}</Banner>
                </div>
              )}
              {isAdmin && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
                  <MkBtn variant={status.status === "reauth_required" ? "primary" : "default"} onClick={handleConnect} disabled={connecting}>
                    <GoogleMark size={15} />
                    {connecting ? "Google へ移動中…" : status.status === "reauth_required" ? "もう一度連携する" : "別のアカウントに切り替える"}
                  </MkBtn>
                  {!confirmDisconnect ? (
                    <MkBtn variant="danger" onClick={() => setConfirmDisconnect(true)}>連携を解除</MkBtn>
                  ) : (
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, color: "#a84238" }}>解除すると同期が止まります。カレンダーの予定と来社予定はどちらも消えません。</span>
                      <MkBtn variant="danger" onClick={handleDisconnect} disabled={disconnecting}>{disconnecting ? "解除中…" : "解除する"}</MkBtn>
                      <MkBtn variant="ghost" onClick={() => setConfirmDisconnect(false)}>やめる</MkBtn>
                    </span>
                  )}
                </div>
              )}
              {isAdmin && status.status !== "reauth_required" && (
                <div style={HINT}>「別のアカウントに切り替える」で違うアカウントを選ぶと、選んであったカレンダーと、予定とカレンダーの結び付きはいったん外れます（予定そのものは消えません）。</div>
              )}
            </>
          ) : status ? (
            <>
              <div style={{ fontSize: 12.5, color: "#6b6559", lineHeight: 1.7, marginBottom: 16 }}>
                「Googleアカウントで連携」を押して Google アカウントで許可すると、同期するカレンダーと連携の方向を選べるようになります。
              </div>
              {isAdmin ? (
                <button
                  onClick={handleConnect}
                  disabled={connecting}
                  style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "10px 16px", fontSize: 14, fontWeight: 600, border: "1px solid #d8d3c7", borderRadius: 8, cursor: connecting ? "not-allowed" : "pointer", background: "#fffefb", color: "#1d1a15", opacity: connecting ? 0.6 : 1 }}
                >
                  <GoogleMark size={20} />
                  {connecting ? "Google へ移動中…" : "Googleアカウントで連携"}
                </button>
              ) : (
                <div style={{ fontSize: 12, color: "#8a8478" }}>連携の設定は管理者だけが行えます。</div>
              )}
            </>
          ) : null}
        </MkCard>

        {/* ── 同期の設定 ── */}
        {usable && (
          <MkCard>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", marginBottom: 4 }}>同期の設定</div>
            <div style={{ fontSize: 11.5, color: "#a8a198", marginBottom: 18 }}>連携の方向はどちらか一方だけ選べます</div>

            {!isAdmin ? (
              <div style={{ ...BOX, fontSize: 12.5, color: "#6b6559", lineHeight: 1.8 }}>
                連携の方向：{status?.direction === "to_google" ? "mokuture+ → Google カレンダー" : status?.direction === "from_google" ? "Google カレンダー → mokuture+" : "未設定"}<br />
                同期するカレンダー：{status?.calendar_name || "未設定"}<br />
                <span style={{ color: "#8a8478", fontSize: 11.5 }}>設定を変えられるのは管理者だけです。</span>
              </div>
            ) : (
              <>
                <div style={LABEL}>連携の方向</div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {dirCard("to_google", "mokuture+ → Google カレンダー",
                    "「来社予定」で登録した予定を、選んだ Google カレンダーに書き出します。予定の変更・削除も反映します。Google カレンダー側で変えても mokuture+ には戻りません。")}
                  {dirCard("from_google", "Google カレンダー → mokuture+",
                    "選んだ Google カレンダーの予定を「来社予定」に取り込みます（約5分ごと）。取り込んだ予定の QR コードは「来社予定」から発行・メール送信できます。")}
                </div>

                <div style={{ ...LABEL, marginTop: 20 }}>同期するカレンダー</div>
                {calError && <Banner tone="error">{calError}</Banner>}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <select
                    value={calendarId}
                    onChange={(e) => setCalendarId(e.target.value)}
                    disabled={calLoading || !calendars}
                    style={{ flex: "1 1 260px", minWidth: 0, maxWidth: 480, padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", color: "#1d1a15" }}
                  >
                    <option value="">{calLoading ? "読み込み中…" : "カレンダーを選んでください"}</option>
                    {mine.length > 0 && <optgroup label="マイカレンダー">{mine.map(calOption)}</optgroup>}
                    {others.length > 0 && <optgroup label="他のカレンダー">{others.map(calOption)}</optgroup>}
                  </select>
                  <MkBtn size="sm" onClick={loadCalendars} disabled={calLoading}>一覧を読み直す</MkBtn>
                </div>
                <div style={HINT}>
                  「マイカレンダー」は、連携したアカウントがオーナーのカレンダーです（いちばん上がメインのカレンダー）。「他のカレンダー」は共有されているカレンダーで、編集の権限が無いものには書き出せません。
                </div>

                {direction === "from_google" && (
                  <>
                    <div style={{ ...LABEL, marginTop: 20 }}>取り込む予定（タイトルに含まれる言葉）</div>
                    <input
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                      maxLength={64}
                      placeholder="例: 来社"
                      style={{ width: "100%", maxWidth: 320, padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb" }}
                    />
                    <div style={HINT}>
                      タイトルにこの言葉を含む予定だけを取り込みます。<b>空欄にして、下の「取り込む予定（色）」も選ばないと、選んだカレンダーの時間が決まっている予定がすべて「来社予定」になります</b>（会議などの社内の予定も含みます）。
                      終日の予定と、自分が「いいえ」と返事した予定は取り込みません。予定のタイトルが、そのまま来社予定の「お名前」になります。
                    </div>

                    <div style={{ ...LABEL, marginTop: 20 }}>取り込む予定（色）</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {(status?.event_colors ?? []).map((c) => {
                        const on = colors.includes(c.id);
                        const swatch = c.hex ?? selectedCal?.color ?? "#c8c3b8";
                        return (
                          <button
                            key={c.id}
                            type="button"
                            aria-pressed={on}
                            onClick={() => setColors((cur) => (cur.includes(c.id) ? cur.filter((x) => x !== c.id) : [...cur, c.id]))}
                            style={{
                              display: "inline-flex", alignItems: "center", gap: 7, padding: "6px 11px", borderRadius: 999, cursor: "pointer",
                              fontSize: 12.5, color: "#1d1a15", background: on ? "#f3f7f1" : "#fffefb",
                              border: on ? "2px solid #4a7c4e" : "1px solid #d8d3c7",
                            }}
                          >
                            <span style={{ width: 14, height: 14, borderRadius: "50%", background: swatch, flexShrink: 0, ...(c.hex ? {} : { boxShadow: "inset 0 0 0 2px #fffefb, 0 0 0 1px " + swatch }) }} />
                            {c.name}
                            {on && <span style={{ color: "#4a7c4e", fontWeight: 700 }}>✓</span>}
                          </button>
                        );
                      })}
                    </div>
                    <div style={{ ...BOX, marginTop: 10, fontSize: 12.5, color: "#1d1a15", lineHeight: 1.7 }}>
                      いまの条件：{(() => {
                        const kw = keyword.trim();
                        const names = (status?.event_colors ?? []).filter((c) => colors.includes(c.id)).map((c) => c.name);
                        if (!kw && names.length === 0) return "選んだカレンダーの、時間が決まっている予定をすべて取り込みます。";
                        const parts = [kw ? `タイトルに「${kw}」を含む` : "", names.length ? `色が「${names.join("」「")}」の` : ""].filter(Boolean);
                        return `${parts.join("、かつ ")}予定だけを取り込みます。`;
                      })()}
                    </div>
                    {keyword.trim() && colors.length > 0 && (
                      <div style={{ ...HINT, color: "#8a5a12" }}>
                        色だけで選びたいときは、上の「取り込む予定（タイトルに含まれる言葉）」を空欄にしてください（言葉が入っていると、言葉と色の両方に合う予定だけになります）。
                      </div>
                    )}
                    <div style={HINT}>
                      Google カレンダーで予定に付けた色で絞り込めます（予定を開いて色を選ぶと付きます）。「色を付けていない予定」は、色を選ばずカレンダーの色のまま表示されている予定です。色を選ばなければ、色では絞り込みません。
                      Google カレンダーで予定の色を変えて条件から外れると、まだ受付していないその予定は「来社予定」から消えます（色を戻すと、新しい予定としてもう一度取り込みます。担当者などは付け直しになります）。
                    </div>

                    <div style={{ ...LABEL, marginTop: 20 }}>取り込んだ予定の担当者</div>
                    <select
                      value={defaultStaff}
                      onChange={(e) => setDefaultStaff(e.target.value)}
                      style={{ width: "100%", maxWidth: 320, padding: "8px 10px", fontSize: 13, border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb" }}
                    >
                      <option value="">指定しない</option>
                      {(status?.staff_list ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <div style={HINT}>
                      担当者は「通知設定」の「担当者ごとの通知先」で登録した名前から選べます。予定の「場所」に会議室の名前が入っていれば、その会議室も入れます。
                      取り込んだあとに「来社予定」で変えた担当者・会議室・会社名・メモは、Google カレンダーで予定が変わっても上書きしません（上書きするのはお名前と日時だけです）。
                    </div>
                  </>
                )}

                {consequences.length > 0 && (
                  <div style={{ marginTop: 18 }}>
                    <Banner tone="warn">
                      保存すると次のようになります。
                      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{consequences.map((c) => <li key={c}>{c}</li>)}</ul>
                    </Banner>
                  </div>
                )}
                {saveError && <div style={{ marginTop: 14 }}><Banner tone="error">{saveError}</Banner></div>}
                {saveDone && <div style={{ marginTop: 14 }}><Banner tone="ok">{saveDone}</Banner></div>}
                <div style={{ marginTop: 18 }}>
                  <MkBtn variant="primary" onClick={handleSave} disabled={!canSave || saving}>{saving ? "保存中…" : "保存して同期する"}</MkBtn>
                </div>
              </>
            )}
          </MkCard>
        )}

        {/* ── 同期の状況 ── */}
        {status?.connected && status.direction && status.calendar_id && (
          <MkCard>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1d1a15", flex: 1 }}>同期の状況</div>
              <MkPill tone={!status.active ? "off" : status.last_error ? "warn" : "live"}>
                {!status.active ? "停止中" : status.last_error ? "一部うまくいっていません" : "同期中"}
              </MkPill>
            </div>
            <div style={{ ...BOX, display: "flex", flexDirection: "column", gap: 8 }}>
              <Row label="連携の方向" value={status.direction === "to_google" ? "mokuture+ → Google カレンダー" : "Google カレンダー → mokuture+"} />
              <Row label="カレンダー" value={status.calendar_name || "—"} />
              <Row label="最後に同期した日時" value={fmtDateTime(status.last_synced_at)} />
              {status.direction === "to_google" && (
                <Row label="まだ送れていない予定" value={status.unsynced_count ? `${status.unsynced_count}件（自動で送り直します）` : "ありません"} />
              )}
            </div>
            {status.last_error && status.status !== "reauth_required" && (
              <div style={{ marginTop: 12 }}>
                <Banner tone="warn">最後のエラー（{fmtDateTime(status.last_error_at)}）：{status.last_error}</Banner>
              </div>
            )}
            <div style={HINT}>
              {status.direction === "to_google"
                ? "「来社予定」で登録・変更・削除すると、すぐに Google カレンダーへ反映します。送れなかった予定は約5分ごとに送り直します。過去（前日より前）の予定は書き出しません。"
                : "Google カレンダーの予定を約5分ごとに取り込みます（前日から90日先まで）。Google カレンダーで消した予定は、まだ受付していなければ「来社予定」からも消えます。「来社予定」で消した予定は、次から取り込みません。"}
            </div>
            {isAdmin && status.active && (
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
                <MkBtn onClick={handleSync} disabled={syncing}>{syncing ? "同期しています…" : "今すぐ同期"}</MkBtn>
                {syncMsg && <span style={{ fontSize: 12, color: "#6b6559" }}>{syncMsg}</span>}
              </div>
            )}
          </MkCard>
        )}
        <div style={{ fontSize: 11.5, color: "#a8a198" }}>
          来社予定の一覧は <a href={`/${tenant}/admin/appointments`} style={{ color: "#4a7c4e" }}>「来社予定」</a> で確認できます。
        </div>
      </div>
    </AdminShell>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
      <div style={{ fontSize: 11, color: "#a8a198", width: 120, flexShrink: 0 }}>{label}</div>
      <div style={{ fontSize: 13, color: "#1d1a15", fontWeight: 500, wordBreak: "break-all", minWidth: 0 }}>{value}</div>
    </div>
  );
}
