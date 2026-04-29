"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

// KioskFlow manages all screen states: idle → top → reception/qr → calling → complete
// This page is the mount point for kiosk devices accessing the cloud frontend.
// Raspberry Pi devices use kiosk_agent/static/kiosk.html instead.
export default function KioskPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("mokuture_kiosk_token");
    if (!stored) {
      router.replace(`/${params.tenant}/kiosk/setup`);
    } else {
      setToken(stored);
    }
  }, [params.tenant, router]);

  if (!token) return null;

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "rgba(255,255,255,0.4)", fontFamily: "Inter, system-ui, sans-serif", fontSize: 16 }}>
        読み込み中…
      </div>
    </div>
  );
}
