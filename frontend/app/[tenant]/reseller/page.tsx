"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useParams } from "next/navigation";
import { api, ResellerStats } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle } from "@/components/AdminShell";

export default function ResellerDashboard() {
  const router = useRouter();
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant ?? "";
  const [stats, setStats] = useState<ResellerStats | null>(null);
  const [loading, setLoading] = useState(true);
  const token = getAccessToken() ?? "";

  useEffect(() => {
    api.getResellerStats(token).then(setStats).finally(() => setLoading(false));
  }, []);

  const kpis = stats ? [
    { label: "顧客数", value: stats.customer_count, color: "#b8763a" },
    { label: "デバイス数", value: stats.device_count, color: "#4a7c4e" },
    { label: "ユーザー数", value: stats.user_count, color: "#2e6b8e" },
    { label: "累計受付数", value: stats.reception_count, color: "#6b4a9e" },
  ] : [];

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="代理店ダッシュボード" subtitle="管理している顧客テナントの概要" style={{ marginBottom: 24 }} />

      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 32 }}>
          {kpis.map((k) => (
            <MkCard key={k.label} style={{ textAlign: "center" as const }}>
              <div style={{ fontSize: 36, fontWeight: 700, color: k.color, letterSpacing: "-1px", marginBottom: 4 }}>{k.value}</div>
              <div style={{ fontSize: 12, color: "#a8a198" }}>{k.label}</div>
            </MkCard>
          ))}
        </div>
      )}

      <MkCard>
        <MkSectionTitle title="クイックアクション" />
        <div style={{ display: "flex", flexDirection: "column" as const, gap: 8 }}>
          {[
            { label: "顧客管理", path: `/${tenant}/reseller/customers`, desc: "顧客テナントの一覧・作成・削除" },
            { label: "ユーザー管理", path: `/${tenant}/reseller/users`, desc: "顧客テナントのユーザー確認" },
            { label: "デバイス管理", path: `/${tenant}/reseller/devices`, desc: "顧客テナントのデバイス確認" },
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
    </div>
  );
}
