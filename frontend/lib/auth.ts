"use client";

export function saveTokens(access: string, refresh: string, role?: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem("mokuture_access", access);
  localStorage.setItem("mokuture_refresh", refresh);
  if (role) localStorage.setItem("mokuture_role", role);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("mokuture_access");
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("mokuture_refresh");
}

export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("mokuture_role");
}

export function clearTokens() {
  localStorage.removeItem("mokuture_access");
  localStorage.removeItem("mokuture_refresh");
  localStorage.removeItem("mokuture_role");
}

export function getLogoutUrl(): string {
  const role = getRole();
  if (role === "operator") return "/ops-console";
  if (role === "reseller") return "/partner-portal";
  return "/login";
}
