// 管理画面のニアリアルタイム連動クライアント（Server-Sent Events）。
//
// backend の GET /events/stream へ1本の EventSource を張り、受付/ロッカーの変化が push される
// たびに onEvent を呼ぶ。呼び出し側はイベントを受けて該当リストだけ即再取得する。
//
// 認証: EventSource はヘッダを送れないため、接続の直前に通常の API(Bearer 認証・トークン更新つき)で
// 短時間だけ有効なチケットを受け取り、それを `?ticket=` で渡す。アクセストークン自体は URL に載せない
// (URL はアクセスログ等に残りやすいため)。チケットは短命なので、張り直すたびに取り直す。
// EventSource 任せの自動再接続は使わない(古いチケット・失効トークンで同じ失敗を繰り返すため)。
// 恒久的に切れた場合に備え、呼び出し側は低頻度のポーリング・フォールバックを併用すること。
//
// ペイロードは { type: "reception" | "locker" } の型マーカーのみ（秘密情報は運ばない）。

import { API_BASE, ApiError, api, ensureFreshToken } from "@/lib/api";

export type RealtimeEvent = { type: string;[k: string]: unknown };

// 再接続の待ち時間。失敗が続くほど延ばし(指数バックオフ)、サーバへ詰めかけないようにする。
const RECONNECT_BASE_MS = 3000;
const RECONNECT_MAX_MS = 60_000;
// この時間以上つながっていたら「正常に使えていた」とみなし、待ち時間を最初に戻す
// (開いた直後に切れる状態で 3 秒ごとの張り直しを続けないため)。
const STABLE_MS = 30_000;

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
  let attempts = 0;

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    const base = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** Math.min(attempts, 5));
    attempts += 1;
    const delay = base * (0.8 + Math.random() * 0.4); // 複数タブが同時に張り直さないよう少しずらす
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void connect();
    }, delay);
  };

  // 接続先の URL を作る。チケットが取れなければ null(少し待って再試行)。
  const buildUrl = async (): Promise<string | null> => {
    const token = await ensureFreshToken();
    if (closed || !token) return null;
    try {
      const { ticket } = await api.getEventsTicket(token);
      if (!ticket) return null;
      return `${API_BASE}/events/stream?ticket=${encodeURIComponent(ticket)}`;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // 移行期間だけの経路: チケットの API がまだ無い backend では、この1回だけ従来の
        // アクセストークン方式で張る。次に張り直すときはまたチケットから試す。
        // backend の切り替えが済んだら、この分岐ごと消すこと。
        const fresh = await ensureFreshToken();
        if (closed || !fresh) return null;
        return `${API_BASE}/events/stream?token=${encodeURIComponent(fresh)}`;
      }
      return null;
    }
  };

  const connect = async () => {
    if (closed) return;
    let url: string | null = null;
    try {
      url = await buildUrl();
    } catch {
      url = null;
    }
    if (closed) return;
    if (!url) {
      // まだセッションが無い/チケットが取れない(一時的な失敗を含む)。待って再試行。
      scheduleReconnect();
      return;
    }
    let openedAt = 0;
    es = new EventSource(url);
    es.onopen = () => { openedAt = Date.now(); };
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data && typeof data.type === "string") onEvent(data as RealtimeEvent);
      } catch {
        /* keepalive/非JSON は無視 */
      }
    };
    es.onerror = () => {
      // 一時切断でも認証切れでもここに来る。EventSource の自動再接続に任せず、
      // 一度閉じてから新しいチケットで張り直す。
      es?.close();
      es = null;
      if (openedAt && Date.now() - openedAt >= STABLE_MS) attempts = 0;
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
