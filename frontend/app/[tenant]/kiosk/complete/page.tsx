"use client";

import { useEffect, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";

const AUTO_RETURN_MS = 10_000;

export default function CompletePage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const name = searchParams.get("name") ?? "お客様";
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      router.push(`/${params.tenant}/kiosk`);
    }, AUTO_RETURN_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [params.tenant, router]);

  return (
    <div
      className="w-screen h-screen bg-[#4a7c4e] flex flex-col items-center justify-center gap-10 cursor-pointer"
      onClick={() => router.push(`/${params.tenant}/kiosk`)}
    >
      {/* Checkmark */}
      <div className="w-28 h-28 rounded-full bg-white/20 flex items-center justify-center">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </div>

      <div className="text-center space-y-4">
        <p className="text-white text-4xl font-medium">{name}様</p>
        <p className="text-white/90 text-2xl">ようこそいらっしゃいました</p>
        <p className="text-white/70 text-lg mt-2">担当者にご連絡しました。</p>
        <p className="text-white/50 text-base">少々お待ちください。</p>
      </div>

      <p className="text-white/40 text-sm mt-8">{AUTO_RETURN_MS / 1000}秒後に自動で戻ります</p>
    </div>
  );
}
