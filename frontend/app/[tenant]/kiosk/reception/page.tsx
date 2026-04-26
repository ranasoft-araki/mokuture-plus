"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ReceptionCreate } from "@/lib/api";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function ReceptionPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [form, setForm] = useState<ReceptionCreate>({
    visitor_name: "", company: "", purpose: "", staff: "", method: "form",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetIdle = () => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => router.push(`/${params.tenant}/kiosk`), IDLE_TIMEOUT_MS);
  };

  useEffect(() => {
    if (!localStorage.getItem(KIOSK_TOKEN_KEY)) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }
    resetIdle();
    return () => { if (idleRef.current) clearTimeout(idleRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleChange = (field: keyof ReceptionCreate, value: string) => {
    resetIdle();
    setForm((f) => ({ ...f, [field]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.visitor_name.trim()) { setError("お名前を入力してください"); return; }
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) { router.replace(`/${params.tenant}/kiosk/setup`); return; }
    setSubmitting(true);
    try {
      await api.createKioskReception(kioskToken, form);
      router.push(`/${params.tenant}/kiosk/complete?name=${encodeURIComponent(form.visitor_name)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付に失敗しました");
      setSubmitting(false);
    }
  };

  const fields: { key: keyof ReceptionCreate; label: string; placeholder: string; required?: boolean }[] = [
    { key: "visitor_name", label: "お名前",   placeholder: "山田 太郎",          required: true },
    { key: "company",      label: "会社名",   placeholder: "株式会社 〇〇" },
    { key: "purpose",      label: "用件",     placeholder: "打ち合わせ、納品など" },
    { key: "staff",        label: "担当者名", placeholder: "担当者のお名前" },
  ];

  return (
    <div
      className="w-screen h-screen flex flex-col select-none"
      style={{ background: "#faf8f4" }}
      onClick={resetIdle}
    >
      {/* Header */}
      <div style={{
        background: "#4a7c4e", padding: "0 28px",
        height: 88, display: "flex", alignItems: "center", gap: 16, flexShrink: 0,
      }}>
        <button
          type="button"
          onClick={() => router.push(`/${params.tenant}/kiosk/top`)}
          style={{
            width: 44, height: 44, borderRadius: 12,
            background: "rgba(255,255,255,0.15)", border: "none",
            display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 5l-7 7 7 7" />
          </svg>
        </button>
        <h1 style={{ color: "white", fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0 }}>
          受付
        </h1>
      </div>

      {/* Form — button lives inside the form so type="submit" works */}
      <form
        onSubmit={handleSubmit}
        style={{
          flex: 1, display: "flex", flexDirection: "column",
          padding: "32px 32px 48px",
        }}
      >
        <p style={{ color: "#6b6559", fontSize: 17, margin: "0 0 28px", lineHeight: 1.5 }}>
          お名前と用件をご入力ください。
        </p>

        {error && (
          <div style={{
            marginBottom: 20, background: "#f6e0dc",
            border: "1px solid #a84238", borderRadius: 12,
            padding: "12px 16px", color: "#a84238", fontSize: 15,
          }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 20, flex: 1 }}>
          {fields.map(({ key, label, placeholder, required }) => (
            <div key={key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <label style={{
                fontSize: 14, fontWeight: 600, color: "#1d1a15",
                display: "flex", alignItems: "center", gap: 8,
              }}>
                {label}
                {required && (
                  <span style={{
                    fontSize: 11, color: "white", background: "#a84238",
                    padding: "1px 8px", borderRadius: 999, fontWeight: 600,
                  }}>必須</span>
                )}
              </label>
              <input
                type="text"
                value={(form[key] as string) ?? ""}
                onChange={(e) => handleChange(key, e.target.value)}
                placeholder={placeholder}
                autoComplete="off"
                required={required}
                style={{
                  height: 64, background: "white",
                  border: `2px solid ${(form[key] as string) ? "#4a7c4e" : "#d8d3c7"}`,
                  borderRadius: 12, padding: "0 20px",
                  fontSize: 20, color: "#1d1a15", outline: "none",
                  boxShadow: (form[key] as string) ? "0 0 0 3px #eaf0e8" : "none",
                  transition: "border-color 0.15s, box-shadow 0.15s",
                }}
              />
            </div>
          ))}
        </div>

        {/* Submit — inside the form, so type="submit" works correctly */}
        <button
          type="submit"
          disabled={submitting}
          style={{
            marginTop: 28, width: "100%", height: 68,
            background: submitting ? "#7a9e7d" : "#4a7c4e",
            color: "white", border: "none", borderRadius: 16,
            fontSize: 20, fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer",
            letterSpacing: "0.02em",
            boxShadow: "0 4px 16px rgba(74,124,78,0.35)",
            transition: "background 0.15s",
            flexShrink: 0,
          }}
        >
          {submitting ? "送信中…" : "受付する"}
        </button>
      </form>
    </div>
  );
}
