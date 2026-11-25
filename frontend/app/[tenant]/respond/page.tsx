"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError, DecisionLinkLookup, DecisionLinkResult } from "@/lib/api";

// メール・Teams の受付通知の「受付／電話／お断り」から開く画面（公開・ログイン不要）。
// リンクは /{slug}/respond#token=…&via=teams&d=accept の形。トークンは「#」の後ろ
// （サーバーへ送られない部分）にあり、ここで読んで API へ本文で渡す。
//
// 開いただけでは返事にしない。メールや Teams のセキュリティ機能はリンクが安全かを確かめるために
// 中身を勝手に開くので、開いた時点で確定すると担当者が押していないのに返事が済んでしまう。
// 開いたときは受付の内容を読むだけで、返事はこの画面のボタンを押したときに確定する。

const FONT_JP = "'Noto Sans JP', Inter, system-ui, sans-serif";
const TOKEN_KEY = "mk_respond_link";
const EXPIRED_MESSAGE = "このリンクは使えなくなりました（通知から2時間で使えなくなります）。受付ログから対応してください。";

type Decision = "accept" | "phone" | "decline";
type Via = "email" | "teams";

const STATE_LABEL: Record<string, string> = { accepted: "受付", phone: "電話", declined: "お断り" };
// 返事以外で閉じた受付（管理画面で「完了」「取り消し」にしたもの）。
const CLOSED_LABEL: Record<string, string> = { completed: "完了", cancelled: "取り消し" };
// 押すとキオスクに何が出るか（来訪者が見る画面）。
const KIOSK_EFFECT: Record<Decision, string> = {
  accept: "キオスクに「参りますので少々お待ちください」と出ます",
  phone: "対応できないとき。キオスクに受付の電話番号が出ます",
  decline: "営業・勧誘のとき。キオスクにお断りの案内が出ます",
};

interface LinkParams { token: string; via: Via; chosen: Decision | null }

