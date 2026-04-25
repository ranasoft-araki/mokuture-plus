const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...init?.headers } });
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

  // Device management (admin)
  listDevices: (token: string) =>
    request<Device[]>("/devices", {}, token),
  createDevice: (token: string, name: string) =>
    request<Device & { token: string }>("/devices", { method: "POST", body: JSON.stringify({ name }) }, token),
  deleteDevice: (token: string, id: string) =>
    request(`/devices/${id}`, { method: "DELETE" }, token),

  // Auth
  register: (body: { tenant_name: string; tenant_slug: string; email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

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
  listPlaylists: (token: string) =>
    request<Playlist[]>("/content/playlists", {}, token),
  createPlaylist: (token: string, name: string) =>
    request("/content/playlists", { method: "POST", body: JSON.stringify({ name }) }, token),
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

export interface Device {
  id: string;
  name: string;
  last_seen_at: string | null;
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

export interface KioskScheduleResponse {
  playlist: {
    id: string;
    name: string;
    items: KioskPlaylistItem[];
  } | null;
}
