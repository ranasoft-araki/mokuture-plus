"use client";

// 遠隔ログイン(運営が、問題の起きた端末へ必要なときだけ SSH で入る)の表示と操作。
// 一覧の 1 マス(RemoteLoginCell)と、開く・終了する・つなぎ方を見るダイアログ(RemoteLoginModal)。

import { useEffect, useState } from "react";
import { api, OperatorDevice, TunnelDeviceStatus, TunnelSession, TunnelStatus } from "@/lib/api";
import { MkBtn, MkPill } from "@/components/AdminShell";

type Tone = "live" | "warn" | "off" | "error" | "info" | "neutral";

const BASTION_USER_KEY = "mk_bastion_user";

function minutesLeft(session: TunnelSession, now: number): number {
  if (!session.expires_at) return 0;
  return Math.max(0, Math.ceil((new Date(session.expires_at).getTime() - now) / 60000));
}

/** 一覧と見出しに出す、いまの状態(短い言葉・色・1 行の説明)。 */
export function describeTunnel(
  status: TunnelStatus | null,
  d: TunnelDeviceStatus | undefined,
  now: number,
): { label: string; tone: Tone; detail: string } {
  if (!status) return { label: "確認中…", tone: "neutral", detail: "" };
  if (!status.enabled) {
    return {
      label: "使えません",
      tone: "off",
      detail: "サーバーに踏み台サーバーの設定（TUNNEL_BASTION_HOST など）がまだありません。",
    };
  }
  if (!d) return { label: "確認中…", tone: "neutral", detail: "" };
  const s = d.session;
  if (s?.state === "open") {
    return { label: `接続中（残り ${minutesLeft(s, now)} 分）`, tone: "live", detail: "端末が踏み台サーバーへ接続しています。下の「つなぎ方」で端末に入れます。" };
  }
  if (s?.state === "requested") {
    return {
      label: "接続準備中",
      tone: "warn",
      detail: s.error
        ? `端末が踏み台サーバーへ接続できていません（${s.error}）。端末は接続をやり直し続けています。`
        : d.reach === "blocked"
          ? "この端末の設置先のネットワークからは、踏み台サーバーへ接続できない見込みです。しばらく待っても「接続中」にならなければ終了してください。"
          : !d.alive
            ? "端末がしばらくサーバーへ問い合わせに来ていません（電源・回線が切れている可能性）。端末が戻れば接続されます。"
            : "端末が要求を受け取ると、自動で踏み台サーバーへ接続します（最大 1 分ほど）。端末側での操作や承認は要りません（端末の画面も変わりません）。",
    };
  }
  if (s?.state === "closing") {
    return { label: "終了待ち", tone: "warn", detail: "終了を指示しました。踏み台サーバー側の経路は 1 分以内に切れます。端末が閉じたと報告するのを待っています。" };
  }
  if (!d.ready) {
    return { label: "端末が未対応", tone: "off", detail: "この端末には、遠隔ログインの仕組みがまだ入っていません（システム更新が届くと入ります。届いていれば、端末のキオスク設定 → デバイスチェック →「ソフトウェア更新」の「OS の設定・部品」に失敗が出ていないか確かめてください）。" };
  }
  if (d.reach === "blocked") {
    return {
      label: "踏み台へ届かない",
      tone: "error",
      detail: "この端末の設置先のネットワークからは、踏み台サーバーへ接続できません。遠隔ログインは使えない見込みです。",
    };
  }
  if (!d.alive) {
    return { label: "端末の応答なし", tone: "off", detail: "端末がしばらくサーバーへ問い合わせに来ていません（電源が切れている・回線が切れている可能性）。開いても接続されないかもしれません。" };
  }
  return { label: "閉じています", tone: "neutral", detail: "端末はどこにも接続していません。" };
}

export function RemoteLoginCell({
  status, device, now, onOpen,
}: { status: TunnelStatus | null; device: OperatorDevice; now: number; onOpen: () => void }) {
  const d = status?.devices[device.id];
  const view = describeTunnel(status, d, now);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <MkPill tone={view.tone}>{view.label}</MkPill>
      <MkBtn size="sm" onClick={onOpen}>{d?.session ? "詳細" : "開く…"}</MkBtn>
    </div>
  );
}

/** 公開鍵("ssh-ed25519 AAAA...")の指紋。ssh が初回接続のときに表示するものと同じ形。 */
async function fingerprint(key: string | null): Promise<string> {
  const body = (key || "").split(" ")[1];
  if (!body || !window.crypto?.subtle) return "";
  try {
    const raw = Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", raw));
    let bin = "";
    digest.forEach((b) => { bin += String.fromCharCode(b); });
    return "SHA256:" + btoa(bin).replace(/=+$/, "");
  } catch {
    return "";
  }
}

