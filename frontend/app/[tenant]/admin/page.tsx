"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ReceptionLog } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";

export default function DashboardPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [todayCount, setTodayCount] = useState<number | null>(null);
  const [recent, setRecent] = useState<ReceptionLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    (async () => {
      try {
        const [stats, logs] = await Promise.all([
          api.todayStats(token),
          api.listReception(token),
        ]);
        setTodayCount(stats.count);
        setRecent(logs.slice(0, 5));
      } catch {
        clearTokens();
        router.push("/login");
      } finally {
        setLoading(false);
      }
    })();
  }, [router]);

  if (loading) return <Shell tenant={params.tenant} title="ダッシュボード"><div className="text-[#8a8070]">読み込み中…</div></Shell>;

  return (
    <Shell tenant={params.tenant} title="ダッシュボード">
      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="本日の受付" value={todayCount ?? 0} unit="件" color="#4a7c4e" />
        <StatCard label="稼働キオスク" value={1} unit="台" color="#2e6b8e" />
        <StatCard label="ロッカー開錠" value={0} unit="回" color="#b8763a" />
        <StatCard label="通知配信" value={todayCount ?? 0} unit="件" color="#8a8070" />
      </div>

      {/* Recent receptions */}
      <div className="bg-white rounded-xl border border-[#e2ddd6]">
        <div className="px-6 py-4 border-b border-[#e2ddd6] flex items-center justify-between">
          <h2 className="font-medium text-[#1d1a15]">直近の受付</h2>
          <button onClick={() => router.push(`/${params.tenant}/admin/reception`)} className="text-[#4a7c4e] text-sm">すべて見る →</button>
        </div>
        {recent.length === 0 ? (
          <div className="px-6 py-8 text-center text-[#8a8070]">受付記録がありません</div>
        ) : (
          <div className="divide-y divide-[#f0ece6]">
            {recent.map((r) => (
              <div key={r.id} className="px-6 py-4 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-[#1d1a15] truncate">{r.visitor_name}</p>
                  <p className="text-sm text-[#8a8070] truncate">{r.company} {r.purpose ? `· ${r.purpose}` : ""}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-sm text-[#5a5347]">{r.staff || "—"}</p>
                  <p className="text-xs text-[#a09880]">{new Date(r.created_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}</p>
                </div>
                <span className={`shrink-0 px-2 py-1 rounded-full text-xs font-medium ${r.state === "received" ? "bg-[#e8f0e9] text-[#4a7c4e]" : "bg-[#f5e8e8] text-[#a84238]"}`}>
                  {r.state === "received" ? "受付済" : r.state}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick nav */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-6">
        {[
          { label: "メディア管理", href: `/${params.tenant}/admin/media`, desc: "動画・画像のアップロード" },
          { label: "受付ログ", href: `/${params.tenant}/admin/reception`, desc: "来訪者の記録一覧" },
          { label: "キオスク管理", href: `/${params.tenant}/admin/kiosk`, desc: "端末トークンの発行・管理" },
          { label: "キオスク表示", href: `/${params.tenant}/kiosk`, desc: "キオスク画面を開く", external: true },
        ].map((item) => (
          <button
            key={item.href}
            onClick={() => item.external ? window.open(item.href, "_blank") : router.push(item.href)}
            className="text-left bg-white rounded-xl border border-[#e2ddd6] px-5 py-4 hover:border-[#4a7c4e] transition-colors"
          >
            <p className="font-medium text-[#1d1a15]">{item.label}</p>
            <p className="text-sm text-[#8a8070] mt-1">{item.desc}</p>
          </button>
        ))}
      </div>
    </Shell>
  );
}

function StatCard({ label, value, unit, color }: { label: string; value: number; unit: string; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-[#e2ddd6] px-5 py-4">
      <p className="text-sm text-[#8a8070]">{label}</p>
      <p className="text-3xl font-semibold mt-1" style={{ color }}>{value}<span className="text-base font-normal text-[#8a8070] ml-1">{unit}</span></p>
    </div>
  );
}

function Shell({ tenant, title, children }: { tenant: string; title: string; children: React.ReactNode }) {
  const router = useRouter();
  const logout = () => { clearTokens(); router.push("/login"); };
  return (
    <div className="min-h-screen bg-[#f5f2ed]">
      <div className="bg-white border-b border-[#e2ddd6] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[#4a7c4e] font-semibold">mokuture+</span>
          <span className="text-[#c8c0b0]">/</span>
          <span className="text-[#5a5347]">{title}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[#8a8070] bg-[#f0ece6] px-2 py-1 rounded">{tenant}</span>
          <button onClick={logout} className="text-sm text-[#8a8070] hover:text-[#1d1a15]">ログアウト</button>
        </div>
      </div>
      <div className="max-w-5xl mx-auto px-6 py-8">{children}</div>
    </div>
  );
}
