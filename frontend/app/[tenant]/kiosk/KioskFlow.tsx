"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, type PublicTenantSettings, getCachedKioskSettings, setCachedKioskSettings } from "@/lib/api";

type KioskScreen = "loading" | "suspended" | "ready";

export default function KioskFlow({ kioskToken }: { kioskToken: string }) {
  const params = useParams<{ tenant: string }>();
  const [settings, setSettings] = useState<PublicTenantSettings | null>(() =>
    getCachedKioskSettings(params.tenant)
  );
  const [suspended, setSuspended] = useState<boolean>(
    () => getCachedKioskSettings(params.tenant)?.is_suspended ?? false
  );
  const [screen, setScreen] = useState<KioskScreen>("loading");
  const settingsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scheduleIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const slug = params.tenant;

    const fetchSettings = async () => {
      try {
        const s = await api.getPublicTenantSettings(slug);
        setCachedKioskSettings(slug, s);
        setSettings(s);
        setSuspended(s.is_suspended);
      } catch {}
    };

    const fetchSchedule = async () => {
      try {
        const data = await api.getKioskSchedule(kioskToken);
        if (data.suspended === true) {
          setSuspended(true);
        }
      } catch {}
    };

    void fetchSettings().then(() => setScreen("ready"));
    void fetchSchedule();

    settingsIntervalRef.current = setInterval(fetchSettings, 60000);
    scheduleIntervalRef.current = setInterval(fetchSchedule, 60000);

    return () => {
      if (settingsIntervalRef.current) clearInterval(settingsIntervalRef.current);
      if (scheduleIntervalRef.current) clearInterval(scheduleIntervalRef.current);
    };
  }, [params.tenant, kioskToken]);

  if (suspended) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#2d2a24",
          color: "#fff",
          gap: 32,
          userSelect: "none",
          pointerEvents: "none",
          zIndex: 9999,
        }}
      >
        <div style={{ fontSize: 64, lineHeight: 1 }}>🔒</div>
        <h1
          style={{
            fontSize: 24,
            fontWeight: 700,
            margin: 0,
            textAlign: "center",
            letterSpacing: "0.02em",
          }}
        >
          このサービスは現在停止中です
        </h1>
        <p
          style={{
            fontSize: 16,
            margin: 0,
            opacity: 0.6,
            textAlign: "center",
          }}
        >
          詳細はスタッフにお問い合わせください
        </p>
      </div>
    );
  }

  if (screen === "loading" || !settings) {
    return (
      <div style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "rgba(255,255,255,0.4)", fontFamily: "Inter, system-ui, sans-serif", fontSize: 16 }}>
          読み込み中…
        </div>
      </div>
    );
  }

  return <ReceptionForm settings={settings} kioskToken={kioskToken} />;
}

// ─── Reception Form ───────────────────────────────────────────────────────────

