"use client";

// Google カレンダー連携の戻り先(GOOGLE_REDIRECT_URI)。Google がここへ ?code=&state= を付けて戻す。
// ログイン中の管理者の JWT 付きで API に渡し、結果を「カレンダー連携」へ ?google=<結果> で知らせる。
// (未認証の API で保存しないのは、他人に認可 URL を踏ませてその人のカレンダーを自分のテナントへ
//  つながせる手を塞ぐため。→ backend/app/api/calendar_integration.py)

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { getAccessToken, getSlug } from "@/lib/auth";

export default function GoogleCalendarCallbackPage() {
  const [message, setMessage] = useState("Google アカウントの連携を仕上げています…");

  const started = useRef(false);

  useEffect(() => {
    // 開発時の StrictMode は effect を 2 回動かす。2 回目は URL からコードが消えているので走らせない。
    if (started.current) return;
    started.current = true;
    const q = new URLSearchParams(window.location.search);
    const code = q.get("code") ?? "";
    const state = q.get("state") ?? "";
    const error = q.get("error") ?? "";
    // 認可コードを URL に残さない(履歴・共有で漏れないように)
    window.history.replaceState({}, "", window.location.pathname);

    const token = getAccessToken();
    const slug = getSlug();
    if (!token || !slug) {
      setMessage("ログインが切れています。mokuture+ にログインしてから、「カレンダー連携」でもう一度「Googleアカウントで連携」を押してください。");
      return;
    }
    api.completeGoogleCalendarOAuth(token, { code, state, error })
      .then((r) => window.location.replace(`/${slug}/admin/calendar?google=${encodeURIComponent(r.result)}`))
      .catch(() => window.location.replace(`/${slug}/admin/calendar?google=error`));
  }, []);

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f4f1ea", padding: 16 }}>
      <div style={{ maxWidth: 420, background: "#fffefb", border: "1px solid #efece5", borderRadius: 12, padding: "24px 28px", fontSize: 13.5, color: "#2d2a24", lineHeight: 1.8, fontFamily: '"Noto Sans JP", system-ui, sans-serif' }}>
        {message}
      </div>
    </div>
  );
}
