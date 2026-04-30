/** Web Push subscription utilities */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export type PushStatus = "unsupported" | "insecure-context" | "ios-not-pwa" | "denied" | "granted" | "default";

/** Detect why push notifications may not be available on this device. */
export function getPushStatus(): PushStatus {
  // iOS non-PWA must be checked FIRST: on iOS Safari (non-standalone), the Push/Notification
  // APIs may be absent specifically because the app isn't installed — not because Safari
  // lacks support. Showing "unsupported" in that case is misleading.
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent.toLowerCase());
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as unknown as { standalone?: boolean }).standalone === true;
  if (isIOS && !isStandalone) return "ios-not-pwa";

  if (!window.isSecureContext) return "insecure-context";

  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return "unsupported";
  }
  return Notification.permission as "denied" | "granted" | "default";
}

/** Convert VAPID public key (base64url) to ArrayBuffer for PushManager.subscribe */
function urlBase64ToArrayBuffer(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const buf = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return buf;
}

/** Fetch VAPID public key from the backend (returns null if not configured). */
export async function fetchVapidPublicKey(authToken: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/notifications/push/vapid-public-key`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.public_key ?? null;
  } catch {
    return null;
  }
}

/** Request notification permission and subscribe to push. Returns the subscription or null on failure. */
export async function requestAndSubscribe(vapidPublicKey: string): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return null;

  try {
    const registration = await navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    if (existing) return existing;

    return await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToArrayBuffer(vapidPublicKey),
    });
  } catch (err) {
    console.warn("Push subscribe failed:", err);
    return null;
  }
}

/** Send push subscription to backend (upsert). */
export async function sendSubscriptionToServer(authToken: string, sub: PushSubscription): Promise<boolean> {
  try {
    const json = sub.toJSON();
    const res = await fetch(`${API_BASE}/notifications/push/subscribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
      body: JSON.stringify({
        endpoint: sub.endpoint,
        p256dh: json.keys?.p256dh ?? "",
        auth: json.keys?.auth ?? "",
      }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Unsubscribe from push and remove from backend. */
export async function unsubscribeFromPush(authToken: string): Promise<boolean> {
  if (!("serviceWorker" in navigator)) return false;
  try {
    const registration = await navigator.serviceWorker.ready;
    const sub = await registration.pushManager.getSubscription();
    if (!sub) return true;

    const endpoint = sub.endpoint;
    await sub.unsubscribe();

    await fetch(`${API_BASE}/notifications/push/unsubscribe`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
      body: JSON.stringify({ endpoint }),
    });
    return true;
  } catch {
    return false;
  }
}

/** Check if current browser is already subscribed. */
export async function getCurrentPushSubscription(): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  try {
    const registration = await navigator.serviceWorker.ready;
    return await registration.pushManager.getSubscription();
  } catch {
    return null;
  }
}