const label: React.CSSProperties = { fontSize: 11.5, fontWeight: 600, color: "#6b6559", marginBottom: 6, display: "block" };
const field: React.CSSProperties = {
  width: "100%", border: "1px solid #d8d3c7", borderRadius: 6, fontSize: 13, padding: "8px 10px",
  outline: "none", background: "#fffefb", color: "#1d1a15", boxSizing: "border-box",
};
const note: React.CSSProperties = { fontSize: 12, color: "#6b6559", lineHeight: 1.7 };
const section: React.CSSProperties = { borderTop: "1px solid #efece5", paddingTop: 16, marginTop: 16 };

const CLOSE_REASON: Record<string, string> = { operator: "運営が終了", expired: "時間切れ" };

export function RemoteLoginModal({
  token, device, status, now, onClose, onChanged,
}: {
  token: string;
  device: OperatorDevice;
  status: TunnelStatus | null;
  now: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const d = status?.devices[device.id];
  const session = d?.session ?? null;
  const live = session?.state === "requested" || session?.state === "open";
  const view = describeTunnel(status, d, now);

  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState<number>(status?.default_minutes ?? 60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // このダイアログは操作のあとにだけ出る(サーバー側では描かれない)ので、最初から保存値を読んでよい
  const [bastionUser, setBastionUser] = useState(() => {
    try { return localStorage.getItem(BASTION_USER_KEY) || ""; } catch { return ""; }
  });
  const [copied, setCopied] = useState(false);
  const [print, setPrint] = useState("");
  const [bastionPrint, setBastionPrint] = useState("");
  const [history, setHistory] = useState<TunnelSession[]>([]);

  useEffect(() => { fingerprint(d?.host_key ?? null).then(setPrint); }, [d?.host_key]);
  useEffect(() => { fingerprint(status?.bastion_host_key ?? null).then(setBastionPrint); }, [status?.bastion_host_key]);
  // 状態が変わるたびに記録を読み直す(開いた・閉じたがすぐ一覧に出る)
  useEffect(() => {
    api.listTunnelSessions(token, device.id).then((r) => setHistory(r.sessions.slice(0, 5))).catch(() => {});
  }, [token, device.id, session?.id, session?.state]);

  const choices = [15, 30, 60, 120, 240].filter(
    (m) => m >= (status?.min_minutes ?? 5) && m <= (status?.max_minutes ?? 240),
  );

  const submit = async () => {
    if (!reason.trim()) { setError("理由を入力してください（あとで記録を見返すために残します）。"); return; }
    setBusy(true); setError("");
    try {
      await api.openTunnel(token, device.id, { reason: reason.trim(), minutes });
      setReason("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "開けませんでした");
    } finally {
      setBusy(false);
    }
  };

  const close = async () => {
    setBusy(true); setError("");
    try {
      await api.closeTunnel(token, device.id);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "終了できませんでした");
    } finally {
      setBusy(false);
    }
  };

  const saveBastionUser = (v: string) => {
    const cleaned = v.replace(/[^a-z0-9-]/g, "");
    setBastionUser(cleaned);
    try { localStorage.setItem(BASTION_USER_KEY, cleaned); } catch { /* 保存できなくても使える */ }
  };

  const command = session && status
    ? `ssh -J ${bastionUser || "<踏み台サーバーでのあなたの利用者名>"}@${status.bastion_host}:${status.bastion_port} -p ${session.port} ${d?.login_user || "<端末の利用者名>"}@127.0.0.1`
    : "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("コピーできませんでした。コマンドを選択してコピーしてください。");
    }
  };

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(29,26,21,0.45)", zIndex: 1000, display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "40px 12px", overflowY: "auto" }}
    >
      <div
        className="adm-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ width: 640, maxWidth: "100%", background: "#fffefb", borderRadius: 12, padding: 24, boxShadow: "0 12px 40px rgba(0,0,0,0.18)" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#1d1a15" }}>遠隔ログイン</div>
            <div style={{ fontSize: 12.5, color: "#6b6559", marginTop: 4 }}>
              {device.name}{device.tenant_name ? `（${device.tenant_name}）` : ""}{device.location ? ` ・ ${device.location}` : ""}
            </div>
          </div>
          <MkBtn variant="ghost" size="sm" onClick={onClose}>閉じる</MkBtn>
        </div>

        <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: "#6b6559" }}>いまの状態</span>
          <MkPill tone={view.tone}>{view.label}</MkPill>
        </div>
        {view.detail && <div style={{ ...note, marginTop: 8 }}>{view.detail}</div>}

        {session && (
          <div style={section}>
            <div style={note}>
              開いた人: {session.requested_by || "—"}
              {session.expires_at && <> ／ 自動で閉じる時刻: {new Date(session.expires_at).toLocaleString("ja-JP")}</>}
            </div>
            <div style={{ ...note, whiteSpace: "pre-wrap", marginTop: 4 }}>理由: {session.reason}</div>
          </div>
        )}

        {session && live && status && (
          <div style={section}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#1d1a15", marginBottom: 10 }}>つなぎ方</div>
            <label style={label}>踏み台サーバーでのあなたの利用者名（踏み台サーバーの管理者が登録した名前。このブラウザに覚えます）</label>
            <input style={{ ...field, maxWidth: 260 }} value={bastionUser} onChange={(e) => saveBastionUser(e.target.value)} placeholder="例: yamada" />
            <label style={{ ...label, marginTop: 14 }}>
              {session.state === "open" ? "あなたの PC のターミナルで、次を実行します" : "「接続中」になったら、あなたの PC のターミナルで次を実行します"}
            </label>
            <div style={{ display: "flex", gap: 8, alignItems: "stretch", flexWrap: "wrap" }}>
              <code style={{ flex: "1 1 320px", minWidth: 0, background: "#f4f1ea", borderRadius: 6, padding: "10px 12px", fontSize: 12, fontFamily: '"JetBrains Mono", monospace', color: "#1d1a15", wordBreak: "break-all" }}>
                {command}
              </code>
              <MkBtn size="sm" onClick={copy}>{copied ? "コピーしました" : "コピー"}</MkBtn>
            </div>
            <div style={{ ...note, marginTop: 10 }}>
              入れるのは、公開鍵を登録済みの人だけです（踏み台サーバーと端末の両方に登録が必要）。
              {(print || bastionPrint) && (
                <>
                  <br />
                  初めてつなぐ相手には、ssh が相手の指紋（fingerprint）を表示して続けるか尋ねます（踏み台サーバー → この端末 の順に 2 回）。次と同じであることを確かめてから yes と答えてください:
                  {bastionPrint && (
                    <>
                      <br />
                      踏み台サーバー: <code style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 11.5, wordBreak: "break-all" }}>{bastionPrint}</code>
                    </>
                  )}
                  {print && (
                    <>
                      <br />
                      この端末: <code style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 11.5, wordBreak: "break-all" }}>{print}</code>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {status?.enabled && session?.state !== "closing" && (
          <div style={section}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#1d1a15", marginBottom: 6 }}>
              {live ? "終了時刻を延ばす" : "遠隔ログインを開く"}
            </div>
            {!live && (
              <div style={{ ...note, marginBottom: 12 }}>
                開くと、この端末が踏み台サーバー（{status.bastion_host}:{status.bastion_port}）へ接続します。
                端末が要求を受け取るまで最大 1 分ほどかかります。端末側での操作や承認は要らず、キオスクの画面も変わりません。下で選んだ時間が過ぎると自動で閉じます。
              </div>
            )}
            <label style={label}>{live ? "延ばす理由（記録に残ります）" : "理由（記録に残ります）"}</label>
            <textarea
              style={{ ...field, minHeight: 60, resize: "vertical", fontFamily: "inherit" }}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              placeholder="例: 受付画面が固まったとの連絡。ログを確認する"
            />
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 12, flexWrap: "wrap" }}>
              <div>
                <label style={label}>{live ? "いまから何分後まで開けておくか" : "開けておく時間"}</label>
                <select style={{ ...field, width: 140, cursor: "pointer" }} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                  {choices.map((m) => <option key={m} value={m}>{m} 分</option>)}
                </select>
              </div>
              <MkBtn variant="primary" onClick={submit} disabled={busy}>
                {live ? "終了時刻を延ばす" : "遠隔ログインを開く"}
              </MkBtn>
            </div>
          </div>
        )}

        {error && <div style={{ marginTop: 14, fontSize: 12.5, color: "#a84238", background: "#f6e0dc", borderRadius: 6, padding: "8px 12px" }}>{error}</div>}

        {session && live && (
          <div style={{ ...section, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div style={{ ...note, flex: "1 1 240px" }}>作業が終わったら終了してください。押し忘れても、上の時刻に自動で閉じます。</div>
            <MkBtn variant="danger" onClick={close} disabled={busy}>遠隔ログインを終了する</MkBtn>
          </div>
        )}

        {history.length > 0 && (
          <div style={section}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#1d1a15", marginBottom: 8 }}>この端末の記録（新しい順・5 件まで）</div>
            {history.map((h) => (
              <div key={h.id} style={{ ...note, padding: "6px 0", borderBottom: "1px solid #f4f1ea" }}>
                {h.requested_at ? new Date(h.requested_at).toLocaleString("ja-JP") : "—"} ／ {h.requested_by || "—"} ／{" "}
                {h.state === "closed"
                  ? `終了（${CLOSE_REASON[h.close_reason ?? ""] ?? "—"}${h.opened_at ? "" : "・端末は接続しなかった"}${h.error ? "・端末が閉じたことは未確認" : ""}）`
                  : h.state === "open" ? "接続中" : h.state === "closing" ? "終了待ち" : "接続準備中"}
                <div style={{ whiteSpace: "pre-wrap", color: "#a8a198" }}>{h.reason}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
