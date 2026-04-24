"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ReceptionCreate } from "@/lib/api";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function ReceptionPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [form, setForm] = useState<ReceptionCreate>({ visitor_name: "", company: "", purpose: "", staff: "", method: "form" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset idle timer on any interaction
  const resetIdle = () => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => router.push(`/${params.tenant}/kiosk`), IDLE_TIMEOUT_MS);
  };

  useEffect(() => {
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
    setSubmitting(true);
    try {
      const token = localStorage.getItem(KIOSK_TOKEN_KEY) ?? "";
      await api.createReception(token, form);
      router.push(`/${params.tenant}/kiosk/complete?name=${encodeURIComponent(form.visitor_name)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付に失敗しました");
      setSubmitting(false);
    }
  };

  return (
    <div className="w-screen h-screen bg-[#faf8f4] flex flex-col" onClick={resetIdle}>
      {/* Header */}
      <div className="bg-[#4a7c4e] px-8 py-6 flex items-center gap-4">
        <button
          onClick={() => router.push(`/${params.tenant}/kiosk`)}
          className="text-white opacity-80 text-2xl min-w-[44px] min-h-[44px] flex items-center"
        >
          ←
        </button>
        <h1 className="text-white text-2xl font-medium">受付</h1>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="flex-1 flex flex-col gap-6 px-10 py-10 max-w-lg mx-auto w-full">
        <p className="text-[#5a5347] text-lg">お名前と用件をご入力ください。</p>

        {error && <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700">{error}</div>}

        <Field label="お名前 *">
          <input
            type="text"
            value={form.visitor_name}
            onChange={(e) => handleChange("visitor_name", e.target.value)}
            className="kiosk-input"
            placeholder="山田 太郎"
            autoComplete="off"
            required
          />
        </Field>

        <Field label="会社名">
          <input
            type="text"
            value={form.company ?? ""}
            onChange={(e) => handleChange("company", e.target.value)}
            className="kiosk-input"
            placeholder="株式会社 〇〇"
            autoComplete="off"
          />
        </Field>

        <Field label="用件">
          <input
            type="text"
            value={form.purpose ?? ""}
            onChange={(e) => handleChange("purpose", e.target.value)}
            className="kiosk-input"
            placeholder="打ち合わせ、納品など"
            autoComplete="off"
          />
        </Field>

        <Field label="担当者名">
          <input
            type="text"
            value={form.staff ?? ""}
            onChange={(e) => handleChange("staff", e.target.value)}
            className="kiosk-input"
            placeholder="担当者のお名前"
            autoComplete="off"
          />
        </Field>

        <button
          type="submit"
          disabled={submitting}
          className="mt-4 bg-[#4a7c4e] text-white text-xl py-5 rounded-xl font-medium disabled:opacity-50 min-h-[64px]"
        >
          {submitting ? "送信中…" : "受付する"}
        </button>
      </form>

      <style jsx global>{`
        .kiosk-input {
          width: 100%;
          padding: 16px 20px;
          font-size: 20px;
          border: 2px solid #e2ddd6;
          border-radius: 12px;
          background: white;
          outline: none;
          min-height: 64px;
        }
        .kiosk-input:focus {
          border-color: #4a7c4e;
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-[#1d1a15] text-base font-medium">{label}</label>
      {children}
    </div>
  );
}
