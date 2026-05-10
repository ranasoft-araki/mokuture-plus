/* mokuture+ Service Worker — push notifications & offline shell cache */
const CACHE = 'mokuture-v1';
const SHELL = ['/', '/icons/icon.svg', '/manifest.json'];

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

  const options = {
    body: payload.body,
    icon: '/icons/icon.svg',
    badge: '/icons/icon.svg',
    tag: payload.tag,
    renotify: true,
    data: { url: payload.url },
    vibrate: [200, 100, 200, 100, 200],
    actions: [
      { action: 'open', title: '確認する' },
      { action: 'dismiss', title: '閉じる' },
    ],
  };

  badgeCount = typeof payload.badge === 'number' ? payload.badge : badgeCount + 1;
  e.waitUntil(
    self.registration.showNotification(payload.title, options).then(() => {
      if ('setAppBadge' in navigator) return navigator.setAppBadge(badgeCount).catch(() => {});
    })
  );
});

// ── Notification click: focus or open window ───────────────────────────
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  badgeCount = 0;
  if ('clearAppBadge' in navigator) navigator.clearAppBadge().catch(() => {});

  if (e.action === 'dismiss') return;

  const targetUrl = e.notification.data?.url ?? '/';
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
