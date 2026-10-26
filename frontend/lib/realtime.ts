// 管理画面のニアリアルタイム連動クライアント（Server-Sent Events）。
//
// backend の GET /events/stream へ1本の EventSource を張り、受付/ロッカーの変化が push される
// たびに onEvent を呼ぶ。呼び出し側はイベントを受けて該当リストだけ即再取得する。EventSource は
// 一時的な切断では自動再接続するが、トークン失効時はサーバが 401 を返し続けて同じトークンで
// リトライし続けてしまうため、エラー時は張り直す前に必ずトークンをリフレッシュする。
// 恒久的に切れた場合に備え、呼び出し側は低頻度のポーリング・フォールバックを併用すること。
//
// ペイロードは { type: "reception" | "locker" } の型マーカーのみ（秘密情報は運ばない）。

import { API_BASE, ensureFreshToken } from "@/lib/api";

export type RealtimeEvent = { type: string;[k: string]: unknown };

// 接続が張れず onopen 前に落ち続ける時の再接続バックオフ。過剰な再接続を避ける。
const RECONNECT_MS = 3000;

/**
 * SSE を購読する。返り値の関数を呼ぶと購読を解除して接続を閉じる。
 * onEvent には backend が push した {type,...} が渡る（keepalive コメントは届かない）。
 */
export function subscribeRealtime(onEvent: (e: RealtimeEvent) => void): () => void {
  // SSR/ビルド時など EventSource が無い環境では何もしない（フォールバックのポーリングに任せる）。
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return () => {};
  }

  let es: EventSource | null = null;
  let closed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void connect();
    }, RECONNECT_MS);
  };

  const connect = async () => {
    if (closed) return;
    const token = await ensureFreshToken();
    if (closed) return;
    if (!token) {
      // まだセッションが無い/リフレッシュ不能。少し待って再試行。
      scheduleReconnect();
      return;
    }
    const url = `${API_BASE}/events/stream?token=${encodeURIComponent(token)}`;
    es = new EventSource(url);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data && typeof data.type === "string") onEvent(data as RealtimeEvent);
      } catch {
        /* keepalive/非JSON は無視 */
      }
    };
    es.onerror = () => {
      // 一時切断でもトークン失効でもここに来る。EventSource の自動再接続に任せず、
      // 一度閉じてからフレッシュなトークンで張り直す（失効時の 401 ループを断つ）。
      es?.close();
      es = null;
      scheduleReconnect();
    };
  };

  void connect();

  return () => {
    closed = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    es?.close();
    es = null;
  };
}
