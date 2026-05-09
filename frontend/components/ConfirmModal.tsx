"use client";

import { useEffect } from "react";

interface Props {
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const FONT_JP = '"Noto Sans JP", "Inter", system-ui, sans-serif';

export function ConfirmModal({
  message,
  confirmLabel = "削除する",
  cancelLabel = "キャンセル",
  onConfirm,
  onCancel,
}: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(29,26,21,0.45)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 16px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fffefb",
          border: "1px solid #d8d3c7",
          borderRadius: 12,
          padding: "28px 28px 24px",
          maxWidth: 380,
          width: "100%",
          boxShadow: "0 8px 32px rgba(29,26,21,0.18)",
          fontFamily: FONT_JP,
        }}
      >
        <p style={{ margin: "0 0 24px", fontSize: 14, color: "#2d2a24", lineHeight: 1.6 }}>
          {message}
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "8px 18px",
              borderRadius: 7,
              border: "1px solid #d8d3c7",
              background: "#f4f1ea",
              color: "#6b6559",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              fontFamily: FONT_JP,
            }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: "8px 18px",
              borderRadius: 7,
              border: "none",
              background: "#a84238",
              color: "#fffefb",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: FONT_JP,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
