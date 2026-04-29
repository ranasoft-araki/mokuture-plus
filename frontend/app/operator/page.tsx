"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, OperatorStats } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle } from "@/components/AdminShell";

export default function OperatorDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<OperatorStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getOperatorStats(token)
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const kpis = stats ? [
    { label: "テナント数", value: stats.tenant_count, color: "#4a7c4e" },
    { label: "代理店数", value: stats.reseller_count, color: "#b8763a" },
    { label: "ユーザー数", value: stats.user_count, color: "#2e6b8e" },
    { label: "デバイス数", value: stats.device_count, color: "#6b4a9e" },
    { label: "累計受付数", value: stats.reception_count, color: "#a84238" },
  ] : [];

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="システム概要" subtitle="全テナント・全デバイスのリアルタイム状況" style={{ marginBottom: 24 }} />

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 32 }}>
          {kpis.map((k) => (
            <MkCard key={k.label} style={{ textAlign: "center" as const }}>
              <div style={{ fontSize: 36, fontWeight: 700, color: k.color, letterSpacing: "-1px", marginBottom: 4 }}>{k.value}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>{k.label}</div>
            </MkCard>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <MkCard>
          <MkSectionTitle title="クイックアクション" />
          <div style={{ display: "flex", flexDirection: "column" as const, gap: 8 }}>
            {[
              { label: "テナント管理", path: "/operator/tenants", desc: "全テナントの一覧・作成・削除" },
              { label: "代理店管理", path: "/operator/resellers", desc: "代理店の一覧・作成・削除" },
              { label: "ユーザー管理", path: "/operator/users", desc: "全ユーザーの確認" },
              { label: "デバイス管理", path: "/operator/devices", desc: "全RasPiデバイスの確認" },
              { label: "緊急配信", path: "/operator/broadcast", desc: "全テナントへの緊急メッセージ配信" },
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
