"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ResellerStats, type ReceptionDailyStats } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { ResellerShell } from "@/components/ResellerShell";

function KpiCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div style={{
      background: "#fffefb",
      border: "1px solid #efece5",
      borderRadius: 12,
      padding: "20px 22px",
      display: "flex",
      flexDirection: "column" as const,
      gap: 4,
    }}>
      <div style={{ fontSize: 11, color: "#a8a198", letterSpacing: "0.2px", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 36, fontWeight: 700, color: "#1d1a15", letterSpacing: "-1px", lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "#c8a96e", fontWeight: 500, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function ResellerDashboard() {
  const router = useRouter();
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";
  const [stats, setStats] = useState<ResellerStats | null>(null);
  const [dailyStats, setDailyStats] = useState<ReceptionDailyStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAccessToken() ?? "";
    if (!token) { router.push("/partner-portal"); return; }
    Promise.all([
      api.getResellerStats(token).then(setStats).catch(() => {}),
      api.getResellerDailyStats(token).then(setDailyStats).catch(() => {}),
    ]).finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const todayStr = new Date().toISOString().slice(0, 10);

  return (
    <ResellerShell>
      <div style={{ padding: "28px 32px" }}>
        {loading ? (
          <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
        ) : (
          <>
            {/* KPI Cards */}
            <div style={{ fontSize: 11, fontWeight: 600, color: "#c8a96e", letterSpacing: "0.08em", textTransform: "uppercase" as const, marginBottom: 10 }}>
              概要
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 28 }}>
              <KpiCard label="顧客テナント数" value={stats?.customer_count ?? 0} sub="管理中テナント" />
              <KpiCard label="管理デバイス数" value={stats?.device_count ?? 0} sub="全顧客テナント" />
              <KpiCard label="本日の受付" value={stats?.reception_today ?? 0} sub="今日 00:00 以降" />
              <KpiCard label="今週の受付" value={stats?.reception_this_week ?? 0} sub="月曜日以降" />
            </div>

            {/* Reception Stats Chart */}
            <div style={{ fontSize: 11, fontWeight: 600, color: "#c8a96e", letterSpacing: "0.08em", textTransform: "uppercase" as const, marginBottom: 10 }}>
              受付統計
            </div>
            <div style={{ background: "#fffefb", border: "1px solid #efece5", borderRadius: 12, padding: "20px 22px", marginBottom: 28 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15", marginBottom: 12 }}>受付統計チャート（過去14日）</div>
              {dailyStats && (
                <>
                  <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
                    <div style={{ fontSize: 13, color: "#1d1a15" }}>
                      今日 <strong style={{ fontSize: 18, color: "#b8924a" }}>{dailyStats.today}</strong>件
                    </div>
                    <div style={{ fontSize: 13, color: "#1d1a15" }}>
                      昨日 <strong style={{ fontSize: 18, color: "#1d1a15" }}>{dailyStats.yesterday}</strong>件
                    </div>
                    <div style={{ fontSize: 13, color: "#1d1a15" }}>
                      今週合計 <strong style={{ fontSize: 18, color: "#1d1a15" }}>{dailyStats.week_total}</strong>件
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 80 }}>
                    {(() => {
                      const maxCount = Math.max(...dailyStats.days.map(d => d.count), 1);
                      return dailyStats.days.map((d, i) => {
                        const barH = Math.max((d.count / maxCount) * 80, 4);
                        const isToday = d.date === todayStr;
                        const dayNum = new Date(d.date).getDate();
                        return (
                          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
                            <div
                              style={{
                                width: "100%",
                                height: barH,
                                background: isToday ? "#b8924a" : "#c8a96e",
                                borderRadius: "3px 3px 0 0",
                                minHeight: 4,
                              }}
                              title={`${d.date}: ${d.count}件`}
                            />
                            <div style={{ fontSize: 10, color: "#a8a198", textAlign: "center" as const }}>{dayNum}</div>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </>
              )}
            </div>

            {/* Quick Actions */}
            <div style={{ fontSize: 11, fontWeight: 600, color: "#c8a96e", letterSpacing: "0.08em", textTransform: "uppercase" as const, marginBottom: 10 }}>
              クイックアクション
            </div>
            <div style={{ background: "#fffefb", border: "1px solid #efece5", borderRadius: 12, padding: "20px 22px" }}>
              <div style={{ display: "flex", flexDirection: "column" as const, gap: 8 }}>
                {[
                  { label: "顧客を追加", path: `/${tenant}/reseller/customers`, desc: "顧客テナントの一覧・作成・削除" },
                  { label: "受付ログを見る", path: `/${tenant}/reseller/reception`, desc: "全顧客テナントの受付履歴" },
                  { label: "デバイス管理", path: `/${tenant}/reseller/devices`, desc: "顧客テナントのデバイス確認" },
                  { label: "ユーザー管理", path: `/${tenant}/reseller/users`, desc: "顧客テナントのユーザー確認" },
                ].map((item) => (
                  <button
                    key={item.path}
                    onClick={() => router.push(item.path)}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "12px 14px", background: "#faf8f4", border: "1px solid #efece5",
                      borderRadius: 8, cursor: "pointer", textAlign: "left" as const,
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f0ede6"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#faf8f4"; }}
                  >
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15" }}>{item.label}</div>
                      <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>{item.desc}</div>
                    </div>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#c8a96e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </ResellerShell>
  );
}
