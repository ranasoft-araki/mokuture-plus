"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type TenantStats, type PublicTenantSettings, type ReceptionDailyStats } from "@/lib/api";
import { getAccessToken, clearTokens, saveTokens } from "@/lib/auth";
import { AdminShell, MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

export default function DashboardPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [stats, setStats] = useState<TenantStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [publicSettings, setPublicSettings] = useState<PublicTenantSettings | null>(null);
  const [dailyStats, setDailyStats] = useState<ReceptionDailyStats | null>(null);

  const loadData = useCallback(async (token: string, showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const s = await api.getTenantStats(token);
      setStats(s);
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
      if (showSpinner) setRefreshing(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadPublicSettings = useCallback(async (slug: string) => {
    try {
      const s = await api.getPublicTenantSettings(slug);
      setPublicSettings(s);
    } catch {}
  }, []);

  useEffect(() => {
    const proxyAccess = localStorage.getItem("mk_proxy_access");
    const proxyRefresh = localStorage.getItem("mk_proxy_refresh");
    const proxyTenant = localStorage.getItem("mk_proxy_tenant");
    if (proxyAccess && proxyRefresh && proxyTenant === params.tenant) {
      saveTokens(proxyAccess, proxyRefresh, "admin");
      localStorage.removeItem("mk_proxy_access");
      localStorage.removeItem("mk_proxy_refresh");
      localStorage.removeItem("mk_proxy_tenant");
    }
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadData(token);
    void loadPublicSettings(params.tenant);
    api.getReceptionDailyStats(token)
      .then(r => setDailyStats(r))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <AdminShell active="dashboard" title="ダッシュボード" breadcrumb="ホーム">
        <div style={{ color: "#a8a198" }}>読み込み中…</div>
      </AdminShell>
    );
  }

  const today = new Date().toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric", weekday: "short" });

  return (
    <AdminShell
      active="dashboard"
      title="ダッシュボード"
      breadcrumb="ホーム"
      subtitle={`${today} · 稼働状況サマリー`}
      receptionUnread={stats?.unread_count ?? 0}
      actions={
        <MkBtn variant="ghost" size="sm" onClick={() => { const t = getAccessToken(); if (t) void loadData(t, true); }} disabled={refreshing}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
          {refreshing ? "更新中..." : "更新"}
        </MkBtn>
      }
    >
      {publicSettings?.is_suspended && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "12px 16px", marginBottom: 16, color: "#dc2626", fontSize: 14 }}>
          このテナントは現在停止中です。サービスは利用できません。
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        <KpiCard
          label="デバイス"
          value={stats?.device_count ?? 0}
          unit="台"
          sub={`オンライン ${stats?.online_device_count ?? 0} 台`}
          accent="#2d6a4f"
          devicesOnline={stats?.devices_online ?? 0}
          devicesOffline={stats?.devices_offline ?? 0}
        />
        <KpiCard
          label="受付"
          value={stats?.reception_today ?? 0}
          unit="件"
          sub={`今週 ${stats?.reception_this_week ?? 0} 件`}
        />
        <KpiCard
          label="ユーザー数"
          value={stats?.user_count ?? 0}
          unit="名"
          sub={`メディア ${stats?.media_count ?? 0} 件`}
        />
        <KpiCard
          label="メディア"
          value={stats?.media_count ?? 0}
          unit="件"
          sub={`プレイリスト ${stats?.playlist_count ?? 0} 件`}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
        <MkCard style={{ textAlign: "center" as const, padding: "32px 24px" }}>
          <MkSectionTitle title="本日の受付" subtitle="今日 00:00 以降" style={{ marginBottom: 16 }} />
          <div style={{ fontSize: 72, fontWeight: 700, color: "#2d6a4f", lineHeight: 1, letterSpacing: "-2px" }}>
            {stats?.reception_today ?? 0}
          </div>
          <div style={{ fontSize: 16, color: "#a8a198", marginTop: 8 }}>件</div>
        </MkCard>
        <MkCard style={{ textAlign: "center" as const, padding: "32px 24px" }}>
          <MkSectionTitle title="今週の受付" subtitle="月曜日以降" style={{ marginBottom: 16 }} />
          <div style={{ fontSize: 72, fontWeight: 700, color: "#1d1a15", lineHeight: 1, letterSpacing: "-2px" }}>
            {stats?.reception_this_week ?? 0}
          </div>
          <div style={{ fontSize: 16, color: "#a8a198", marginTop: 8 }}>件</div>
        </MkCard>
      </div>

      {dailyStats && (
        <MkCard style={{ marginBottom: 24, padding: "20px 24px" }}>
          <MkSectionTitle title="受付統計（過去14日）" subtitle="直近14日間の受付件数" style={{ marginBottom: 16 }} />
          <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
            <div style={{ fontSize: 13, color: "#1d1a15" }}>
              今日 <strong style={{ fontSize: 18, color: "#2d6a4f" }}>{dailyStats.today}</strong>件
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
              const todayStr = new Date().toISOString().slice(0, 10);
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
                        background: isToday ? "#2d6a4f" : "#4a7c4e",
                        borderRadius: "3px 3px 0 0",
                        minHeight: 4,
                      }}
                      title={`${d.date}: ${d.count}件`}
                    />
                    <div style={{ fontSize: 10, color: "#a8a198", textAlign: "center" }}>{dayNum}</div>
                  </div>
                );
              });
            })()}
          </div>
        </MkCard>
      )}

      <MkCard>
        <MkSectionTitle title="クイックアクセス" subtitle="よく使う管理ページ" style={{ marginBottom: 16 }} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          <QuickLink
            icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>}
            label="メディア管理"
            onClick={() => router.push(`/${params.tenant}/admin/media`)}
          />
          <QuickLink
            icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>}
            label="キオスク端末"
            onClick={() => router.push(`/${params.tenant}/admin/kiosk`)}
          />
          <QuickLink
            icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>}
            label="受付設定"
            onClick={() => router.push(`/${params.tenant}/admin/kiosk-settings`)}
          />
          <QuickLink
            icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>}
            label="ユーザー管理"
            onClick={() => router.push(`/${params.tenant}/admin/users`)}
          />
        </div>
      </MkCard>
    </AdminShell>
  );
}