// URL の「#…」を読んだら、アドレス欄と閲覧履歴から消してこのタブの sessionStorage へ移す
// （共有画面や履歴にリンクが残らないように。再読み込みしても続きから使える）。
function readLink(): LinkParams {
  const empty: LinkParams = { token: "", via: "email", chosen: null };
  if (typeof window === "undefined") return empty;
  const parse = (raw: string): LinkParams => {
    const q = new URLSearchParams(raw);
    const d = q.get("d");
    return {
      token: q.get("token") ?? "",
      via: q.get("via") === "teams" ? "teams" : "email",
      chosen: d === "accept" || d === "phone" || d === "decline" ? d : null,
    };
  };
  const hash = window.location.hash.replace(/^#/, "");
  try {
    if (hash) {
      const fromHash = parse(hash);
      if (fromHash.token) {
        sessionStorage.setItem(TOKEN_KEY, hash);
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        return fromHash;
      }
    }
    return parse(sessionStorage.getItem(TOKEN_KEY) ?? "");
  } catch {
    return parse(hash);
  }
}

function fmt(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function withHonorific(name: string): string {
  const n = (name || "").trim();
  return !n || /(様|さま|さん|殿)$/.test(n) ? n : `${n} 様`;
}

export default function RespondPage() {
  const params = useParams<{ tenant: string }>();
  const slug = params?.tenant ?? "";
  const [link, setLink] = useState<LinkParams>({ token: "", via: "email", chosen: null });
  const [info, setInfo] = useState<DecisionLinkLookup | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sending, setSending] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ decision: Decision; res: DecisionLinkResult } | null>(null);

  useEffect(() => {
    const l = readLink();
    // マウント後にだけ読める URL の「#」以降からトークンを取る
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLink(l);
    if (!l.token) {
      setLoadError("リンクが正しくありません。通知のボタン（またはリンク）をもう一度開いてください。");
      setLoading(false);
      return;
    }
    api.lookupDecisionLink(l.token)
      .then((res) => setInfo(res))
      .catch((e: unknown) => {
        const status = e instanceof ApiError ? e.status : 0;
        setLoadError(
          status === 401
            ? EXPIRED_MESSAGE
            : status === 404
              ? "この受付は見つかりませんでした（削除された可能性があります）。"
              : "受付を確認できませんでした。時間をおいてもう一度お試しください。",
        );
      })
      .finally(() => setLoading(false));
  }, []);

  async function decide(decision: Decision) {
    if (sending) return;
    setSending(decision);
    setError(null);
    try {
      const res = await api.decideByLinkToken(link.token, decision, link.via);
      setResult({ decision, res });
    } catch (e: unknown) {
      const status = e instanceof ApiError ? e.status : 0;
      setError(status === 401
        ? EXPIRED_MESSAGE
        : "返事を送れませんでした。通信の状態を確かめて、もう一度押してください。");
    } finally {
      setSending(null);
    }
  }

  const card: React.CSSProperties = { background: "#fffefb", border: "1px solid #e7e3d9", borderRadius: 16, padding: "24px 22px" };
  const receptionLog = slug ? `/${slug}/admin/reception` : "/login";
  const adminLink = (
    <a href={receptionLog} style={{ fontSize: 13, color: "#3e6b42", fontWeight: 600 }}>受付ログを開く（ログインが必要です）</a>
  );

  let content: React.ReactNode;
  if (loading) {
    content = <div style={{ ...card, textAlign: "center", color: "#a8a198", fontSize: 14 }}>受付を確認しています...</div>;
  } else if (loadError || !info) {
    content = (
      <div style={card}>
        <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#a84238" }}>{loadError}</p>
        {adminLink}
      </div>
    );
  } else if (result) {
    const label = STATE_LABEL[result.res.state] ?? "";
    content = (
      <div style={card}>
        {result.res.decision_applied ? (
          <>
            <p style={{ margin: "0 0 8px", fontSize: 20, fontWeight: 700, color: "#3e6b42" }}>「{label}」で返事をしました</p>
            <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#4a463d" }}>{KIOSK_EFFECT[result.decision]}。</p>
          </>
        ) : result.res.decision_expired ? (
          <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#7a5c00" }}>
            返事が間に合わず、キオスクは電話の案内に切り替わっていました。
          </p>
        ) : (
          <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#7a5c00" }}>
            先に{result.res.decided_by_name || "ほかの人"}さんが「{label}」で返事をしていました。この返事は送られていません。
          </p>
        )}
        {adminLink}
      </div>
    );
  } else {
    const rows: [string, string][] = [];
    if (info.method === "delivery") {
      // 配達の呼び出しは visitor_name="配達"・company=受付端末の名前で記録されている。
      rows.push(["ご用件", "荷物の配達（呼び出し）"]);
      if (info.company) rows.push(["受付端末", info.company]);
    } else {
      if (info.company) rows.push(["会社名", info.company]);
      rows.push(["お名前", withHonorific(info.visitor_name)]);
    }
    if (info.department) rows.push(["訪問先部署", info.department]);
    if (info.staff) rows.push(["訪問先", info.staff]);
    if (info.purpose && info.method !== "delivery") rows.push(["ご用件", info.purpose]);
    if (info.created_at) rows.push(["受付時刻", fmt(info.created_at)]);
    const actions = [...info.actions].sort((a, b) =>
      a.action === link.chosen ? -1 : b.action === link.chosen ? 1 : 0);

    content = (
      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 20 }}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: "5px 14px 5px 0", color: "#8a8478", fontSize: 13, whiteSpace: "nowrap", verticalAlign: "top" }}>{k}</td>
                <td style={{ padding: "5px 0", color: "#2d2a24", fontSize: 15, fontWeight: 600, wordBreak: "break-all" }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {info.decided ? (
          <>
            <p style={{ margin: "0 0 18px", fontSize: 14, lineHeight: 1.8, color: "#7a5c00" }}>
              {info.decision_expired
                ? "返事が無いまま時間切れになり、キオスクは電話の案内に切り替わりました。"
                : CLOSED_LABEL[info.state]
                  ? `この受付は管理画面で「${CLOSED_LABEL[info.state]}」になっているため、返事はできません。`
                  : `すでに${info.decided_by_name || "ほかの人"}さんが「${STATE_LABEL[info.state] ?? ""}」で返事をしています。`}
            </p>
            {adminLink}
          </>
        ) : (
          <>
            <p style={{ margin: "0 0 14px", fontSize: 14, lineHeight: 1.8, color: "#4a463d" }}>
              押すと返事が確定し、受付の画面（キオスク）に伝わります。
            </p>
            {actions.map((a, i) => {
              const primary = link.chosen ? a.action === link.chosen : i === 0;
              const busy = sending === a.action;
              return (
                <button
                  key={a.action}
                  type="button"
                  onClick={() => decide(a.action)}
                  disabled={sending !== null}
                  style={{
                    display: "block", width: "100%", textAlign: "left", marginBottom: 10,
                    padding: "14px 18px", borderRadius: 12, cursor: sending ? "default" : "pointer", fontFamily: FONT_JP,
                    border: primary ? "none" : "1px solid #c9d6c9",
                    background: primary ? (sending ? "#9db59f" : "#4a7c4e") : "#fffefb",
                    color: primary ? "#fff" : "#2d2a24",
                  }}
                >
                  <span style={{ display: "block", fontSize: 17, fontWeight: 700 }}>
                    {busy ? "送っています..." : `「${a.title}」で返事する`}
                  </span>
                  <span style={{ display: "block", fontSize: 12.5, marginTop: 3, opacity: 0.85 }}>{KIOSK_EFFECT[a.action]}</span>
                </button>
              );
            })}
            {error && <div style={{ fontSize: 13, color: "#a84238", margin: "4px 0 12px", lineHeight: 1.7 }}>{error}</div>}
            <div style={{ marginTop: 8 }}>{adminLink}</div>
          </>
        )}
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#faf8f4", display: "flex", flexDirection: "column", alignItems: "center", padding: "32px 16px", fontFamily: FONT_JP }}>
      <div style={{ width: "100%", maxWidth: 480 }}>
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.3em", color: "#a8a198", marginBottom: 8 }}>
            {info?.tenant_name || "mokuture+"}
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1d1a15", margin: 0 }}>来客への返事</h1>
        </div>
        {content}
      </div>
    </div>
  );
}
