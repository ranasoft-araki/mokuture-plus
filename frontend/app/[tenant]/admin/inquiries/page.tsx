"use client";

import { useEffect, useState, useCallback } from "react";
import { AdminShell, MkBtn, MkCard } from "@/components/AdminShell";
import { api, Inquiry } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const STATE_LABEL: Record<string, string> = { new: "未読", read: "既読", archived: "対応済み" };
const STATE_COLOR: Record<string, string> = { new: "#f59e0b", read: "#3b82f6", archived: "#9ca3af" };

function fmt(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return iso;
  }
}

export default function InquiriesPage() {
  const [items, setItems] = useState<Inquiry[]>([]);
  const [loading, setLoading] = useState(true);
  const [stateFilter, setStateFilter] = useState("");

  const load = useCallback(() => {
    const token = getAccessToken();
    if (!token) return;
    setLoading(true);
    api.listInquiries(token, stateFilter ? { state: stateFilter } : undefined)
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [stateFilter]);

  useEffect(() => { load(); }, [load]);

  const setState = (id: string, state: "new" | "read" | "archived") => {
    const token = getAccessToken();
    if (!token) return;
    api.updateInquiry(token, id, state)
      .then((updated) => setItems((prev) => prev.map((it) => (it.id === id ? updated : it))))
      .catch(() => {});
  };

  const remove = (id: string) => {
    const token = getAccessToken();
    if (!token) return;
    api.deleteInquiry(token, id)
      .then(() => setItems((prev) => prev.filter((it) => it.id !== id)))
      .catch(() => {});
  };

  const newCount = items.filter((it) => it.state === "new").length;

  return (
    <AdminShell
      active="inquiries"
      title="問い合わせ"
      breadcrumb="ホーム / 問い合わせ"
      subtitle="mokuture 共通問い合わせフォームからの受信内容"
      actions={
        <>
          <select
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            style={{ border: "1px solid #d8d3c7", borderRadius: 8, background: "#fffefb", padding: "6px 10px", fontSize: 12.5, color: "#2d2a24" }}
          >
            <option value="">すべて</option>
            <option value="new">未読</option>
            <option value="read">既読</option>
            <option value="archived">対応済み</option>
          </select>
          <MkBtn variant="default" size="sm" onClick={load}>更新</MkBtn>
        </>
      }
    >
      {newCount > 0 && (
        <div style={{ background: "#fef6e6", border: "1px solid #f5d99a", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#8a5a10", marginBottom: 14 }}>
          未読の問い合わせが {newCount} 件あります
        </div>
      )}

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", color: "#a8a198", fontSize: 13 }}>読み込み中…</div>
      ) : items.length === 0 ? (
        <MkCard>
          <div style={{ padding: 40, textAlign: "center", color: "#a8a198", fontSize: 14 }}>問い合わせはまだありません</div>
        </MkCard>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((it) => (
            <MkCard key={it.id}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
                    <span style={{ fontSize: 16, fontWeight: 700, color: "#1d1a15" }}>{it.name}</span>
                    {it.company && <span style={{ fontSize: 13, color: "#6b6559" }}>{it.company}</span>}
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: STATE_COLOR[it.state] ?? "#9ca3af", borderRadius: 10, padding: "2px 9px" }}>
                      {STATE_LABEL[it.state] ?? it.state}
                    </span>
                    <span style={{ fontSize: 12, color: "#a8a198", fontFamily: "monospace", marginLeft: "auto" }}>{fmt(it.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 14, color: "#2d2a24", lineHeight: 1.7, whiteSpace: "pre-wrap", background: "#f4f1ea", borderRadius: 8, padding: "12px 14px" }}>
                    {it.message}
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 10, fontSize: 12.5, color: "#6b6559" }}>
                    {it.email && <span>✉ <a href={`mailto:${it.email}`} style={{ color: "#2e5c32" }}>{it.email}</a></span>}
                    {it.phone && <span>☎ <a href={`tel:${it.phone}`} style={{ color: "#2e5c32" }}>{it.phone}</a></span>}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
                {it.state !== "read" && <MkBtn variant="default" size="sm" onClick={() => setState(it.id, "read")}>既読にする</MkBtn>}
                {it.state !== "archived" && <MkBtn variant="default" size="sm" onClick={() => setState(it.id, "archived")}>対応済みにする</MkBtn>}
                <MkBtn variant="ghost" size="sm" onClick={() => remove(it.id)}>削除</MkBtn>
              </div>
            </MkCard>
          ))}
        </div>
      )}
    </AdminShell>
  );
}