function KpiCard({ label, value, unit, sub, accent, devicesOnline, devicesOffline }: { label: string; value: number; unit: string; sub?: string; accent?: string; devicesOnline?: number; devicesOffline?: number }) {
  return (
    <MkCard padding="20px">
      <div style={{ fontSize: 11.5, color: "#a8a198", letterSpacing: "0.2px", marginBottom: 10 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <div style={{ fontSize: 32, fontWeight: 700, color: accent ?? "#1d1a15", letterSpacing: "-1px", lineHeight: 1 }}>
          {value}
        </div>
        <div style={{ fontSize: 13, color: "#a8a198" }}>{unit}</div>
      </div>
      {sub && <div style={{ fontSize: 11, color: "#6b6559", marginTop: 8 }}>{sub}</div>}
      {devicesOnline !== undefined && devicesOffline !== undefined && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontSize: 11 }}>
          <span style={{ color: "#16a34a" }}>● {devicesOnline} オンライン</span>
          <span style={{ color: "#a8a198" }}>○ {devicesOffline} オフライン</span>
        </div>
      )}
    </MkCard>
  );
}

function QuickLink({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
        padding: "20px 12px",
        background: "#fffefb",
        border: "1px solid #efece5",
        borderRadius: 10,
        cursor: "pointer",
        color: "#2d2a24",
        fontSize: 12.5,
        fontWeight: 500,
        transition: "background 0.15s",
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#f4f1ea"; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#fffefb"; }}
    >
      <div style={{ color: "#2d6a4f" }}>{icon}</div>
      {label}
    </button>
  );
}
