"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, OperatorStats, DailyStatItem } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle } from "@/components/AdminShell";
import BarChart from "@/components/BarChart";

export default function OperatorDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<OperatorStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [dailyStats, setDailyStats] = useState<DailyStatItem[]>([]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getOperatorStats(token)
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false));
    api.getOperatorReceptionDailyStats(token)
      .then(r => setDailyStats(r.data))
      .catch(() => {});
  }, []);

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="システム概要" subtitle="全テナント・全デバイスのリアルタイム状況" style={{ marginBottom: 24 }} />

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : stats ? (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            <MkCard style={{ position: "relative" as const }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.tenant_count}</div>
              <div style={{ fontSize: 12, color: "#a8a198", marginBottom: 2 }}>テナント数</div>
              <div style={{ fontSize: 11, color: "#a8a198" }}>{stats.active_tenant_count} / {stats.tenant_count} アクティブ</div>
            </MkCard>

            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6b4a9e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.device_count}</div>
              <div style={{ fontSize: 12, color: "#a8a198", marginBottom: 2 }}>デバイス数</div>
              <div style={{ fontSize: 11, color: "#a8a198" }}>{stats.online_device_count} オンライン</div>
            </MkCard>

            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#b8763a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.reseller_count}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>代理店数</div>
            </MkCard>

            <MkCard style={stats.suspended_tenant_count > 0 ? { background: "#2a1010", border: "1px solid #7a2020" } : {}}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={stats.suspended_tenant_count > 0 ? "#e05555" : "#a8a198"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: stats.suspended_tenant_count > 0 ? "#e05555" : "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.suspended_tenant_count}</div>
              <div style={{ fontSize: 12, color: stats.suspended_tenant_count > 0 ? "#e05555" : "#a8a198", fontWeight: stats.suspended_tenant_count > 0 ? 600 : 400 }}>停止中テナント</div>
              {stats.suspended_tenant_count > 0 && (
                <div style={{ fontSize: 10, color: "#e05555", marginTop: 2 }}>要確認</div>
              )}
            </MkCard>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2e6b8e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.reception_today}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>本日の受付</div>
            </MkCard>

            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2e6b8e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.reception_this_week}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>今週の受付</div>
            </MkCard>

            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a84238" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.reception_count}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>総受付数</div>
            </MkCard>

            <MkCard>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f4f0e8", letterSpacing: "-1px", marginBottom: 4 }}>{stats.user_count}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>ユーザー数</div>
            </MkCard>
          </div>

          {dailyStats.length > 0 && (
            <MkCard style={{ marginBottom: 24, padding: "16px 20px" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#6b6559", marginBottom: 4 }}>受付ボリューム（過去14日）</div>
              <BarChart data={dailyStats} barColor="#c8a96e" />
            </MkCard>
          )}
        </>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <MkCard>
          <MkSectionTitle title="クイックアクション" />
          <div style={{ display: "flex", flexDirection: "column" as const, gap: 8 }}>
            {[
              { label: "テナントを追加", path: "/operator/tenants", desc: "全テナントの一覧・作成・削除" },
              { label: "代理店管理", path: "/operator/resellers", desc: "代理店の一覧・作成・削除" },
              { label: "緊急配信", path: "/operator/broadcast", desc: "全テナントへの緊急メッセージ配信" },
              { label: "受付ログ", path: "/operator/reception", desc: "クロステナント受付ログ一覧" },
              { label: "デバイス管理", path: "/operator/devices", desc: "全RasPiデバイスの確認" },
            ].map((item) => (
              <button
                key={item.path}
                onClick={() => router.push(item.path)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", background: "#faf8f4", border: "1px solid #efece5", borderRadius: 8, cursor: "pointer", textAlign: "left" as const }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f0ede6"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#faf8f4"; }}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1d1a15" }}>{item.label}</div>
                  <div style={{ fontSize: 11.5, color: "#a8a198", marginTop: 2 }}>{item.desc}</div>
                </div>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
              </button>
            ))}
          </div>
        </MkCard>

        <MkCard>
          <MkSectionTitle title="注意事項" />
          <div style={{ display: "flex", flexDirection: "column" as const, gap: 10 }}>
            <div style={{ padding: "12px 14px", background: "#fff8f0", border: "1px solid #fde8c0", borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#b8763a", marginBottom: 4 }}>テナント削除について</div>
              <div style={{ fontSize: 12, color: "#6b6559", lineHeight: 1.6 }}>テナントを削除すると、関連するすべてのメディア・受付ログ・デバイス情報も完全に削除されます。</div>
            </div>
            <div style={{ padding: "12px 14px", background: "#fff0f0", border: "1px solid #ffc5c5", borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#a84238", marginBottom: 4 }}>緊急配信について</div>
              <div style={{ fontSize: 12, color: "#6b6559", lineHeight: 1.6 }}>緊急配信を実行すると、全テナントのキオスクデバイスに強制更新が送信されます。</div>
            </div>
          </div>
        </MkCard>
      </div>
    </div>
  );
}
