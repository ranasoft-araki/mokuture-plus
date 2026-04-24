"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ReceptionLog } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";

export default function ReceptionLogsPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [logs, setLogs] = useState<ReceptionLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    api.listReception(token)
      .then(setLogs)
      .catch(() => { clearTokens(); router.push("/login"); })
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <div className="min-h-screen bg-[#f5f2ed]">
      <div className="bg-white border-b border-[#e2ddd6] px-6 py-4 flex items-center gap-3">
        <button onClick={() => router.push(`/${params.tenant}/admin`)} className="text-[#8a8070] hover:text-[#1d1a15]">← ダッシュボード</button>
        <span className="text-[#c8c0b0]">/</span>
        <span className="text-[#5a5347] font-medium">受付ログ</span>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="bg-white rounded-xl border border-[#e2ddd6] overflow-hidden">
          <div className="px-6 py-4 border-b border-[#e2ddd6]">
            <h1 className="font-medium text-[#1d1a15]">受付記録 ({logs.length}件)</h1>
          </div>

          {loading ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">読み込み中…</div>
          ) : logs.length === 0 ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">受付記録がありません</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-[#f8f5f0]">
                <tr>
                  {["日時", "お名前", "会社", "用件", "担当者", "方法", "状態"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-[#5a5347] font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f0ece6]">
                {logs.map((r) => (
                  <tr key={r.id} className="hover:bg-[#faf8f4]">
                    <td className="px-4 py-3 text-[#8a8070] whitespace-nowrap">
                      {new Date(r.created_at).toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="px-4 py-3 font-medium text-[#1d1a15]">{r.visitor_name}</td>
                    <td className="px-4 py-3 text-[#5a5347]">{r.company || "—"}</td>
                    <td className="px-4 py-3 text-[#5a5347]">{r.purpose || "—"}</td>
                    <td className="px-4 py-3 text-[#5a5347]">{r.staff || "—"}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded bg-[#e8f0f5] text-[#2e6b8e] text-xs">{r.method}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${r.state === "received" ? "bg-[#e8f0e9] text-[#4a7c4e]" : "bg-[#f0ece6] text-[#8a8070]"}`}>
                        {r.state}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
