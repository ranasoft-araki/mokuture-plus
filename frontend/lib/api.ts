const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function _fetch(path: string, init?: RequestInit, token?: string): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...init?.headers } });
}

// Singleton: prevents race condition when multiple requests expire simultaneously
let _pendingRefresh: Promise<string | null> | null = null;

async function _doRefresh(): Promise<string | null> {
  const { getRefreshToken, saveTokens, clearTokens } = await import("@/lib/auth");
  const rt = getRefreshToken();
  if (!rt) return null;
  const res = await _fetch("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (res.ok) {
    const { access_token, refresh_token } = await res.json();
    saveTokens(access_token, refresh_token);
    return access_token;
  }
  clearTokens();
  if (typeof window !== "undefined") window.location.href = "/login";
  return null;
}

async function request<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  let res = await _fetch(path, init, token);

  if (res.status === 401 && token) {
    // All concurrent 401s share one refresh attempt — prevents refresh token rotation conflict
    if (!_pendingRefresh) {
      _pendingRefresh = _doRefresh().finally(() => { _pendingRefresh = null; });
    }
    const newToken = await _pendingRefresh;
    if (!newToken) throw new Error("セッションが切れました。再ログインしてください。");
    res = await _fetch(path, init, newToken);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // Kiosk API (device token auth via X-Kiosk-Token header)
  getKioskSchedule: (kioskToken: string) =>
    request<KioskScheduleResponse>("/kiosk/schedule", { headers: { "X-Kiosk-Token": kioskToken } }),
  createKioskReception: (kioskToken: string, body: ReceptionCreate) =>
    request("/kiosk/reception", { method: "POST", body: JSON.stringify(body), headers: { "X-Kiosk-Token": kioskToken } }),
  verifyKioskPin: (pinCode: string) =>
    request<{ device_token: string }>("/kiosk/verify-pin", { method: "POST", body: JSON.stringify({ pin_code: pinCode }) }),

  // Device management (admin)
  listDevices: (token: string) =>
    request<Device[]>("/devices", {}, token),
  createDevice: (token: string, name: string) =>
    request<Device & { token: string; pin_code: string; pin_expires_minutes: number }>("/devices", { method: "POST", body: JSON.stringify({ name }) }, token),
  deleteDevice: (token: string, id: string) =>
    request(`/devices/${id}`, { method: "DELETE" }, token),

  // Auth
  register: (body: { tenant_name: string; tenant_slug: string; email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  // Settings
  getTenantSettings: (token: string) =>
    request<TenantSettings>("/settings", {}, token),
  updateTenantSettings: (token: string, body: { brand_color?: string; font?: string }) =>
    request<TenantSettings>("/settings", { method: "PATCH", body: JSON.stringify(body) }, token),
  getLogoUploadUrl: (token: string, filename: string, mime_type: string) =>
    request<{ upload_url: string; public_url: string }>("/settings/logo-upload-url", { method: "POST", body: JSON.stringify({ filename, mime_type }) }, token),
  confirmLogoUpload: (token: string, logo_url: string) =>
    request<TenantSettings>("/settings/logo", { method: "PATCH", body: JSON.stringify({ logo_url }) }, token),

  // Content
  uploadMedia: async (token: string, file: File): Promise<MediaItem> => {
    // Step 1: Get presigned PUT URL from backend
    const urlData = await api.getMediaUploadUrl(token, file.name, file.type);

    // Step 2: PUT file directly to R2 (no auth header — presigned URL already contains credentials)
    const putRes = await fetch(urlData.upload_url, {
      method: "PUT",
      headers: { "Content-Type": file.type },
      body: file,
    });
    if (!putRes.ok) {
      throw new Error(`ストレージへのアップロードに失敗しました (${putRes.status})`);
    }

    // Step 3: Register metadata in DB
    return api.registerMedia(token, {
      media_id: urlData.media_id,
      filename: file.name,
      mime_type: file.type,
      url: urlData.public_url,
      size_bytes: file.size,
    });
  },
  getMediaUploadUrl: (token: string, filename: string, mime_type: string) =>
    request<MediaUploadUrlResponse>("/content/media/upload-url", { method: "POST", body: JSON.stringify({ filename, mime_type }) }, token),
  registerMedia: (token: string, body: object) =>
    request<MediaItem>("/content/media", { method: "POST", body: JSON.stringify(body) }, token),
  listMedia: (token: string, type?: string) =>
    request<MediaItem[]>(`/content/media${type ? `?type=${type}` : ""}`, {}, token),
  deleteMedia: (token: string, id: string) =>
    request(`/content/media/${id}`, { method: "DELETE" }, token),
  listPlaylists: (token: string) =>
    request<Playlist[]>("/content/playlists", {}, token),
  createPlaylist: (token: string, name: string) =>
    request<Playlist>("/content/playlists", { method: "POST", body: JSON.stringify({ name }) }, token),
  updatePlaylistItems: (token: string, playlistId: string, items: { media_id: string; display_order: number; duration_sec: number }[]) =>
    request("/content/playlists/" + playlistId + "/items", { method: "PUT", body: JSON.stringify(items) }, token),
  deletePlaylist: (token: string, id: string) =>
    request("/content/playlists/" + id, { method: "DELETE" }, token),
  listSchedules: (token: string) =>
    request<Schedule[]>("/content/schedules", {}, token),
  createSchedule: (token: string, body: { playlist_id: string; day_of_week: number; start_time: string; end_time: string }) =>
    request<{ id: string }>("/content/schedules", { method: "POST", body: JSON.stringify(body) }, token),
  deleteSchedule: (token: string, id: string) =>
    request("/content/schedules/" + id, { method: "DELETE" }, token),
  currentSchedule: (token: string) =>
    request<{ playlist_id: string | null }>("/content/schedules/current", {}, token),

  // Reception
  createReception: (token: string, body: ReceptionCreate) =>
    request<ReceptionLog>("/reception", { method: "POST", body: JSON.stringify(body) }, token),
  listReception: (token: string) =>
    request<ReceptionLog[]>("/reception", {}, token),
  todayStats: (token: string) =>
    request<{ date: string; count: number }>("/reception/stats/today", {}, token),

  // Lockers
  listLockers: (token: string) =>
    request<Locker[]>("/lockers", {}, token),
  unlockLocker: (token: string, id: string) =>
    request(`/lockers/${id}/unlock`, { method: "POST" }, token),
  lockLocker: (token: string, id: string) =>
    request(`/lockers/${id}/lock`, { method: "POST" }, token),

  // Push notifications (admin)
  getPushVapidKey: (token: string) =>
    request<{ public_key: string | null }>("/notifications/push/vapid-public-key", {}, token),
  setupPushVapid: (token: string) =>
    request<{ public_key: string }>("/notifications/push/setup", { method: "POST" }, token),
  subscribePush: (token: string, body: { endpoint: string; p256dh: string; auth: string }) =>
    request("/notifications/push/subscribe", { method: "POST", body: JSON.stringify(body) }, token),
  listPushSubscriptions: (token: string) =>
    request<PushSubscriptionInfo[]>("/notifications/push/subscriptions", {}, token),
  deletePushSubscription: (token: string, endpoint: string) =>
    request("/notifications/push/unsubscribe", { method: "DELETE", body: JSON.stringify({ endpoint }) }, token),
  testPushNotification: (token: string) =>
    request<{ sent: number; total: number }>("/notifications/push/test", { method: "POST" }, token),
  regenerateVapid: (token: string) =>
    request<{ public_key: string; regenerated: boolean }>("/notifications/push/regenerate", { method: "POST" }, token),
};

export interface MediaUploadUrlResponse {
  media_id: string;
  upload_url: string;
  public_url: string;
  storage_key?: string;
}

export interface MediaItem {
  id: string;
  filename: string;
  mime_type: string;
  url: string;
  size_bytes: number;
  duration_sec: number | null;
  uploaded_at: string;
}

export interface Playlist {
  id: string;
  name: string;
  items: PlaylistItem[];
}

export interface PlaylistItem {
  id: string;
  media_id: string;
  display_order: number;
  duration_sec: number;
}

export interface ReceptionCreate {
  visitor_name: string;
  company?: string;
  purpose?: string;
  staff?: string;
  method?: string;
}

export interface ReceptionLog extends ReceptionCreate {
  id: string;
  state: string;
  created_at: string;
}

export interface Locker {
  id: string;
  door_number: number;
  state: string;
  last_unlocked_at: string | null;
  auto_relock_sec: number;
}

export interface Schedule {
  id: string;
  playlist_id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
}

export interface Device {
  id: string;
  name: string;
  last_seen_at: string | null;
  created_at: string;
}

export interface PushSubscriptionInfo {
  id: string;
  endpoint: string;
  display_endpoint: string;
  user_id: string | null;
  created_at: string;
}

export interface KioskMediaItem {
  id: string;
  url: string;
  mime_type: string;
  filename: string;
}

export interface KioskPlaylistItem {
  id: string;
  media_id: string;
  display_order: number;
  duration_sec: number;
  media: KioskMediaItem | null;
}

export interface TenantSettings {
  tenant_name: string;
  tenant_slug: string;
  brand_color: string;
  logo_url: string | null;
  font: string;
}

export interface KioskScheduleResponse {
  playlist: {
    id: string;
    name: string;
    items: KioskPlaylistItem[];
  } | null;
}
