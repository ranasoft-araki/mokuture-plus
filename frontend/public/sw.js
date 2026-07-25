/* mokuture+ Service Worker — push notifications & offline shell cache */
const CACHE = 'mokuture-v6';
const SHELL = ['/', '/icons/icon.svg', '/manifest.json'];

// 受付 OK/NG 応答の送信先フォールバック（プッシュ payload に decisionEndpoint が無い場合）
const DECISION_ENDPOINT_FALLBACK = 'https://mokuture-plus-api.onrender.com/api/reception/decision';

// Badge count — in-memory; resets on SW restart (acceptable trade-off)
let badgeCount = 0;

// ── Install: pre-cache shell ──────────────────────────────────────────
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

// ── Activate: claim clients, purge old caches ─────────────────────────
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API/dynamic, cache-first for shell ────────
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Skip non-GET and cross-origin (API calls, etc.)
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  // Cache-first for static assets
  if (url.pathname.startsWith('/icons/') || url.pathname === '/manifest.json') {
    e.respondWith(
      caches.match(e.request).then((cached) => cached ?? fetch(e.request))
    );
    return;
  }
  // 起動ゲート(/) は cache-first + 背景更新（stale-while-revalidate）。
  // / はインライン script で即 location.replace する軽量ゲートで、React を hydrate せず
  // 離脱するため、古いHTMLでもチャンクを実行せず＝ stale でも安全。起動時のネット往復を消す。
  // （遷移先の /login・/{tenant}/admin は下の network-first で常に fresh を取る＝チャンク不整合を防ぐ）
  if (url.pathname === '/') {
    e.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match('/');
        const network = fetch(e.request).then((res) => {
          if (res && res.ok) cache.put('/', res.clone());
          return res;
        }).catch(() => null);
        return cached || (await network) || Response.error();
      })
    );
    return;
  }
  // Network-first for pages
  e.respondWith(
    fetch(e.request).catch(async () => {
      const cached = await caches.match(e.request);
      return cached ?? Response.error();
    })
  );
});

// ── Push: show notification ────────────────────────────────────────────
self.addEventListener('push', (e) => {
  let payload = { title: 'mokuture+', body: '来客のお知らせ', url: '/', tag: 'reception' };
  try {
    if (e.data) payload = { ...payload, ...e.data.json() };
  } catch (_) {}

  // 受付応答プッシュ(kind==='reception_decision')は OK/NG アクションを出す。
  // それ以外(テスト通知等)は従来の 確認する/閉じる。
  const actions = Array.isArray(payload.actions) && payload.actions.length
    ? payload.actions
    : [
        { action: 'open', title: '確認する' },
        { action: 'dismiss', title: '閉じる' },
      ];

  const options = {
    body: payload.body,
    icon: '/icons/icon.svg',
    badge: '/icons/icon.svg',
    tag: payload.tag,
    renotify: true,
    data: {
      url: payload.url,
      kind: payload.kind,
      logId: payload.logId,
      decisionToken: payload.decisionToken,
      decisionEndpoint: payload.decisionEndpoint,
    },
    vibrate: [200, 100, 200, 100, 200],
    actions,
  };

  badgeCount = typeof payload.badge === 'number' ? payload.badge : badgeCount + 1;
  e.waitUntil(
    self.registration.showNotification(payload.title, options).then(() => {
      if ('setAppBadge' in navigator) return navigator.setAppBadge(badgeCount).catch(() => {});
    })
  );
});

// ── Notification click: OK/NG decision, or focus/open window ───────────
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  badgeCount = 0;
  if ('clearAppBadge' in navigator) navigator.clearAppBadge().catch(() => {});

  if (e.action === 'dismiss') return;

  const data = e.notification.data || {};

  // 受付応答: 通知ボタンの 受付 / 電話 / お断り。
  // SW は JWT を持てないので payload の署名トークンで直接 POST する（ウィンドウは開かない）。
  if (e.action === 'accept' || e.action === 'phone' || e.action === 'decline') {
    const endpoint = data.decisionEndpoint || DECISION_ENDPOINT_FALLBACK;
    if (data.decisionToken) {
      e.waitUntil(
        fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: data.decisionToken, decision: e.action }),
        }).catch(() => {})
      );
    }
    return;
  }

  // 通知本体タップ: 該当受付のモーダルを開く。
  // ・受付応答(reception_decision) → 対応モーダル(受付/電話/お断り)。postMessage(FOCUS_RECEPTION)。
  // ・置き配(delivery_dropoff)     → 詳細モーダル(解錠PINを大きく表示)。postMessage(FOCUS_DETAIL)。
  // 既に受付ログ画面が開いていればフォーカスして postMessage でモーダルを開かせ、無ければ
  // ?respond=/?detail=<id> 付き URL で新規に開く（画面側が query を読んでモーダルを自動表示）。
  // これらの通知の url はテナントUUIDをパスに含むが、管理者が実際に開くタブはスラッグURLのため、
  // /admin/reception サフィックスで既存タブを捕捉する（スラッグ/UUID どちらでもフォーカス＝新規タブ重複を防ぐ）。
  const targetUrl = data.url ?? '/';
  const logId = data.logId;
  const opensReception = data.kind === 'reception_decision' || data.kind === 'delivery_dropoff';
  const matchKey = opensReception ? '/admin/reception' : targetUrl.split('?')[0];
  const focusMsgType = data.kind === 'delivery_dropoff' ? 'FOCUS_DETAIL' : 'FOCUS_RECEPTION';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const match = list.find((c) => c.url.includes(matchKey) && 'focus' in c);
      if (match) {
        if (logId) match.postMessage({ type: focusMsgType, logId });
        return match.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});

// ── Message: clear badge from page context ────────────────────────────
self.addEventListener('message', (e) => {
  if (e.data?.type === 'CLEAR_BADGE') {
    badgeCount = 0;
    if ('clearAppBadge' in navigator) navigator.clearAppBadge().catch(() => {});
  }
});
