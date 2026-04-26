"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { KioskScaler } from "@/components/KioskScaler";

const IDLE_TIMEOUT_MS = 60_000;
const KIOSK_TOKEN_KEY = "mokuture_kiosk_token";

type FieldKey = "visitor_name" | "company" | "staff" | "purpose";

const FIELDS: { key: FieldKey; label: string; placeholder: string; required?: boolean }[] = [
  { key: "visitor_name", label: "お名前",   placeholder: "山田 太郎",           required: true },
  { key: "company",      label: "会社名",   placeholder: "株式会社 〇〇" },
  { key: "staff",        label: "ご担当者名", placeholder: "担当者のお名前" },
  { key: "purpose",      label: "ご用件",   placeholder: "お打ち合わせ など" },
];

const KB_ROWS = [
  ["1","2","3","4","5","6","7","8","9","0"],
  ["q","w","e","r","t","y","u","i","o","p"],
  ["a","s","d","f","g","h","j","k","l"],
  ["shift","z","x","c","v","b","n","m","⌫"],
];

export default function KioskFormPage() {
  const params = useParams<{ tenant: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const idleRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [form, setForm] = useState<Record<FieldKey, string>>({
    visitor_name: "", company: "", staff: "",
    purpose: searchParams.get("purpose") ?? "",
  });
  const [focusedField, setFocusedField] = useState<FieldKey>("visitor_name");
  const [shifted, setShifted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState("");

  const resetIdle = useCallback(() => {
    if (idleRef.current) clearTimeout(idleRef.current);
    idleRef.current = setTimeout(() => router.push(`/${params.tenant}/kiosk`), IDLE_TIMEOUT_MS);
  }, [params.tenant, router]);

  useEffect(() => {
    if (!localStorage.getItem(KIOSK_TOKEN_KEY)) {
      router.replace(`/${params.tenant}/kiosk/setup`);
      return;
    }
    resetIdle();
    const tick = () => {
      const d = new Date();
      setNow(`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")} · ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`);
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => { if (idleRef.current) clearTimeout(idleRef.current); clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleKey = (key: string) => {
    resetIdle();
    if (key === "⌫") {
      setForm(f => ({ ...f, [focusedField]: f[focusedField].slice(0, -1) }));
    } else if (key === "shift") {
      setShifted(s => !s);
    } else if (key === "space") {
      setForm(f => ({ ...f, [focusedField]: f[focusedField] + " " }));
    } else {
      const char = shifted ? key.toUpperCase() : key;
      setForm(f => ({ ...f, [focusedField]: f[focusedField] + char }));
      if (shifted) setShifted(false);
    }
  };

  const handleSubmit = async () => {
    if (!form.visitor_name.trim()) { setError("お名前を入力してください"); return; }
    const kioskToken = localStorage.getItem(KIOSK_TOKEN_KEY);
    if (!kioskToken) { router.replace(`/${params.tenant}/kiosk/setup`); return; }
    setSubmitting(true);
    try {
      await api.createKioskReception(kioskToken, {
        visitor_name: form.visitor_name, company: form.company,
        purpose: form.purpose, staff: form.staff, method: "form",
      });
      router.push(`/${params.tenant}/kiosk/calling?name=${encodeURIComponent(form.visitor_name)}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付に失敗しました");
      setSubmitting(false);
    }
  };

  return (
    <KioskScaler bg="#faf8f4">
      <div
        style={{ width: 1920, height: 1080, background: "#faf8f4", display: "flex", flexDirection: "column", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}
        onClick={resetIdle}
      >
        {/* Brand */}
        <div style={{ padding: "28px 80px 0", display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
          <div style={{ width: 48, height: 48, borderRadius: 4, border: "1.5px solid #1d1a15", color: "#1d1a15", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 500, letterSpacing: -1, fontFamily: "Inter, system-ui, sans-serif" }}>磯</div>
          <div>
            <div style={{ fontSize: 11, letterSpacing: 3.2, textTransform: "uppercase" as const, color: "#a8a198", marginBottom: 4, fontFamily: "Inter, system-ui, sans-serif" }}>EST. 1948</div>
            <div style={{ fontSize: 20, fontWeight: 500, letterSpacing: -0.2, color: "#1d1a15" }}>磯野木工所</div>
          </div>
        </div>

        {/* Body: left=fields, right=keyboard */}
        <div style={{ flex: 1, padding: "16px 80px 0", display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 48, minHeight: 0 }}>
          {/* Left: fields */}
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <button
              onClick={() => router.push(`/${params.tenant}/kiosk/top`)}
              style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8, padding: "10px 18px", background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 999, fontSize: 14, color: "#6b6559", marginBottom: 16, cursor: "pointer", fontFamily: "inherit" }}
            >
              ← 戻る
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 18 }}>
              <div style={{ fontSize: 14, color: "#a8a198", letterSpacing: 4, textTransform: "uppercase" as const, fontFamily: "Inter, system-ui, sans-serif" }}>FORM</div>
              <div style={{ display: "flex", gap: 6 }}>
                <span style={{ width: 32, height: 5, borderRadius: 3, background: "#4a7c4e" }} />
                <span style={{ width: 32, height: 5, borderRadius: 3, background: "#efece5" }} />
              </div>
            </div>

            <div style={{ fontSize: 44, fontWeight: 600, color: "#1d1a15", letterSpacing: -1.4, lineHeight: 1.15, marginBottom: 22 }}>
              ご来訪情報を<br />ご記入ください
            </div>

            {error && (
              <div style={{ marginBottom: 14, background: "#f6e0dc", border: "1px solid rgba(168,66,56,0.35)", borderRadius: 12, padding: "12px 16px", color: "#a84238", fontSize: 15 }}>{error}</div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
              {FIELDS.slice(0, 2).map(f => {
                const isFocused = focusedField === f.key;
                return (
                  <div key={f.key}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7 }}>
                      <span style={{ fontSize: 15, fontWeight: 600, color: "#2d2a24" }}>{f.label}</span>
                      {f.required && <span style={{ fontSize: 10, color: "#a84238", background: "#f6e0dc", padding: "2px 8px", borderRadius: 4, fontWeight: 600, letterSpacing: 0.5 }}>必須</span>}
                    </div>
                    <div
                      onClick={() => { setFocusedField(f.key); resetIdle(); }}
                      style={{
                        background: "#fffefb", border: `2px solid ${isFocused ? "#4a7c4e" : form[f.key] ? "#4a7c4e" : "#d8d3c7"}`,
                        borderRadius: 11, padding: "14px 20px", fontSize: 22,
                        color: form[f.key] ? "#2d2a24" : "#a8a198",
                        boxShadow: isFocused ? "0 0 0 4px #eaf0e8" : "none",
                        cursor: "default", minHeight: 60, display: "flex", alignItems: "center",
                        transition: "border-color 0.15s, box-shadow 0.15s",
                      }}
                    >
                      {form[f.key] || f.placeholder}
                      {isFocused && <span style={{ display: "inline-block", width: 2, height: 26, background: "#4a7c4e", marginLeft: 4, animation: "kiosk-cursor-blink 1s step-end infinite" }} />}
                    </div>
                  </div>
                );
              })}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                {FIELDS.slice(2).map(f => {
                  const isFocused = focusedField === f.key;
                  return (
                    <div key={f.key}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7 }}>
                        <span style={{ fontSize: 15, fontWeight: 600, color: "#2d2a24" }}>{f.label}</span>
                        {f.required && <span style={{ fontSize: 10, color: "#a84238", background: "#f6e0dc", padding: "2px 8px", borderRadius: 4, fontWeight: 600 }}>必須</span>}
                      </div>
                      <div
                        onClick={() => { setFocusedField(f.key); resetIdle(); }}
                        style={{
                          background: "#fffefb", border: `2px solid ${isFocused ? "#4a7c4e" : form[f.key] ? "#4a7c4e" : "#d8d3c7"}`,
                          borderRadius: 11, padding: "14px 20px", fontSize: 20,
                          color: form[f.key] ? "#2d2a24" : "#a8a198",
                          boxShadow: isFocused ? "0 0 0 4px #eaf0e8" : "none",
                          cursor: "default", minHeight: 56, display: "flex", alignItems: "center",
                          transition: "border-color 0.15s, box-shadow 0.15s",
                        }}
                      >
                        {form[f.key] || f.placeholder}
                        {isFocused && <span style={{ display: "inline-block", width: 2, height: 22, background: "#4a7c4e", marginLeft: 4, animation: "kiosk-cursor-blink 1s step-end infinite" }} />}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Right: keyboard */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", minHeight: 0, paddingBottom: 24 }}>
            <div style={{ background: "#f4f1ea", borderRadius: 18, padding: 12, border: "1px solid #efece5" }}>
              {KB_ROWS.map((row, ri) => (
                <div key={ri} style={{ display: "flex", gap: 5, marginBottom: ri < KB_ROWS.length - 1 ? 5 : 0, justifyContent: "center", paddingLeft: ri === 2 ? 24 : 0 }}>
                  {row.map((k) => {
                    const isShift = k === "shift";
                    const isDel = k === "⌫";
                    const isWide = isShift || isDel;
                    return (
                      <button
                        key={k}
                        onMouseDown={(e) => { e.preventDefault(); handleKey(k); }}
                        onTouchStart={(e) => { e.preventDefault(); handleKey(k); }}
                        style={{
                          flex: isWide ? 1.8 : 1,
                          height: 62, background: (isShift && shifted) ? "#1d1a15" : "#fffefb",
                          border: "1px solid #d8d3c7",
                          borderRadius: 9,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: isWide ? 14 : 24,
                          fontWeight: isWide ? 600 : 400,
                          color: (isShift && shifted) ? "#ffffff" : "#2d2a24",
                          cursor: "pointer",
                          fontFamily: "Inter, system-ui, sans-serif",
                          userSelect: "none",
                          transition: "background 0.1s",
                        }}
                      >
                        {k === "shift" ? "⇧" : (shifted && !isShift && !isDel ? k.toUpperCase() : k)}
                      </button>
                    );
                  })}
                </div>
              ))}
              {/* Bottom row: space + submit */}
              <div style={{ display: "flex", gap: 5, marginTop: 5, justifyContent: "center" }}>
                <button
                  onMouseDown={(e) => { e.preventDefault(); handleKey("space"); }}
                  onTouchStart={(e) => { e.preventDefault(); handleKey("space"); }}
                  style={{ flex: 2, height: 62, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "#6b6559", cursor: "pointer", fontFamily: "inherit", userSelect: "none" }}
                >
                  かな / ABC
                </button>
                <button
                  onMouseDown={(e) => { e.preventDefault(); handleKey("space"); }}
                  onTouchStart={(e) => { e.preventDefault(); handleKey("space"); }}
                  style={{ flex: 5, height: 62, background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 9, cursor: "pointer", userSelect: "none" }}
                />
                <button
                  onClick={handleSubmit}
                  disabled={submitting}
                  style={{
                    flex: 2, height: 62, background: submitting ? "#7a9e7d" : "#1d1a15",
                    borderRadius: 9, border: "none",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 16, color: "#ffffff", fontWeight: 600,
                    cursor: submitting ? "not-allowed" : "pointer",
                    fontFamily: "inherit", userSelect: "none",
                  }}
                >
                  {submitting ? (
                    <div style={{ width: 22, height: 22, borderRadius: "50%", border: "2.5px solid rgba(255,255,255,0.3)", borderTopColor: "#ffffff", animation: "kiosk-spin 0.7s linear infinite" }} />
                  ) : "送信 →"}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: "12px 80px 20px", display: "flex", alignItems: "center", color: "#a8a198", fontSize: 13, flexShrink: 0 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 14 }}>{now}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: "JetBrains Mono, monospace" }}>kiosk-hq-1f-01</span>
        </div>
      </div>

      <style>{`
        @keyframes kiosk-spin { to { transform: rotate(360deg); } }
        @keyframes kiosk-cursor-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>
    </KioskScaler>
  );
}
