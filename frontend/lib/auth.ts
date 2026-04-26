"use client";

export function saveTokens(access: string, refresh: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem("mokuture_access", access);
  localStorage.setItem("mokuture_refresh", refresh);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("mokuture_access");
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("mokuture_refresh");
}

export function clearTokens() {
  localStorage.removeItem("mokuture_access");
  localStorage.removeItem("mokuture_refresh");
}
