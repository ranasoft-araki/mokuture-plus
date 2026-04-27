"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type ReceptionLog, type Device } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";
import { AdminShell, MkCard, MkBtn, MkPill, MkSectionTitle } from "@/components/AdminShell";

export default function DashboardPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [todayCount, setTodayCount] = useState<number | null>(null);
  const [logs, setLogs] = useState<ReceptionLog[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [notifySettings, setNotifySettings] = useState<Record<string, Record<string, string>>>({});

  const loadData = useCallback(async (token: string, showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const [stats, allLogs, devs, notify] = await Promise.all([
        api.todayStats(token),
        api.listReception(token),
        api.listDevices(token),
        api.getNotificationSettings(token).catch(() => ({})),
      ]);
      setTodayCount(stats.count);
      setLogs(allLogs);
      setDevices(devs);
      setNotifySettings(notify);
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
      if (showSpinner) setRefreshing(false);
    }
  }, [router]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadData(token);
  }, [loadData, router]);

  const hourlyData = useMemo(() => {
    const now = new Date();
    const today = now.toLocaleDateString("ja-JP");
    const buckets = Array(24).fill(0);
    logs.forEach((r) => {
      const d = new Date(r.created_at);
      if (d.toLocaleDateString("ja-JP") === today) {
        buckets[d.getHours()]++;
      }
    });
    return buckets;
  }, [logs]);

  const maxHour = Math.max(...hourlyData, 1);
  const recent = logs.slice(0, 5);

  const isOnline = (d: Device) => !!d.last_seen_at && (Date.now() - new Date(d.last_seen_at).getTime()) < 2 * 60 * 1000;
  const onlineCount = devices.filter(isOnline).length;

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
      subtitle={`${today} · 本日の稼働状況`}
      actions={
        <>
          <MkBtn variant="ghost" size="sm" onClick={() => { const t = getAccessToken(); if (t) void loadData(t, true); }} disabled={refreshing}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
            {refreshing ? "更新中..." : "更新"}
          </MkBtn>
          <MkBtn variant="primary" onClick={() => router.push(`/${params.tenant}/admin/media`)}>
            + 新規コンテンツ
          </MkBtn>
        </>
      }
    >
      {/* KPI row */}
      <div className="adm-kpi-row" style={{ gap: 14, marginBottom: 22 }}>
        <StatCard label="本日の受付件数" value={String(todayCount ?? 0)} unit="件" delta="前日比" />
        <StatCard label="稼働中キオスク" value={`${onlineCount}`} unit={`/ ${devices.length}`} accent="#3a6240" delta="すべて正常稼働" />
        <StatCard label="ロッカー開錠回数" value="0" unit="回" delta="—" />
        <StatCard label="通知配信数" value={String(todayCount ?? 0)} unit="件" delta="失敗 0件" />
      </div>

      <div className="adm-grid-main" style={{ gap: 20 }}>
        {/* LEFT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Hourly chart */}
          <MkCard>
            <MkSectionTitle
              title="時間帯別 受付件数"
              subtitle="00:00 – 23:59 / 本日"
              action={
                <div style={{ display: "flex", gap: 6 }}>
                  <MkBtn size="sm" variant="default">今日</MkBtn>
                  <MkBtn size="sm" variant="ghost">今週</MkBtn>
                  <MkBtn size="sm" variant="ghost">今月</MkBtn>
                </div>
              }
            />
            <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 80, padding: "0 0 4px" }}>
              {hourlyData.map((d, i) => (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    height: `${(d / maxHour) * 100 || 2}%`,
                    minHeight: 2,
                    background: d > 0 ? "#4a7c4e" : "#efece5",
                    borderRadius: "2px 2px 0 0",
                    opacity: d === 0 ? 0.6 : 1,
                  }}
                />
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#a8a198", marginTop: 6, fontFamily: "monospace" }}>
              <span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>
            </div>
          </MkCard>

          {/* Recent receptions */}
          <MkCard padding="0">
            <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid #efece5" }}>
              <MkSectionTitle
                title="直近の受付"
                subtitle="最新5件（カレンダー連動 / フォーム入力）"
                style={{ marginBottom: 0 }}
                action={
                  <MkBtn variant="ghost" size="sm" onClick={() => router.push(`/${params.tenant}/admin/reception`)}>
                    受付ログへ →
                  </MkBtn>
                }
              />
            </div>
            {recent.length === 0 ? (
              <div style={{ padding: "32px 20px", textAlign: "center", color: "#a8a198" }}>受付記録がありません</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ fontSize: 10.5, color: "#a8a198", textAlign: "left", background: "#f4f1ea", letterSpacing: "0.3px" }}>
                    {["時刻", "来訪者", "会社", "用件", "担当", "状態"].map((h) => (
                      <th key={h} style={{ padding: "9px 14px", fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody style={{ fontSize: 12.5 }}>
                  {recent.map((r, i) => (
                    <tr key={r.id} style={{ borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                      <td style={{ padding: "12px 14px", color: "#6b6559", fontFamily: "monospace", fontSize: 12 }}>
                        {new Date(r.created_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}
                      </td>
                      <td style={{ padding: "12px 14px", color: "#1d1a15", fontWeight: 500 }}>{r.visitor_name}</td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.company || "—"}</td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.purpose || "—"}</td>
                      <td style={{ padding: "12px 14px", color: "#6b6559" }}>{r.staff || "—"}</td>
                      <td style={{ padding: "12px 14px" }}>
                        <MkPill tone={r.state === "received" ? "live" : "neutral"}>
                          {r.state === "received" ? "確認済" : r.state}
                        </MkPill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </MkCard>
        </div>

        {/* RIGHT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Kiosk device status */}
          <MkCard>
            <MkSectionTitle
              title="キオスク端末"
              subtitle="リアルタイム稼働"
              action={<MkBtn size="sm" variant="ghost" onClick={() => router.push(`/${params.tenant}/admin/kiosk`)}>管理</MkBtn>}
            />
            {devices.length === 0 ? (
              <div style={{ fontSize: 12, color: "#a8a198" }}>端末が登録されていません</div>
            ) : (
              devices.slice(0, 3).map((d, i) => (
                <div key={d.id} style={{ padding: "12px 0", borderTop: i > 0 ? "1px solid #efece5" : "none", display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 6, background: "#1d1a15", display: "flex", alignItems: "center", justifyContent: "center", color: "#fffefb", flexShrink: 0 }}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>
                    </svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: "#2d2a24" }}>{d.name}</div>
                    <div style={{ fontSize: 10.5, color: "#a8a198", fontFamily: "monospace", marginTop: 2 }}>{d.id}</div>
                  </div>
                  <MkPill tone={isOnline(d) ? "live" : "off"}>{isOnline(d) ? "稼働中" : "オフライン"}</MkPill>
                </div>
              ))
            )}
          </MkCard>

          {/* Now playing */}
          <MkCard>
            <MkSectionTitle title="現在再生中" subtitle="スケジュール自動切替" />
            <div style={{
              aspectRatio: "16/9", borderRadius: 7, overflow: "hidden",
              background: "#1d1a15", position: "relative",
              backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 8px, transparent 8px 16px)",
            }}>
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, color: "#fffefb" }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="#fffefb" stroke="none"><polygon points="6 4 20 12 6 20 6 4"/></svg>
                <div style={{ fontSize: 11, fontFamily: "monospace", opacity: 0.7 }}>スケジュールを設定してください</div>
              </div>
              <div style={{ position: "absolute", left: 10, bottom: 8, right: 10, height: 3, background: "rgba(255,255,255,0.15)", borderRadius: 2 }}>
                <div style={{ width: "0%", height: "100%", background: "#4a7c4e", borderRadius: 2 }} />
              </div>
            </div>
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <MkPill tone="off">待機中</MkPill>
              <span style={{ fontSize: 11.5, color: "#6b6559" }}>スケジュール未設定</span>
            </div>
          </MkCard>

          {/* System health */}
          <MkCard>
            <MkSectionTitle title="システム状態" />
            {[
              { label: "Slack Webhook",    tone: (notifySettings["slack"]?.["webhook_url"] ? "live" : "off") as "live" | "off", value: notifySettings["slack"]?.["webhook_url"] ? "設定済" : "未設定" },
              { label: "Chatwork API",     tone: (notifySettings["chatwork"]?.["api_token"] ? "live" : "off") as "live" | "off", value: notifySettings["chatwork"]?.["api_token"] ? "設定済" : "未設定" },
              { label: "PWA Push (VAPID)", tone: (notifySettings["vapid"]?.["public_key"] ? "live" : "off") as "live" | "off",  value: notifySettings["vapid"]?.["public_key"] ? "設定済" : "未設定" },
              { label: "ロッカー制御",      tone: "off" as const,     value: "Phase 2" },
              { label: "Google Calendar",  tone: "off" as const,     value: "Phase 2" },
            ].map((item, i) => (
              <div key={item.label} style={{ display: "flex", alignItems: "center", padding: "8px 0", borderTop: i > 0 ? "1px solid #efece5" : "none" }}>
                <span style={{ flex: 1, fontSize: 12, color: "#2d2a24" }}>{item.label}</span>
                <MkPill tone={item.tone}>{item.value}</MkPill>
              </div>
            ))}
          </MkCard>
        </div>
      </div>
    </AdminShell>
  );
}

function StatCard({ label, value, unit, accent, delta }: { label: string; value: string; unit: string; accent?: string; delta?: string }) {
  return (
    <MkCard padding="18px" style={{ flex: 1 }}>
      <div style={{ fontSize: 11.5, color: "#a8a198", letterSpacing: "0.2px" }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 8 }}>
        <div style={{ fontSize: 30, fontWeight: 600, color: accent ?? "#1d1a15", letterSpacing: "-0.8px", lineHeight: 1 }}>
          {value}
        </div>
        {unit && <div style={{ fontSize: 13, color: "#a8a198" }}>{unit}</div>}
      </div>
      {delta && (
        <div style={{ fontSize: 11, color: "#6b6559", marginTop: 10, display: "flex", alignItems: "center", gap: 4 }}>
          → {delta}
        </div>
      )}
    </MkCard>
  );
}
