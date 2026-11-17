"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { consumeProxyHandoff, getProxyEndReason, purgeStaleProxyHandoff } from "@/lib/auth";

// 代理ログイン(運営・代理店が顧客の管理画面を別タブで開く)の受け取り口。運営・代理店の両方がここを通る。
//
// 開く側は一時キーを localStorage に置き、`/{tenant}/admin?proxy=1` を新しいタブで開く。
// このタブは一時キーを1回だけ使い、トークンをこのタブの sessionStorage だけに置く(lib/auth.ts)。
//
// 子の effect は親の effect より先に走るため、受け取る前に子を描くと、最初の通信が開いた側の
// ログインのまま走ってしまう。そこで管理画面(/admin 以下)では、この effect で受け取りを終えるまで
// 子を描かない(最初の1回だけ何も描かない)。`?proxy=` の値はキー名として使わない(印としてだけ見る)。

// expired / start_failed は案内を出して子を描かない状態
type Phase = "init" | "ready" | "expired" | "start_failed";

const MESSAGES: Record<"expired" | "start_failed", string> = {
  expired: "代理ログインの有効時間が切れました。このタブを閉じて、もう一度「代理ログイン」を押してください。",
  start_failed: "代理ログインを開始できませんでした（受け渡しの有効時間が過ぎたか、すでに使われています）。このタブを閉じて、もう一度「代理ログイン」を押してください。",
};

export default function ProxyLoginHandler({
  tenant,
  children,
}: {
  tenant: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const [phase, setPhase] = useState<Phase>("init");

  const isAdminPath = pathname === `/${tenant}/admin` || pathname.startsWith(`/${tenant}/admin/`);

  useEffect(() => {
    let next: Phase = "ready";
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.has("proxy") && isAdminPath) {
        consumeProxyHandoff(tenant);
        // 受け取りに成功したら URL から印を外す(再読み込みで受け取り直さない)。失敗時は残す。
        if (!getProxyEndReason()) {
          params.delete("proxy");
          const qs = params.toString();
          window.history.replaceState(window.history.state, "", window.location.pathname + (qs ? `?${qs}` : ""));
        }
      }
      // 使われずに残った古い一時キー(期限切れ・以前の版のもの)を片付ける
      purgeStaleProxyHandoff();
      const reason = getProxyEndReason();
      if (reason) next = reason;
    } catch {
      // ストレージが使えない環境では代理ログインは成立しない。通常どおり描く。
    }
    // 受け取りを同期で終えてから子を描く(上のコメント参照)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhase(next);
  // 受け取りはタブを開いた最初の1回だけ
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === "expired" || phase === "start_failed") return <ProxyEndedNotice message={MESSAGES[phase]} />;
  if (phase === "init" && isAdminPath) return null;
  return <>{children}</>;
}

function ProxyEndedNotice({ message }: { message: string }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "0 16px", background: "#faf8f4" }}>
      <div style={{ maxWidth: 440, width: "100%", background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 12, padding: "28px 28px 24px", fontFamily: '"Noto Sans JP", "Inter", system-ui, sans-serif', color: "#2d2a24", fontSize: 14, lineHeight: 1.7 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>代理ログイン</div>
        <p style={{ margin: 0 }}>{message}</p>
      </div>
    </div>
  );
}
