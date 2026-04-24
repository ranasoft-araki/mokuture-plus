"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";

const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

export default function KioskSetupPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [token, setToken] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) return;
    setVerifying(true);
    setError("");
    try {
      // Verify the token works by calling the schedule endpoint
      await api.getKioskSchedule(trimmed);
      localStorage.setItem(KIOSK_TOKEN_KEY, trimmed);
      router.replace(`/${params.tenant}/kiosk`);
    } catch {
      setError("トークンが無効です。管理画面で発行されたトークンを確認してください。");
      setVerifying(false);
    }
  }

  return (
    <div className="w-screen h-screen bg-[#1d1a15] flex items-center justify-center px-6">
      <div className="w-full max-w-md bg-[#2a2720] rounded-2xl p-8 space-y-6">
        <div className="text-center space-y-2">
          <p className="text-[#faf8f4] text-2xl font-light tracking-widest">mokuture+</p>
          <p className="text-[#8a8070] text-sm">キオスク端末セットアップ</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm text-[#c8c0b0]">デバイストークン</label>
            <textarea
              value={token}
              onChange={(e) => { setToken(e.target.value); setError(""); }}
              placeholder="管理画面で発行したトークンを貼り付けてください"
              rows={3}
              className="w-full bg-[#1d1a15] text-[#faf8f4] text-sm font-mono rounded-lg px-4 py-3 border border-[#3a3530] focus:outline-none focus:border-[#4a7c4e] resize-none"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-900/30 border border-red-700/50 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={verifying || !token.trim()}
            className="w-full bg-[#4a7c4e] text-white py-3 rounded-lg font-medium disabled:opacity-50"
          >
            {verifying ? "確認中…" : "設定を保存してキオスクを起動"}
          </button>
        </form>

        <p className="text-center text-xs text-[#5a5347]">
          トークンは管理画面の「キオスク管理」から発行できます
        </p>
      </div>
    </div>
  );
}
