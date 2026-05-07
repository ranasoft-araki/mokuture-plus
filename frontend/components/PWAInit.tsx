"use client";

import { useEffect } from "react";

type NavWithBadge = Navigator & {
  clearAppBadge?: () => Promise<void>;
};

export function PWAInit() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch((err) => console.warn("SW registration failed:", err));

    const clearBadge = async () => {
      (navigator as NavWithBadge).clearAppBadge?.().catch(() => {});
      const reg = await navigator.serviceWorker.ready.catch(() => null);
      reg?.active?.postMessage({ type: "CLEAR_BADGE" });
    };

    const onVisibility = () => { if (!document.hidden) clearBadge(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  return null;
}
