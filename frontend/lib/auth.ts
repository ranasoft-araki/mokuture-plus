"use client";

export function saveTokens(access: string, refresh: string, role: string | undefined, remember: boolean, slug?: string) {
  if (typeof window === "undefined") return;
  const store = remember ? localStorage : sessionStorage;
  store.setItem("mokuture_access", access);
  store.setItem("mokuture_refresh", refresh);
  if (role) store.setItem("mokuture_role", role);
  if (slug) store.setItem("mokuture_slug", slug);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("mokuture_access") ?? localStorage.getItem("mokuture_access");
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("mokuture_refresh") ?? localStorage.getItem("mokuture_refresh");
}

export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("mokuture_role") ?? localStorage.getItem("mokuture_role");
}

export function getSlug(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("mokuture_slug") ?? localStorage.getItem("mokuture_slug");
}

export function clearTokens() {
  ["mokuture_access", "mokuture_refresh", "mokuture_role", "mokuture_slug"].forEach((k) => {
    localStorage.removeItem(k);
    sessionStorage.removeItem(k);
  });
}

export function refreshSaveTokens(access: string, refresh: string) {
  if (typeof window === "undefined") return;
  const store = sessionStorage.getItem("mokuture_access") ? sessionStorage : localStorage;
  store.setItem("mokuture_access", access);
  store.setItem("mokuture_refresh", refresh);
}

export function getLogoutUrl(): string {
  const role = getRole();
  if (role === "operator") return "/ops-console";
  if (role === "reseller") return "/partner-portal";
  return "/login";
}

// ログイン済みセッションがある場合に「開いたら中へ」自動遷移する先を返す。
// slug が無い（本機能導入前の旧セッション等）場合は null=遷移せずログイン画面を表示。
export function getHomeUrl(): string | null {
  if (typeof window === "undefined") return null;
  if (!getRefreshToken()) return null;
  const role = getRole();
  const slug = getSlug();
  if (role === "operator") return "/operator";
  if (role === "reseller") return slug ? `/${slug}/reseller` : null;
  return slug ? `/${slug}/admin` : null;
}

// ログインIDのみ端末に記憶する（パスワードは保存しない）。ログアウトでは消さない。
export function rememberLoginId(key: string, id: string) {
  if (typeof window === "undefined") return;
  if (id) localStorage.setItem(`mokuture_saved_id_${key}`, id);
}

export function getSavedLoginId(key: string): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(`mokuture_saved_id_${key}`) ?? "";
}
