"use client";

import { useEffect, useState } from "react";
import { api, OperatorDevice } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkSectionTitle, MkPill } from "@/components/AdminShell";

export default function OperatorDevicesPage() {
  const [devices, setDevices] = useState<OperatorDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const token = getAccessToken() ?? "";

  useEffect(() => {
    api.listOperatorDevices(token).then(setDevices).finally(() => setLoading(false));
  }, []);

  const isOnline = (lastSeen: string | null) => {
    if (!lastSeen) return false;
    return Date.now() - new Date(lastSeen).getTime() < 5 * 60 * 1000;
  };

  return (
    <div style={{ padding: "28px 32px" }}>
      <MkSectionTitle title="デバイス管理" subtitle={`${devices.length} デバイス（全テナント）`} style={{ marginBottom: 24 }} />
      {loading ? (
        <div style={{ color: "#a8a198", fontSize: 14 }}>読み込み中…</div>
      ) : (
        <MkCard padding="0">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #efece5" }}>
                {["デバイス名", "ステータス", "テナントID", "最終接続"].map((h) => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left" as const, fontSize: 11, fontWeight: 600, color: "#a8a198", letterSpacing: "0.4px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id} style={{ borderBottom: "1px solid #f4f1ea" }}>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: "#1d1a15" }}>{d.name}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <MkPill tone={isOnline(d.last_seen_at) ? "live" : "off"}>{isOnline(d.last_seen_at) ? "オンライン" : "オフライン"}</MkPill>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontFamily: '"JetBrains Mono", monospace', fontSize: 11 }}>{d.tenant_id}</td>
                  <td style={{ padding: "12px 16px", color: "#a8a198", fontSize: 12 }}>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString("ja-JP") : "未接続"}</td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr><td colSpan={4} style={{ padding: "24px", textAlign: "center" as const, color: "#a8a198" }}>デバイスがありません</td></tr>
              )}
            </tbody>
          </table>
        </MkCard>
      )}
    </div>
  );
}
