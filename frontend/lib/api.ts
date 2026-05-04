const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

async function _fetch(path: string, init?: RequestInit, token?: string): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...init?.headers } });
}

// Singleton: prevents race condition when multiple requests expire simultaneously
let _pendingRefresh: Promise<string | null> | null = null;

async function _doRefresh(): Promise<string | null> {
  const { getRefreshToken, refreshSaveTokens, clearTokens } = await import("@/lib/auth");
  const rt = getRefreshToken();
  if (!rt) return null;
  const res = await _fetch("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (res.ok) {
    const { access_token, refresh_token } = await res.json();
    refreshSaveTokens(access_token, refresh_token);
    return access_token;
  }
  clearTokens();
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
    let errorMsg: string;
    if (Array.isArray(err.detail)) {
      errorMsg = err.detail[0]?.msg ?? "Validation failed";
    } else {
      errorMsg = typeof err.detail === "string" ? err.detail : "Request failed";
    }
    throw new Error(errorMsg);
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
    request<{ device_token: string; device_name: string }>("/kiosk/verify-pin", { method: "POST", body: JSON.stringify({ pin_code: pinCode }) }),

  // Device management (admin)
  listDevices: (token: string) =>
    request<Device[]>("/devices", {}, token),
  createDevice: (token: string, name: string) =>
    request<Device & { token: string; pin_code: string; pin_expires_minutes: number }>("/devices", { method: "POST", body: JSON.stringify({ name }) }, token),
  deleteDevice: (token: string, id: string) =>
    request(`/devices/${id}`, { method: "DELETE" }, token),
  forceRefreshDevice: (token: string, deviceId: string): Promise<void> =>
    request(`/devices/${deviceId}/force-refresh`, { method: "POST" }, token),
  updateDevice: (token: string, deviceId: string, name: string) =>
    request<Device>(`/devices/${deviceId}`, { method: "PATCH", body: JSON.stringify({ name }) }, token),
  updateDeviceLocation: (token: string, deviceId: string, location: string | null) =>
    request<Device>(`/devices/${deviceId}`, { method: "PATCH", body: JSON.stringify({ location }) }, token),
  regenerateDevicePin: (token: string, deviceId: string) =>
    request<{ pin_code: string; expires_minutes: number }>(`/devices/${deviceId}/pin`, { method: "POST" }, token),

  // Auth
  register: (body: { tenant_name: string; tenant_slug: string; email: string; password: string }) =>
    request<AuthResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  operatorLogin: (email: string, password: string) =>
    request<AuthResponse>("/auth/operator/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  resellerLogin: (reseller_id: string, password: string) =>
    request<AuthResponse>("/auth/reseller/login", { method: "POST", body: JSON.stringify({ reseller_id, password }) }),

  // Operator API (運営)
  getOperatorStats: (token: string) =>
    request<OperatorStats>("/operator/stats", {}, token),
  listOperatorTenants: (token: string, params?: { reseller_id?: string; q?: string; status?: string; page?: number; page_size?: number; limit?: number; offset?: number }) => {
    const p = new URLSearchParams();
    if (params?.reseller_id) p.set("reseller_id", params.reseller_id);
    if (params?.q) p.set("q", params.q);
    if (params?.status) p.set("status", params.status);
    if (params?.page != null) {
      p.set("page", String(params.page));
      if (params?.page_size != null) p.set("page_size", String(params.page_size));
    } else if (params?.offset != null && params?.limit != null) {
      // offset-based -> convert to page-based
      p.set("page", String(Math.floor(params.offset / params.limit) + 1));
      p.set("page_size", String(params.limit));
    } else if (params?.limit != null) {
      p.set("page_size", String(params.limit));
      p.set("page", "1");
    }
    const qs = p.toString();
    return request<PaginatedResponse<OperatorTenant>>(`/operator/tenants${qs ? `?${qs}` : ""}`, {}, token);
  },
  createOperatorTenant: (token: string, body: { name: string; slug: string; reseller_id?: string; admin_email: string; admin_password: string }) =>
    request<{ id: string; slug: string; name: string }>("/operator/tenants", { method: "POST", body: JSON.stringify(body) }, token),
  deleteOperatorTenant: (token: string, id: string) =>
    request(`/operator/tenants/${id}`, { method: "DELETE" }, token),
  listResellers: (token: string) =>
    request<OperatorTenant[]>("/operator/resellers", {}, token),
  createReseller: (token: string, body: { name: string; slug: string; admin_email: string; admin_password: string }) =>
    request<{ id: string; slug: string; name: string }>("/operator/resellers", { method: "POST", body: JSON.stringify(body) }, token),
  deleteReseller: (token: string, id: string) =>
    request(`/operator/resellers/${id}`, { method: "DELETE" }, token),
  createOperatorUser: (token: string, body: { tenant_id: string; email: string; password: string; role: string }) =>
    request<OperatorUser>("/operator/users", { method: "POST", body: JSON.stringify(body) }, token),
  deleteOperatorUser: (token: string, userId: string): Promise<void> =>
    request(`/operator/users/${userId}`, { method: "DELETE" }, token),
  updateOperatorUserRole: (token: string, userId: string, role: string) =>
    request<OperatorUser>(`/operator/users/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) }, token),
  listOperatorUsers: (token: string, params?: { tenant_id?: string; role?: string; reseller_id?: string; q?: string; page?: number; page_size?: number }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.role) p.set("role", params.role);
    if (params?.reseller_id) p.set("reseller_id", params.reseller_id);
    if (params?.q) p.set("q", params.q);
    if (params?.page != null) p.set("page", String(params.page));
    if (params?.page_size != null) p.set("page_size", String(params.page_size));
    const qs = p.toString();
    return request<PaginatedResponse<OperatorUser>>(`/operator/users${qs ? `?${qs}` : ""}`, {}, token);
  },
  listOperatorDevices: (token: string, params?: { q?: string; tenant_id?: string; reseller_id?: string; status?: string; page?: number; page_size?: number }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.reseller_id) p.set("reseller_id", params.reseller_id);
    if (params?.status) p.set("status", params.status);
    if (params?.q) p.set("q", params.q);
    if (params?.page != null) p.set("page", String(params.page));
    if (params?.page_size != null) p.set("page_size", String(params.page_size));
    const qs = p.toString();
    return request<PaginatedResponse<OperatorDevice>>(`/operator/devices${qs ? `?${qs}` : ""}`, {}, token);
  },
  listOperatorReception: (token: string, params?: { tenant_id?: string; reseller_id?: string; q?: string; status?: string; method?: string; date_from?: string; date_to?: string; offset?: number; limit?: number }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.reseller_id) p.set("reseller_id", params.reseller_id);
    if (params?.q) p.set("q", params.q);
    if (params?.status) p.set("status", params.status);
    if (params?.method) p.set("method", params.method);
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    if (params?.offset != null) p.set("offset", String(params.offset));
    if (params?.limit != null) p.set("limit", String(params.limit));
    const qs = p.toString();
    return request<OperatorReceptionItem[]>(`/operator/reception${qs ? `?${qs}` : ""}`, {}, token);
  },
  updateOperatorReceptionLog: (token: string, logId: string, updates: { state?: string; staff_notes?: string }): Promise<OperatorReceptionItem> =>
    request<OperatorReceptionItem>(`/operator/reception/${logId}`, { method: "PATCH", body: JSON.stringify(updates) }, token),
  bulkDeleteOperatorReception: (token: string, ids: string[], tenant_id?: string): Promise<{ deleted: number }> =>
    request("/operator/reception/bulk", { method: "DELETE", body: JSON.stringify({ ids, tenant_id: tenant_id ?? null }) }, token),
  exportOperatorReceptionCsv: async (token: string, params?: { tenant_id?: string; reseller_id?: string; q?: string; status?: string; date_from?: string; date_to?: string }): Promise<Blob> => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.reseller_id) p.set("reseller_id", params.reseller_id);
    if (params?.q) p.set("q", params.q);
    if (params?.status) p.set("status", params.status);
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    const qs = p.toString();
    const headers: Record<string, string> = { "Content-Type": "application/json", "Authorization": `Bearer ${token}` };
    const res = await fetch(`${API_BASE}/operator/reception/export.csv${qs ? `?${qs}` : ""}`, { headers });
    if (!res.ok) throw new Error("CSV export failed");
    return res.blob();
  },
  emergencyBroadcast: (token: string, message: string, tenant_ids?: string[]) =>
    request<{ updated_tenants: number; message: string }>("/operator/broadcast", { method: "POST", body: JSON.stringify({ message, tenant_ids }) }, token),
  proxyLoginAsTenant: (token: string, tenantId: string) =>
    request<{ access_token: string; tenant_slug: string; tenant_name: string }>(`/operator/tenants/${tenantId}/proxy-login`, { method: "POST" }, token),
  suspendTenant: (token: string, tenantId: string, suspended: boolean) =>
    request<{ ok: boolean; tenant_id: string; is_suspended: boolean }>(`/operator/tenants/${tenantId}/suspend`, { method: "PATCH", body: JSON.stringify({ suspended }) }, token),
  updateTenantNotes: (token: string, tenantId: string, notes: string): Promise<void> =>
    request(`/operator/tenants/${tenantId}/notes`, { method: "PATCH", body: JSON.stringify({ notes }) }, token),
  updateTenantReseller: (token: string, tenantId: string, resellerId: string | null) =>
    request(`/operator/tenants/${tenantId}/reseller`, { method: "PATCH", body: JSON.stringify({ reseller_id: resellerId }) }, token),

  // Reseller API (代理店)
  getResellerStats: (token: string) =>
    request<ResellerStats>("/reseller/stats", {}, token),
  listResellerCustomers: (token: string, params?: { q?: string; offset?: number; limit?: number }) => {
    const p = new URLSearchParams();
    if (params?.q) p.set("q", params.q);
    if (params?.offset != null) p.set("offset", String(params.offset));
    if (params?.limit != null) p.set("limit", String(params.limit));
    const qs = p.toString();
    return request<OperatorTenant[]>(`/reseller/customers${qs ? `?${qs}` : ""}`, {}, token);
  },
  createResellerCustomer: (token: string, body: { name: string; slug: string; admin_email: string; admin_password: string }) =>
    request<{ id: string; slug: string; name: string }>("/reseller/customers", { method: "POST", body: JSON.stringify(body) }, token),
  deleteResellerCustomer: (token: string, id: string) =>
    request(`/reseller/customers/${id}`, { method: "DELETE" }, token),
  proxyLoginAsCustomer: (token: string, tenantId: string) =>
    request<{ access_token: string; refresh_token: string; tenant_slug: string; role: string }>(`/reseller/customers/${tenantId}/proxy-login`, { method: "POST" }, token),
  listResellerDevices: (token: string, params?: { tenant_id?: string; status?: string; q?: string }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.status) p.set("status", params.status);
    if (params?.q) p.set("q", params.q);
    const qs = p.toString();
    return request<OperatorDevice[]>(`/reseller/devices${qs ? `?${qs}` : ""}`, {}, token);
  },
  listResellerUsers: (token: string, params?: { tenant_id?: string; role?: string; q?: string }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.role) p.set("role", params.role);
    if (params?.q) p.set("q", params.q);
    const qs = p.toString();
    return request<OperatorUser[]>(`/reseller/users${qs ? `?${qs}` : ""}`, {}, token);
  },
  listResellerReception: (token: string, params?: { tenant_id?: string; q?: string; status?: string; date_from?: string; date_to?: string; offset?: number; limit?: number }) => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.q) p.set("q", params.q);
    if (params?.status) p.set("status", params.status);
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    if (params?.offset != null) p.set("offset", String(params.offset));
    if (params?.limit != null) p.set("limit", String(params.limit));
    const qs = p.toString();
    return request<ResellerReceptionItem[]>(`/reseller/reception${qs ? `?${qs}` : ""}`, {}, token);
  },
  exportResellerReceptionCsv: async (token: string, params?: { tenant_id?: string; q?: string; status?: string; date_from?: string; date_to?: string }): Promise<Blob> => {
    const p = new URLSearchParams();
    if (params?.tenant_id) p.set("tenant_id", params.tenant_id);
    if (params?.q) p.set("q", params.q);
    if (params?.status) p.set("status", params.status);
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    const qs = p.toString();
    const headers: Record<string, string> = { "Content-Type": "application/json", "Authorization": `Bearer ${token}` };
    const res = await fetch(`${API_BASE}/reseller/reception/export.csv${qs ? `?${qs}` : ""}`, { headers });
    if (!res.ok) throw new Error("CSV export failed");
    return res.blob();
  },

  getTenantStats: (token: string) =>
    request<TenantStats>("/settings/stats", {}, token),

  // Settings
  getTenantSettings: (token: string) =>
    request<TenantSettings>("/settings", {}, token),
  updateTenantSettings: (token: string, body: {
    name?: string; brand_color?: string; font?: string;
    kiosk_welcome_message?: string; kiosk_sub_message?: string;
    kiosk_calling_message?: string; kiosk_complete_message?: string;
    kiosk_idle_timeout_sec?: number; kiosk_complete_timeout_sec?: number;
    logo_pos_x?: number; logo_pos_y?: number; logo_width_pct?: number;
    kiosk_style?: string; staff_list?: string | null; purpose_list?: string | null;
  }) =>
    request<TenantSettings>("/settings", { method: "PATCH", body: JSON.stringify(body) }, token),
  getPublicTenantSettings: (tenantSlug: string) =>
    request<PublicTenantSettings>(`/settings/public/${tenantSlug}`),
  getLogoUploadUrl: (token: string, filename: string, mime_type: string) =>
    request<{ upload_url: string; public_url: string }>("/settings/logo-upload-url", { method: "POST", body: JSON.stringify({ filename, mime_type }) }, token),
  confirmLogoUpload: (token: string, logo_url: string) =>
    request<TenantSettings>("/settings/logo", { method: "PATCH", body: JSON.stringify({ logo_url }) }, token),
  deleteLogo: (token: string) =>
    request<TenantSettings>("/settings/logo", { method: "DELETE" }, token),

  // Content
  uploadMedia: async (token: string, file: File): Promise<MediaItem> => {
    const urlData = await api.getMediaUploadUrl(token, file.name, file.type);
    const putRes = await fetch(urlData.upload_url, {
      method: "PUT",
      headers: { "Content-Type": file.type },
      body: file,
    });
    if (!putRes.ok) {
      throw new Error(`ストレージへのアップロードに失敗しました (${putRes.status})`);
    }
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
  reorderPlaylistItems: (token: string, playlistId: string, items: { id: string; sort_order: number }[]) =>
    request<{ ok: boolean }>("/content/playlists/" + playlistId + "/items/reorder", { method: "PATCH", body: JSON.stringify({ items }) }, token),
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
  updateReceptionLog: (token: string, logId: string, updates: { state?: string; staff_notes?: string }) =>
    request<ReceptionLog>(`/reception/${logId}`, { method: "PATCH", body: JSON.stringify(updates) }, token),
  exportContactsCsv: async (token: string): Promise<Blob> => {
    const res = await _fetch("/reception/contacts.csv", {}, token);
    if (!res.ok) throw new Error("Export failed");
    return res.blob();
  },
  exportReceptionCsv: async (token: string, params?: { q?: string; status?: string; date_from?: string; date_to?: string; method?: string }): Promise<Blob> => {
    const p = new URLSearchParams();
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    if (params?.method) p.set("method", params.method);
    const qs = p.toString();
    const headers: Record<string, string> = { "Content-Type": "application/json", "Authorization": `Bearer ${token}` };
    const res = await fetch(`${API_BASE}/reception/export.csv${qs ? `?${qs}` : ""}`, { headers });
    if (!res.ok) throw new Error("CSV export failed");
    return res.blob();
  },
  deleteReceptionLog: (token: string, logId: string): Promise<void> =>
    request(`/reception/${logId}`, { method: "DELETE" }, token),
  bulkDeleteReceptionLogs: (token: string, ids: string[]): Promise<{ deleted: number }> =>
    request("/reception/bulk", { method: "DELETE", body: JSON.stringify({ ids }) }, token),
  todayStats: (token: string) =>
    request<{ date: string; count: number }>("/reception/stats/today", {}, token),
  getReceptionDailyStats: (token: string) =>
    request<ReceptionDailyStats>("/reception/daily-stats", {}, token),
  getVisitorHistory: (token: string, name: string) =>
    request<{ count: number; first_visit: string | null; last_visit: string | null }>(`/reception/visitor-history?name=${encodeURIComponent(name)}`, {}, token),
  getOperatorReceptionDailyStats: (token: string, days = 14) =>
    request<DailyStatsResponse>(`/operator/reception/daily-stats?days=${days}`, {}, token),
  getResellerReceptionDailyStats: (token: string, days = 14) =>
    request<DailyStatsResponse>(`/reseller/reception/daily-stats?days=${days}`, {}, token),
  getResellerDailyStats: (token: string) =>
    request<ReceptionDailyStats>("/reseller/reception/daily-stats", {}, token),

  // Lockers
  listLockers: (token: string) =>
    request<Locker[]>("/lockers", {}, token),
  unlockLocker: (token: string, id: string) =>
    request(`/lockers/${id}/unlock`, { method: "POST" }, token),
  lockLocker: (token: string, id: string) =>
    request(`/lockers/${id}/lock`, { method: "POST" }, token),
  openLocker: (token: string, lockerId: string) =>
    request<Locker>(`/lockers/${lockerId}/open`, { method: "POST" }, token),
  closeLocker: (token: string, lockerId: string) =>
    request<Locker>(`/lockers/${lockerId}/close`, { method: "POST" }, token),

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

  // Notification settings
  getNotificationSettings: (token: string) =>
    request<Record<string, Record<string, string>>>("/notifications/settings", {}, token),
  updateSlackSettings: (token: string, webhook_url: string) =>
    request("/notifications/settings/slack", { method: "PUT", body: JSON.stringify({ webhook_url }) }, token),
  updateChatworkSettings: (token: string, api_token: string, room_id: string) =>
    request("/notifications/settings/chatwork", { method: "PUT", body: JSON.stringify({ api_token, room_id }) }, token),
  testSlackNotification: (token: string) =>
    request<{ ok: boolean }>("/notifications/test/slack", { method: "POST" }, token),
  testChatworkNotification: (token: string) =>
    request<{ ok: boolean }>("/notifications/test/chatwork", { method: "POST" }, token),
  testNotification: (token: string, type: string): Promise<{ ok: boolean; error?: string; sent?: number }> => {
    if (type === "push") {
      return request<{ sent: number; total: number }>("/notifications/push/test", { method: "POST" }, token)
        .then((r) => ({ ok: r.sent > 0, sent: r.sent }))
        .catch((e: unknown) => ({ ok: false, error: e instanceof Error ? e.message : String(e) }));
    }
    return request<{ ok: boolean }>(`/notifications/test/${type}`, { method: "POST" }, token)
      .catch((e: unknown) => ({ ok: false, error: e instanceof Error ? e.message : String(e) }));
  },
  updateWebhookSettings: (token: string, webhook_url: string) =>
    request("/notifications/settings/webhook", { method: "PUT", body: JSON.stringify({ webhook_url }) }, token),
  testWebhookNotification: (token: string) =>
    request<{ ok: boolean }>("/notifications/test/webhook", { method: "POST" }, token),

  // Lockers (extended)
  createLocker: (token: string, data: { name: string; gpio_pin: number }) =>
    request<Locker>("/lockers", { method: "POST", body: JSON.stringify({ name: data.name, gpio_pin: data.gpio_pin }) }, token),
  deleteLocker: (token: string, id: string) =>
    request(`/lockers/${id}`, { method: "DELETE" }, token),

  // OTA
  forceKioskUpdate: (token: string) =>
    request<{ ok: boolean; forced_at: string }>("/settings/kiosk-force-push", { method: "POST" }, token),

  // Visitor appointments (admin)
  listAppointments: (token: string, params?: { status?: string; date_from?: string; date_to?: string }) => {
    const p = new URLSearchParams();
    if (params?.status) p.set("status", params.status);
    if (params?.date_from) p.set("date_from", params.date_from);
    if (params?.date_to) p.set("date_to", params.date_to);
    const qs = p.toString();
    return request<VisitorAppointment[]>(`/appointments${qs ? `?${qs}` : ""}`, {}, token);
  },
  createAppointment: (token: string, body: AppointmentCreate) =>
    request<VisitorAppointment>("/appointments", { method: "POST", body: JSON.stringify(body) }, token),
  updateAppointment: (token: string, id: string, body: Partial<AppointmentCreate> & { status?: string }) =>
    request<VisitorAppointment>(`/appointments/${id}`, { method: "PATCH", body: JSON.stringify(body) }, token),
  deleteAppointment: (token: string, id: string): Promise<void> =>
    request(`/appointments/${id}`, { method: "DELETE" }, token),

  // Kiosk appointment lookup (device token auth)
  getKioskAppointment: (kioskToken: string, apptToken: string) =>
    request<KioskAppointmentResponse>(`/kiosk/appointment/${encodeURIComponent(apptToken)}`, { headers: { "X-Kiosk-Token": kioskToken } }),

  // Tenant user management (admin)
  listUsers: (token: string) =>
    request<UserListItem[]>("/users", {}, token),
  createUser: (token: string, data: { email: string; password: string; role: string }) =>
    request<UserListItem>("/users", { method: "POST", body: JSON.stringify(data) }, token),
  deleteUser: (token: string, userId: string) =>
    request(`/users/${userId}`, { method: "DELETE" }, token),
  updateUserRole: (token: string, userId: string, role: string) =>
    request<UserListItem>(`/users/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) }, token),
  changePassword: (token: string, currentPassword: string, newPassword: string): Promise<void> =>
    request(`/users/me/password`, { method: "PATCH", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }, token),
  resetUserPassword: (token: string, userId: string, newPassword: string): Promise<void> =>
    request(`/users/${userId}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: newPassword }) }, token),
  getMe: (token: string) =>
    request<MeProfile>("/users/me", {}, token),
  updateMe: (token: string, data: string | { email?: string; name?: string }) =>
    request<MeProfile>("/users/me", { method: "PATCH", body: JSON.stringify(typeof data === "string" ? { email: data } : data) }, token),
};

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface DailyStatItem {
  date: string;
  count: number;
}

export interface DailyStatsResponse {
  data: DailyStatItem[];
}

export interface ReceptionDailyStat {
  date: string;
  count: number;
}

export interface ReceptionDailyStats {
  days: ReceptionDailyStat[];
  today: number;
  yesterday: number;
  week_total: number;
}

export interface UserListItem {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

export interface MeProfile {
  id: string;
  email: string;
  name?: string | null;
  role: string;
  tenant_id: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  tenant_slug: string;
  role: string;
}

export interface OperatorStats {
  tenant_count: number;
  reseller_count: number;
  user_count: number;
  device_count: number;
  reception_count: number;
  online_device_count: number;
  suspended_tenant_count: number;
  reception_today: number;
  reception_this_week: number;
  active_tenant_count: number;
  reception_today_unread?: number;
}

export interface ResellerStats {
  customer_count: number;
  device_count: number;
  user_count: number;
  reception_count: number;
  online_device_count: number;
  suspended_customer_count: number;
  reception_today: number;
  reception_this_week: number;
}

export interface OperatorTenant {
  id: string;
  slug: string;
  name: string;
  reseller_id?: string | null;
  brand_color?: string;
  is_suspended: boolean;
  created_at: string | null;
  operator_notes: string | null;
  device_count?: number;
  reception_today?: number;
  customer_count?: number;
}

export interface OperatorUser {
  id: string;
  email: string;
  role: string;
  tenant_id: string | null;
  created_at: string | null;
}

export interface OperatorDevice {
  id: string;
  name: string;
  location: string | null;
  tenant_id: string;
  tenant_name?: string | null;
  reseller_name?: string | null;
  last_seen_at: string | null;
  is_online?: boolean;
  pin_code?: string | null;
}

export interface OperatorReceptionItem {
  id: string;
  tenant_id: string;
  tenant_name: string;
  visitor_name: string;
  company: string | null;
  staff: string | null;
  purpose: string | null;
  method: string | null;
  state: string | null;
  staff_notes: string | null;
  created_at: string;
}

export interface ResellerReceptionItem {
  id: string;
  tenant_id: string;
  tenant_name: string;
  visitor_name: string;
  company: string | null;
  staff: string | null;
  purpose: string | null;
  method: string | null;
  state: string | null;
  staff_notes: string | null;
  created_at: string;
}

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
  staff_notes: string | null;
  created_at: string;
}

export interface Locker {
  id: string;
  name: string;
  gpio_pin: number;
  state: string;
  tenant_id: string;
  // Legacy fields (kept for backward compatibility)
  door_number: number;
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
  location: string | null;
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

export interface TenantStats {
  device_count: number;
  online_device_count: number;
  devices_online: number;
  devices_offline: number;
  reception_count: number;
  reception_today: number;
  reception_this_week: number;
  unread_count: number;
  user_count: number;
  media_count: number;
  playlist_count: number;
}

export interface TenantSettings {
  tenant_name: string;
  tenant_slug: string;
  brand_color: string;
  logo_url: string | null;
  font: string;
  kiosk_welcome_message: string;
  kiosk_sub_message: string;
  kiosk_calling_message: string;
  kiosk_complete_message: string;
  kiosk_idle_timeout_sec: number;
  kiosk_complete_timeout_sec: number;
  logo_pos_x: number;
  logo_pos_y: number;
  logo_width_pct: number;
  kiosk_style: string;
  staff_list?: string | null;
  purpose_list?: string | null;
}

export interface PublicTenantSettings {
  brand_color: string;
  logo_url: string | null;
  font: string;
  kiosk_welcome_message: string;
  kiosk_sub_message: string;
  kiosk_calling_message: string;
  kiosk_complete_message: string;
  kiosk_idle_timeout_sec: number;
  kiosk_complete_timeout_sec: number;
  logo_pos_x: number;
  logo_pos_y: number;
  logo_width_pct: number;
  kiosk_style: string;
  is_suspended: boolean;
  staff_list?: string[];
  purpose_list?: string[];
}

export interface KioskScheduleResponse {
  playlist: {
    id: string;
    name: string;
    items: KioskPlaylistItem[];
  } | null;
  suspended?: boolean;
}

// ---- Local Device Agent --------------------------------------------------
// Set NEXT_PUBLIC_LOCAL_AGENT_URL=http://localhost:8080 in kiosk builds to
// route media through the on-device agent instead of the remote CDN.
const _LOCAL_AGENT = process.env.NEXT_PUBLIC_LOCAL_AGENT_URL ?? "";

export const localAgent = {
  isAvailable: () => Boolean(_LOCAL_AGENT),
  getMediaUrl: (mediaId: string) => `${_LOCAL_AGENT}/media/${mediaId}`,
  openLocker: (lockerId: string): Promise<{ locker_id: string; state: string }> =>
    fetch(`${_LOCAL_AGENT}/device/locker/${lockerId}/open`, { method: "POST" }).then(r => r.json()),
  getPirStatus: (): Promise<{ motion_detected: boolean }> =>
    fetch(`${_LOCAL_AGENT}/device/pir`).then(r => r.json()),
  getHealth: (): Promise<{ status: string; token_set: boolean; mock_gpio: boolean }> =>
    fetch(`${_LOCAL_AGENT}/health`).then(r => r.json()),
};

export interface VisitorAppointment {
  id: string;
  visitor_name: string;
  company: string | null;
  purpose: string | null;
  staff: string | null;
  scheduled_at: string;
  token: string;
  status: "pending" | "received" | "expired";
  notes: string | null;
  created_at: string;
}

export interface AppointmentCreate {
  visitor_name: string;
  company?: string;
  purpose?: string;
  staff?: string;
  scheduled_at: string;
  notes?: string;
}

export interface KioskAppointmentResponse {
  id: string;
  visitor_name: string;
  company: string | null;
  purpose: string | null;
  staff: string | null;
  scheduled_at: string;
  status: string;
}

const _SETTINGS_KEY = "mokuture_kiosk_settings";

export function getCachedKioskSettings(tenantSlug: string): PublicTenantSettings | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(`${_SETTINGS_KEY}_${tenantSlug}`);
    if (raw) return JSON.parse(raw) as PublicTenantSettings;
  } catch {}
  return null;
}

export function setCachedKioskSettings(tenantSlug: string, s: PublicTenantSettings): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(`${_SETTINGS_KEY}_${tenantSlug}`, JSON.stringify(s));
  } catch {}
}