function ReceptionForm({ settings, kioskToken }: { settings: PublicTenantSettings; kioskToken: string }) {
  const staffList = settings.staff_list ?? [];
  const useDropdown = staffList.length > 0;

  const [visitorName, setVisitorName] = useState("");
  const [company, setCompany] = useState("");
  const [staff, setStaff] = useState("");
  const [staffMode, setStaffMode] = useState<"dropdown" | "freetext">(
    useDropdown ? "dropdown" : "freetext"
  );
  const [purpose, setPurpose] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const bc = settings.brand_color;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!visitorName.trim()) {
      setError("お名前を入力してください");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.createKioskReception(kioskToken, {
        visitor_name: visitorName,
        company: company || undefined,
        purpose: purpose || undefined,
        staff: staff || undefined,
        method: "form",
      });
      setSubmitted(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "受付に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div style={{
        width: "100vw", height: "100vh", background: "#1d1a15",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24,
        fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
      }}>
        <div style={{ width: 80, height: 80, borderRadius: "50%", background: `${bc}33`, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <svg viewBox="0 0 24 24" fill="none" stroke={bc} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ width: 40, height: 40 }}>
            <path d="M5 12l5 5L20 6" />
          </svg>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 28, fontWeight: 600, color: "#fffefb" }}>{visitorName} 様</div>
          <div style={{ fontSize: 16, color: "rgba(255,255,255,0.5)", marginTop: 8 }}>
            {settings.kiosk_complete_message}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      width: "100vw", minHeight: "100vh", background: "#faf8f4",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      padding: "40px 24px",
      fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
    }}>
      <div style={{ width: "100%", maxWidth: 560 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: "#1d1a15", marginBottom: 32, letterSpacing: "-0.02em" }}>
          ご来訪情報をご記入ください
        </h1>

        {error && (
          <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#a84238", marginBottom: 16 }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Visitor name */}
          <FormField label="お名前" required>
            <input
              value={visitorName}
              onChange={(e) => setVisitorName(e.target.value)}
              placeholder="山田 太郎"
              style={inputStyle}
            />
          </FormField>

          {/* Company */}
          <FormField label="会社名">
            <input
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="株式会社 〇〇"
              style={inputStyle}
            />
          </FormField>

          {/* Staff — dropdown or free text */}
          <FormField label="ご担当者名">
            {useDropdown && staffMode === "dropdown" ? (
              <div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: staff ? 8 : 0 }}>
                  {staffList.map((name) => (
                    <button
                      key={name}
                      type="button"
                      onClick={() => setStaff(name)}
                      style={{
                        padding: "8px 16px",
                        borderRadius: 999,
                        border: `2px solid ${staff === name ? bc : "#d8d3c7"}`,
                        background: staff === name ? bc : "transparent",
                        color: staff === name ? "#fff" : "#2d2a24",
                        fontSize: 14,
                        cursor: "pointer",
                        transition: "background .12s, color .12s, border-color .12s",
                      }}
                    >
                      {name}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => { setStaff(""); setStaffMode("freetext"); }}
                    style={{
                      padding: "8px 16px",
                      borderRadius: 999,
                      border: "2px solid #d8d3c7",
                      background: "transparent",
                      color: "#6b6559",
                      fontSize: 14,
                      cursor: "pointer",
                    }}
                  >
                    直接入力...
                  </button>
                </div>
                {staff && (
                  <div style={{ fontSize: 12, color: "#6b6559" }}>
                    選択中: <strong>{staff}</strong>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <input
                  value={staff}
                  onChange={(e) => setStaff(e.target.value)}
                  placeholder="担当者のお名前"
                  style={inputStyle}
                  autoFocus={useDropdown}
                />
                {useDropdown && (
                  <button
                    type="button"
                    onClick={() => { setStaff(""); setStaffMode("dropdown"); }}
                    style={{
                      alignSelf: "flex-start",
                      fontSize: 12,
                      padding: "4px 10px",
                      borderRadius: 999,
                      border: "1px solid #d8d3c7",
                      background: "transparent",
                      color: "#6b6559",
                      cursor: "pointer",
                    }}
                  >
                    ← リストに戻る
                  </button>
                )}
              </div>
            )}
          </FormField>

          {/* Purpose */}
          <FormField label="ご用件">
            <input
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="お打ち合わせ など"
              style={inputStyle}
            />
          </FormField>

          <button
            type="submit"
            disabled={submitting}
            style={{
              marginTop: 8,
              padding: "14px",
              borderRadius: 10,
              border: "none",
              background: bc,
              color: "#fff",
              fontSize: 16,
              fontWeight: 600,
              cursor: submitting ? "not-allowed" : "pointer",
              opacity: submitting ? 0.7 : 1,
              fontFamily: "inherit",
            }}
          >
            {submitting ? "送信中..." : "受付する →"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ─── Shared primitives ────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "12px 14px",
  border: "1.5px solid #d8d3c7",
  borderRadius: 8,
  background: "#fffefb",
  fontSize: 15,
  color: "#2d2a24",
  outline: "none",
  fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
  boxSizing: "border-box",
};

function FormField({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#2d2a24" }}>{label}</span>
        {required && (
          <span style={{ fontSize: 10, color: "#a84238", background: "#fdf2f1", padding: "1px 7px", borderRadius: 4, fontWeight: 600 }}>
            必須
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
