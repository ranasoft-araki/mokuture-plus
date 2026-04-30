"use client";

export function saveTokens(access: string, refresh: string, role: string | undefined, remember: boolean) {
  if (typeof window === "undefined") return;
  const store = remember ? localStorage : sessionStorage;
  store.setItem("mokuture_access", access);
  store.setItem("mokuture_refresh", refresh);
  if (role) store.setItem("mokuture_role", role);
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

export function clearTokens() {
  ["mokuture_access", "mokuture_refresh", "mokuture_role"].forEach((k) => {
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
