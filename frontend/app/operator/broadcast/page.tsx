"use client";

import { useEffect, useState } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

export default function OperatorBroadcastPage() {
  const [message, setMessage] = useState("");
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [allTenants, setAllTenants] = useState(true);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ updated_tenants: number; message: string } | null>(null);
  const [error, setError] = useState("");

  const token = getAccessToken() ?? "";

  useEffect(() => {
    api.listOperatorTenants(token).then(setTenants);
  }, []);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirm(`「${message}」を${allTenants ? "全テナント" : `${selectedIds.length} テナント`}に緊急配信しますか？`)) return;
    setSending(true); setError(""); setResult(null);
    try {
      const r = await api.emergencyBroadcast(token, message, allTenants ? undefined : selectedIds);
      setResult(r);
      setMessage("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setSending(false);
    }
  };

  const toggleTenant = (id: string) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  return (
    <div style={{ padding: "28px 32px", maxWidth: 720 }}>
      <MkSectionTitle title="緊急配信" subtitle="全テナントのキオスクデバイスに緊急メッセージを配信します" style={{ marginBottom: 24 }} />

      <div style={{ background: "#fff8f0", border: "1px solid #fde8c0", borderRadius: 10, padding: "14px 18px", marginBottom: 24 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#b8763a", marginBottom: 6 }}>⚠ 緊急配信について</div>
        <div style={{ fontSize: 13, color: "#6b6559", lineHeight: 1.7 }}>
          送信すると対象テナントのキオスクデバイスが強制更新されます。<br/>
          メッセージは「担当者呼び出し中」のキオスク画面に表示されます。
        </div>
      </div>

      <MkCard>
        <form onSubmit={handleSend}>
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", display: "block", marginBottom: 8 }}>緊急メッセージ</label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
              rows={3}
              placeholder="例：本日は臨時休業のため、受付を停止しています。"
              style={{ width: "100%", border: "1px solid #e2ddd6", borderRadius: 8, padding: "12px 14px", fontSize: 14, color: "#1d1a15", background: "#faf8f4", outline: "none", resize: "vertical" as const, boxSizing: "border-box" as const }}
              onFocus={(e) => { e.currentTarget.style.borderColor = "#4a7c4e"; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "#e2ddd6"; }}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#1d1a15", display: "block", marginBottom: 12 }}>配信対象</label>
            <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: "#1d1a15" }}>
                <input type="radio" checked={allTenants} onChange={() => setAllTenants(true)} /> 全テナント（{tenants.length}）
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: "#1d1a15" }}>
                <input type="radio" checked={!allTenants} onChange={() => setAllTenants(false)} /> テナントを選択
              </label>
            </div>
            {!allTenants && (
              <div style={{ border: "1px solid #e2ddd6", borderRadius: 8, maxHeight: 200, overflow: "auto" }}>
                {tenants.map((t) => (
                  <label key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid #f4f1ea", cursor: "pointer" }}>
                    <input type="checkbox" checked={selectedIds.includes(t.id)} onChange={() => toggleTenant(t.id)} />
                    <span style={{ fontSize: 13, color: "#1d1a15" }}>{t.name}</span>
                    <span style={{ fontSize: 11, color: "#a8a198", fontFamily: '"JetBrains Mono", monospace' }}>{t.slug}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {error && <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 12px", marginBottom: 12, fontSize: 13, color: "#dc2626" }}>{error}</div>}
          {result && (
            <div style={{ background: "#f0f9f0", border: "1px solid #86efac", borderRadius: 6, padding: "10px 12px", marginBottom: 12, fontSize: 13, color: "#166534" }}>
              ✓ {result.updated_tenants} テナントに配信しました
            </div>
          )}

          <MkBtn variant="danger" type="submit" disabled={sending || (!allTenants && selectedIds.length === 0)}>
            {sending ? "配信中…" : "緊急配信を送信"}
          </MkBtn>
        </form>
      </MkCard>
    </div>
  );
}
