"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function KioskSetupPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (pin.length < 4) return;
    setLoading(true);
    setError(null);
    try {
      const { device_token } = await api.verifyKioskPin(pin);
      localStorage.setItem("mokuture_kiosk_token", device_token);
      router.replace(`/${params.tenant}/kiosk`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "PIN が正しくありません");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Inter, 'Noto Sans JP', system-ui, sans-serif" }}>
      <div style={{ background: "#1d1a15", borderRadius: 16, padding: "40px 48px", width: 400 }}>
        <div style={{ fontSize: 13, letterSpacing: 3, color: "#a8a198", textTransform: "uppercase", marginBottom: 8 }}>DEVICE SETUP</div>
        <div style={{ fontSize: 24, fontWeight: 600, color: "#fffefb", marginBottom: 32 }}>PIN コードを入力</div>
        <input
          type="text"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 8))}
          placeholder="管理画面で発行した PIN"
          style={{ width: "100%", padding: "12px 16px", borderRadius: 8, border: "1px solid #3a3631", background: "#2d2a24", color: "#fffefb", fontSize: 18, fontFamily: "monospace", outline: "none", marginBottom: 8 }}
        />
        {error && <div style={{ fontSize: 12, color: "#f08080", marginBottom: 12 }}>{error}</div>}
        <button
          onClick={handleSubmit}
          disabled={loading || pin.length < 4}
          style={{ width: "100%", padding: "14px", borderRadius: 8, border: "none", background: "#4a7c4e", color: "#fffefb", fontSize: 16, fontWeight: 600, cursor: "pointer", opacity: (loading || pin.length < 4) ? 0.5 : 1, marginTop: 8 }}
        >
          {loading ? "確認中…" : "デバイスを登録"}
        </button>
      </div>
    </div>
  );
}
