"use client";

import { useEffect, useState, useRef } from "react";
import { api, OperatorTenant } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MkCard, MkBtn, MkSectionTitle } from "@/components/AdminShell";

const inputStyle: React.CSSProperties = {
  height: 34,
  border: "1px solid #efece5",
  borderRadius: 6,
  fontSize: 13,
  padding: "0 10px",
  outline: "none",
  background: "#faf8f4",
  color: "#1d1a15",
  width: "100%",
  boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  width: "auto",
  cursor: "pointer",
};

function TenantSelectModal({
  token,
  selectedIds,
  onConfirm,
  onClose,
}: {
  token: string;
  selectedIds: string[];
  onConfirm: (ids: string[]) => void;
  onClose: () => void;
}) {
  const [resellers, setResellers] = useState<OperatorTenant[]>([]);
  const [tenants, setTenants] = useState<OperatorTenant[]>([]);
  const [localSelected, setLocalSelected] = useState<Set<string>>(new Set(selectedIds));
  const [searchQ, setSearchQ] = useState("");
  const [filterReseller, setFilterReseller] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const LIMIT = 50;

  useEffect(() => {
    api.listResellers(token).then(setResellers);
  }, [token]);

  const loadTenants = (q: string, reseller_id: string, off: number, append: boolean) => {
    setLoading(true);
    api.listOperatorTenants(token, { q: q || undefined, reseller_id: reseller_id || undefined, offset: off, limit: LIMIT })
      .then((data) => {
        setTenants((prev) => append ? [...prev, ...data] : data);
        setHasMore(data.length === LIMIT);
        setOffset(off + data.length);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadTenants(searchQ, filterReseller, 0, false);
  }, []);

  const handleSearchChange = (v: string) => {
    setSearchQ(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setOffset(0);
      loadTenants(v, filterReseller, 0, false);
    }, 300);
  };

  const handleResellerChange = (v: string) => {
    setFilterReseller(v);
    setOffset(0);
    loadTenants(searchQ, v, 0, false);
  };

  const handleLoadMore = () => {
    loadTenants(searchQ, filterReseller, offset, true);
  };

  const toggle = (id: string) => {
    setLocalSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: "#fffefb", borderRadius: 12, padding: 24, width: 560, maxHeight: "70vh", overflow: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#1d1a15" }}>テナントを選択</div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={inputStyle}
            placeholder="テナント名・スラッグで検索"
            value={searchQ}
            onChange={(e) => handleSearchChange(e.target.value)}
          />
          <select
            style={{ ...selectStyle, width: "100%", boxSizing: "border-box" }}
            value={filterReseller}
            onChange={(e) => handleResellerChange(e.target.value)}
          >
            <option value="">全代理店</option>
            {resellers.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>

        <div style={{ fontSize: 12, color: "#a8a198" }}>{localSelected.size} テナント選択中</div>

        <div style={{ border: "1px solid #e2ddd6", borderRadius: 8, overflow: "auto", maxHeight: 340 }}>
          {tenants.map((t) => (
            <label key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid #f4f1ea", cursor: "pointer" }}>
              <input type="checkbox" checked={localSelected.has(t.id)} onChange={() => toggle(t.id)} />
              <span style={{ fontSize: 13, color: "#1d1a15" }}>{t.name}</span>
              <span style={{ fontSize: 11, color: "#a8a198", fontFamily: '"JetBrains Mono", monospace' }}>{t.slug}</span>
            </label>
          ))}
          {tenants.length === 0 && !loading && (
            <div style={{ padding: 16, textAlign: "center", color: "#a8a198", fontSize: 13 }}>テナントがありません</div>
          )}
          {loading && (
            <div style={{ padding: 16, textAlign: "center", color: "#a8a198", fontSize: 13 }}>読み込み中…</div>
          )}
          {hasMore && !loading && (
            <div style={{ padding: "10px 14px" }}>
              <button
                type="button"
                onClick={handleLoadMore}
                style={{ fontSize: 13, color: "#4a7c4e", background: "none", border: "none", cursor: "pointer", padding: 0 }}
              >
                もっと読み込む
              </button>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <MkBtn variant="default" type="button" onClick={onClose}>キャンセル</MkBtn>
          <MkBtn variant="primary" type="button" onClick={() => onConfirm(Array.from(localSelected))}>確定</MkBtn>
        </div>
      </div>
    </div>
  );
}

export default function OperatorBroadcastPage() {
  const [message, setMessage] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedTenants, setSelectedTenants] = useState<Map<string, string>>(new Map());
  const [allTenants, setAllTenants] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ updated_tenants: number; message: string } | null>(null);
  const [error, setError] = useState("");

  const token = getAccessToken() ?? "";

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

  const handleModalConfirm = (ids: string[]) => {
    setSelectedIds(ids);
    api.listOperatorTenants(token, { limit: 200 }).then((all) => {
      const map = new Map<string, string>();
      all.forEach((t) => { if (ids.includes(t.id)) map.set(t.id, t.name); });
      setSelectedTenants(map);
    });
    setModalOpen(false);
  };

  const removeSelected = (id: string) => {
    setSelectedIds((prev) => prev.filter((x) => x !== id));
    setSelectedTenants((prev) => { const next = new Map(prev); next.delete(id); return next; });
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
                <input type="radio" checked={allTenants} onChange={() => setAllTenants(true)} /> 全テナントに送信
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: "#1d1a15" }}>
                <input type="radio" checked={!allTenants} onChange={() => setAllTenants(false)} /> テナントを指定
              </label>
            </div>

            {!allTenants && (
              <div>
                <MkBtn variant="default" type="button" onClick={() => setModalOpen(true)}>
                  テナントを選択 {selectedIds.length > 0 ? `（${selectedIds.length}）` : ""}
                </MkBtn>
                {selectedIds.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                    {selectedIds.map((id) => (
                      <span
                        key={id}
                        style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "#edf7ee", border: "1px solid #86efac", borderRadius: 999, padding: "3px 10px", fontSize: 12, color: "#166534" }}
                      >
                        {selectedTenants.get(id) ?? id}
                        <button
                          type="button"
                          onClick={() => removeSelected(id)}
                          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "#166534", fontSize: 14 }}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
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

      {modalOpen && (
        <TenantSelectModal
          token={token}
          selectedIds={selectedIds}
          onConfirm={handleModalConfirm}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );
}
