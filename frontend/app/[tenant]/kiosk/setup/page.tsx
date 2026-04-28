"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";
const KIOSK_NAME_KEY = "mokuture_kiosk_name";

const PAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "←", "0", "→"] as const;

function KioskSetup() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [pin, setPin] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");

  // Auto-submit when PIN is in URL query param (SSH provisioning flow)
  const urlPin = searchParams.get("pin");
  useEffect(() => {
    if (urlPin && urlPin.length === 6) {
      verifyPin(urlPin);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function verifyPin(code: string) {
    setVerifying(true);
    setError("");
    try {
      const { device_token, device_name } = await api.verifyKioskPin(code);
      localStorage.setItem(KIOSK_TOKEN_KEY, device_token);
      localStorage.setItem(KIOSK_NAME_KEY, device_name);
      router.replace(`/${params.tenant}/kiosk`);
    } catch {
      setError("PINが無効です。管理画面で新しいPINを発行してください。");
      setVerifying(false);
    }
  }

  function handleKey(key: string) {
    if (verifying) return;
    if (key === "←") {
      setPin((p) => p.slice(0, -1));
      setError("");
    } else if (key === "→") {
      if (pin.length === 6) verifyPin(pin);
    } else if (pin.length < 6) {
      const next = pin + key;
      setPin(next);
      setError("");
      if (next.length === 6) verifyPin(next);
    }
  }

  const dots = Array.from({ length: 6 }, (_, i) => pin[i] ?? null);

  return (
    <div className="w-screen h-screen bg-[#1d1a15] flex items-center justify-center">
      <div className="flex flex-col items-center gap-8 w-full max-w-xs px-6">
        {/* Header */}
        <div className="text-center space-y-1">
          <p className="text-[#faf8f4] text-2xl font-light tracking-widest">mokuture+</p>
          <p className="text-[#8a8070] text-sm">キオスク端末セットアップ</p>
        </div>

        {/* PIN dots */}
        <div className="flex gap-3">
          {dots.map((digit, i) => (
            <div
              key={i}
              className="w-11 h-11 rounded-xl flex items-center justify-center text-xl font-bold border"
              style={{
                background: digit !== null ? "#4a7c4e" : "#2a2720",
                borderColor: digit !== null ? "#4a7c4e" : "#3a3530",
                color: "#faf8f4",
              }}
            >
              {digit !== null ? "●" : ""}
            </div>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="w-full rounded-lg bg-red-900/30 border border-red-700/50 px-4 py-3 text-sm text-red-300 text-center">
            {error}
          </div>
        )}

        {/* Verifying overlay */}
        {verifying && (
          <p className="text-[#8a8070] text-sm animate-pulse">確認中…</p>
        )}

        {/* Numpad */}
        <div className="grid grid-cols-3 gap-3 w-full">
          {PAD_KEYS.map((key) => {
            const isAction = key === "←" || key === "→";
            const isConfirm = key === "→";
            const isDisabled = verifying || (isConfirm && pin.length < 6);
            return (
              <button
                key={key}
                onClick={() => handleKey(key)}
                disabled={isDisabled}
                className="h-16 rounded-2xl text-xl font-semibold select-none transition-opacity active:scale-95"
                style={{
                  background: isConfirm ? "#4a7c4e" : isAction ? "#2a2720" : "#2a2720",
                  color: isConfirm ? "#faf8f4" : isAction ? "#c8c0b0" : "#faf8f4",
                  border: `1px solid ${isConfirm ? "#4a7c4e" : "#3a3530"}`,
                  opacity: isDisabled ? 0.35 : 1,
                  fontSize: isAction ? "1rem" : "1.25rem",
                }}
              >
                {key === "←" ? "⌫" : key === "→" ? "決定" : key}
              </button>
            );
          })}
        </div>

        <p className="text-center text-xs text-[#5a5347]">
          管理画面「キオスク端末」→「端末を追加」でPINを発行
        </p>
      </div>
    </div>
  );
}

export default function KioskSetupPage() {
  return (
    <Suspense>
      <KioskSetup />
    </Suspense>
  );
}
