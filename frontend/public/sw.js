/* mokuture+ Service Worker — push notifications & offline shell cache */
const CACHE = 'mokuture-v2';
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

  // 受付応答: 通知ボタンの すぐ伺います / 只今対応できません。
  // SW は JWT を持てないので payload の署名トークンで直接 POST する（ウィンドウは開かない）。
  if (e.action === 'accept' || e.action === 'decline') {
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

  const targetUrl = data.url ?? '/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const match = list.find((c) => c.url.includes(targetUrl) && 'focus' in c);
      if (match) return match.focus();
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
