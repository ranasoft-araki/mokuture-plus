"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AdminShell, MkBtn, MkSectionTitle } from "@/components/AdminShell";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, Locker } from "@/lib/api";
import { getAccessToken, clearTokens } from "@/lib/auth";

const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

// ─── Input style helper ────────────────────────────────────────────────────
const inputStyle: React.CSSProperties = {
  width: "100%",
  border: "1px solid #d8d3c7",
  borderRadius: 7,
  padding: "0 12px",
  height: 34,
  fontSize: 12.5,
  color: "#2d2a24",
  outline: "none",
  boxSizing: "border-box",
  background: "#fffefb",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11.5,
  fontWeight: 600,
  color: "#2d2a24",
  marginBottom: 6,
};

// ─── Locker Card ───────────────────────────────────────────────────────────
function LockerCard({
  locker,
  onOpen,
  onClose,
  onDelete,
}: {
  locker: Locker;
  onOpen: () => void;
  onClose: () => void;
  onDelete: () => void;
}) {
  const isOpen = locker.state === "open";

  return (
    <div
      style={{
        background: "#fffefb",
        border: "1px solid #d8d3c7",
        borderRadius: 10,
        padding: "16px 14px",
        position: "relative",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Delete button (×) */}
      <button
        onClick={onDelete}
        title="削除"
        style={{
          position: "absolute",
          top: 8,
          right: 8,
          width: 22,
          height: 22,
          borderRadius: "50%",
          border: "1px solid #d8d3c7",
          background: "#f4f1ea",
          color: "#a8a198",
          fontSize: 12,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          lineHeight: 1,
          padding: 0,
        }}
      >
        ×
      </button>

      {/* Name */}
      <div style={{ fontSize: 15, fontWeight: 700, color: "#1d1a15", paddingRight: 24 }}>
        {locker.name}
      </div>

      {/* GPIO Pin */}
      <div
        style={{
          fontSize: 12,
          fontFamily: FONT_MONO,
          color: "#a8a198",
        }}
      >
        Pin #{locker.gpio_pin}
      </div>

      {/* State badge */}
      <div>
        <span
          style={{
            display: "inline-block",
            padding: "3px 10px",
            borderRadius: 999,
            fontSize: 11.5,
            fontWeight: 600,
            background: isOpen ? "#dc2626" : "#4a7c4e",
            color: "#fffefb",
          }}
        >
          {isOpen ? "開錠中" : "施錠中"}
        </span>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 6 }}>
        <button
          onClick={onOpen}
          disabled={isOpen}
          style={{
            flex: 1,
            padding: "7px 0",
            borderRadius: 7,
            border: "none",
            background: isOpen ? "#e8e4dc" : "#c8a96e",
            color: isOpen ? "#a8a198" : "#fffefb",
            fontSize: 12.5,
            fontWeight: 600,
            cursor: isOpen ? "not-allowed" : "pointer",
            opacity: isOpen ? 0.6 : 1,
          }}
        >
          開錠
        </button>
        <button
          onClick={onClose}
          disabled={!isOpen}
          style={{
            flex: 1,
            padding: "7px 0",
            borderRadius: 7,
            border: "none",
            background: !isOpen ? "#e8e4dc" : "#6b6559",
            color: !isOpen ? "#a8a198" : "#fffefb",
            fontSize: 12.5,
            fontWeight: 600,
            cursor: !isOpen ? "not-allowed" : "pointer",
            opacity: !isOpen ? 0.6 : 1,
          }}
        >
          施錠
        </button>
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────
export default function AdminLockerPage() {
  const router = useRouter();
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [modal, setModal] = useState<{ msg: string; action: () => Promise<void> } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formGpioPin, setFormGpioPin] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { clearTokens(); router.push("/login"); return; }
    api.listLockers(token)
      .then((data) => setLockers(data))
      .catch(() => { clearTokens(); router.push("/login"); })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const token = getAccessToken();
    if (!token) return;
    const pin = parseInt(formGpioPin, 10);
    if (!formName.trim()) { setFormError("名前を入力してください"); return; }
    if (isNaN(pin) || pin < 0) { setFormError("GPIOピン番号を正しく入力してください"); return; }
    setCreating(true);
    setFormError(null);
    try {
      const created = await api.createLocker(token, { name: formName.trim(), gpio_pin: pin });
      setLockers((prev) => [...prev, created]);
      setFormName("");
      setFormGpioPin("");
      setShowForm(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "追加に失敗しました");
    } finally {
      setCreating(false);
    }
  }

  async function handleOpen(lockerId: string) {
    const token = getAccessToken();
    if (!token) return;
    // Optimistic update
    setLockers((prev) =>
      prev.map((l) => (l.id === lockerId ? { ...l, state: "open" } : l))
    );
    try {
      await api.openLocker(token, lockerId);
    } catch (err: unknown) {
      // Revert on failure
      setLockers((prev) =>
        prev.map((l) => (l.id === lockerId ? { ...l, state: "closed" } : l))
      );
      setError(err instanceof Error ? err.message : "開錠に失敗しました");
    }
  }

  async function handleClose(lockerId: string) {
    const token = getAccessToken();
    if (!token) return;
    // Optimistic update
    setLockers((prev) =>
      prev.map((l) => (l.id === lockerId ? { ...l, state: "closed" } : l))
    );
    try {
      await api.closeLocker(token, lockerId);
    } catch (err: unknown) {
      // Revert on failure
      setLockers((prev) =>
        prev.map((l) => (l.id === lockerId ? { ...l, state: "open" } : l))
      );
      setError(err instanceof Error ? err.message : "施錠に失敗しました");
    }
  }

  function handleDelete(lockerId: string) {
    setModal({
      msg: "このロッカーを削除しますか？",
      action: async () => {
        const token = getAccessToken();
        if (!token) return;
        await api.deleteLocker(token, lockerId);
        setLockers((prev) => prev.filter((l) => l.id !== lockerId));
      },
    });
  }

  if (loading) {
    return (
      <AdminShell active="locker" title="ロッカー管理" breadcrumb="ホーム / ロッカー">
        <div style={{ textAlign: "center", color: "#a8a198", fontSize: 13, padding: "60px 0" }}>
          読み込み中...
        </div>
      </AdminShell>
    );
  }

  return (
    <>
    {modal && (
      <ConfirmModal
        message={modal.msg}
        onConfirm={async () => {
          const action = modal.action;
          setModal(null);
          try { await action(); } catch (err: unknown) { setError(err instanceof Error ? err.message : "削除に失敗しました"); }
        }}
        onCancel={() => setModal(null)}
      />
    )}
    <AdminShell
      active="locker"
      title="ロッカー管理"
      breadcrumb="ホーム / ロッカー"
      subtitle={`${lockers.length} 台`}
      actions={
        <MkBtn
          variant={showForm ? "default" : "primary"}
          size="sm"
          onClick={() => { setShowForm((v) => !v); setFormError(null); }}
        >
          {showForm ? "キャンセル" : "＋ ロッカーを追加"}
        </MkBtn>
      }
    >
      {/* Error banner */}
      {error && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 14px",
            borderRadius: 7,
            background: "#f6e0dc",
            border: "1px solid #a84238",
            color: "#a84238",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ flex: 1 }}>{error}</span>
          <button
            onClick={() => setError(null)}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#a84238", fontSize: 14 }}
          >
            ×
          </button>
        </div>
      )}

      {/* Create form panel */}
      {showForm && (
        <div
          style={{
            marginBottom: 20,
            background: "#fffefb",
            border: "1px solid #d8d3c7",
            borderRadius: 10,
            padding: 20,
          }}
        >
          <MkSectionTitle title="ロッカーを追加" />
          <form onSubmit={handleCreate}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
              <div>
                <label style={labelStyle}>ロッカー名</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="例: ロッカー A1"
                  style={inputStyle}
                  required
                />
              </div>
              <div>
                <label style={labelStyle}>GPIO ピン番号</label>
                <input
                  type="number"
                  min="0"
                  value={formGpioPin}
                  onChange={(e) => setFormGpioPin(e.target.value)}
                  placeholder="例: 18"
                  style={inputStyle}
                  required
                />
              </div>
            </div>
            {formError && (
              <div
                style={{
                  marginBottom: 12,
                  padding: "8px 12px",
                  background: "#f6e0dc",
                  border: "1px solid rgba(168,66,56,0.3)",
                  borderRadius: 7,
                  color: "#a84238",
                  fontSize: 12,
                }}
              >
                {formError}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <MkBtn variant="primary" size="sm" disabled={creating}>
                {creating ? "追加中…" : "追加"}
              </MkBtn>
            </div>
          </form>
        </div>
      )}

      {/* Locker grid */}
      {lockers.length === 0 ? (
        <div
          style={{
            background: "#fffefb",
            border: "1px solid #d8d3c7",
            borderRadius: 10,
            padding: "48px 0",
            textAlign: "center",
            color: "#a8a198",
            fontSize: 13,
          }}
        >
          ロッカーが登録されていません。<br />
          「＋ ロッカーを追加」ボタンで追加してください。
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 14,
          }}
        >
          {lockers.map((locker) => (
            <LockerCard
              key={locker.id}
              locker={locker}
              onOpen={() => handleOpen(locker.id)}
              onClose={() => handleClose(locker.id)}
              onDelete={() => handleDelete(locker.id)}
            />
          ))}
        </div>
      )}
    </AdminShell>
    </>
  );
}
