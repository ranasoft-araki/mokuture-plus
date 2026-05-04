"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
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

  const ease = [0.25, 0.46, 0.45, 0.94] as const;

  return (
    <AnimatePresence mode="wait">
      {suspended ? (
        <motion.div
          key="suspended"
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 1.02 }}
          transition={{ duration: 1.1, ease }}
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
        </motion.div>
      ) : screen === "loading" || !settings ? (
        <motion.div
          key="loading"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.7 }}
          style={{ width: "100vw", height: "100vh", background: "#0a0806", display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div style={{ color: "rgba(255,255,255,0.4)", fontFamily: "Inter, system-ui, sans-serif", fontSize: 16 }}>
            読み込み中…
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="ready"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1.2, ease }}
        >
          <ReceptionForm settings={settings} kioskToken={kioskToken} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ─── Animation variants ───────────────────────────────────────────────────────

const ease = [0.25, 0.46, 0.45, 0.94] as const;

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.24, delayChildren: 0.3 } },
};

const fieldVariants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0, transition: { duration: 1.0, ease } },
};

const shakeVariants = {
  hidden: { opacity: 0, x: 0 },
  visible: {
    opacity: 1,
    x: [0, -8, 8, -6, 6, -3, 3, 0],
    transition: {
      opacity: { duration: 0.4 },
      x: { duration: 1.2 },
    },
  },
};

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

  return (
    <AnimatePresence mode="wait">
      {submitted ? (
        <motion.div
          key="complete"
          initial={{ opacity: 0, scale: 0.98, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1.3, ease }}
        >
          <SuccessScreen visitorName={visitorName} settings={settings} />
        </motion.div>
      ) : (
        <motion.div
          key="form"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 0.96, filter: "blur(4px)" }}
          transition={{ duration: 0.8 }}
          style={{
            width: "100vw",
            minHeight: "100vh",
            background: "#faf8f4",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "40px 24px",
            fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
          }}
        >
          <div style={{ width: "100%", maxWidth: 560 }}>
            <motion.h1
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 1.0, ease }}
              style={{ fontSize: 28, fontWeight: 700, color: "#1d1a15", marginBottom: 32, letterSpacing: "-0.02em" }}
            >
              ご来訪情報をご記入ください
            </motion.h1>

            <AnimatePresence>
              {error && (
                <motion.div
                  key={error}
                  variants={shakeVariants}
                  initial="hidden"
                  animate="visible"
                  exit={{ opacity: 0, transition: { duration: 0.5 } }}
                  style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#a84238", marginBottom: 16 }}
                >
                  {error}
                </motion.div>
              )}
            </AnimatePresence>

            <motion.form
              onSubmit={handleSubmit}
              variants={containerVariants}
              initial="hidden"
              animate="visible"
              style={{ display: "flex", flexDirection: "column", gap: 18 }}
            >
              {/* Visitor name */}
              <motion.div variants={fieldVariants}>
                <FormField label="お名前" required>
                  <input
                    value={visitorName}
                    onChange={(e) => setVisitorName(e.target.value)}
                    placeholder="山田 太郎"
                    style={inputStyle}
                  />
                </FormField>
              </motion.div>

              {/* Company */}
              <motion.div variants={fieldVariants}>
                <FormField label="会社名">
                  <input
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="株式会社 〇〇"
                    style={inputStyle}
                  />
                </FormField>
              </motion.div>

              {/* Staff */}
              <motion.div variants={fieldVariants}>
                <FormField label="ご担当者名">
                  {useDropdown && staffMode === "dropdown" ? (
                    <div>
                      <motion.div
                        style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: staff ? 8 : 0 }}
                        variants={containerVariants}
                        initial="hidden"
                        animate="visible"
                      >
                        {staffList.map((name) => (
                          <motion.button
                            key={name}
                            type="button"
                            onClick={() => setStaff(name)}
                            variants={fieldVariants}
                            whileHover={{ scale: 1.04 }}
                            whileTap={{ scale: 0.96 }}
                            transition={{ type: "spring", stiffness: 500, damping: 30 }}
                            style={{
                              padding: "8px 16px",
                              borderRadius: 999,
                              border: `2px solid ${staff === name ? bc : "#d8d3c7"}`,
                              background: staff === name ? bc : "transparent",
                              color: staff === name ? "#fff" : "#2d2a24",
                              fontSize: 14,
                              cursor: "pointer",
                            }}
                          >
                            {name}
                          </motion.button>
                        ))}
                        <motion.button
                          type="button"
                          onClick={() => { setStaff(""); setStaffMode("freetext"); }}
                          variants={fieldVariants}
                          whileTap={{ scale: 0.96 }}
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
                        </motion.button>
                      </motion.div>
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
              </motion.div>

              {/* Purpose */}
              <motion.div variants={fieldVariants}>
                <FormField label="ご用件">
                  <input
                    value={purpose}
                    onChange={(e) => setPurpose(e.target.value)}
                    placeholder="お打ち合わせ など"
                    style={inputStyle}
                  />
                </FormField>
              </motion.div>

              <motion.div variants={fieldVariants}>
                <motion.button
                  type="submit"
                  disabled={submitting}
                  whileTap={submitting ? {} : { scale: 0.97 }}
                  transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  style={{
                    width: "100%",
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
                </motion.button>
              </motion.div>
            </motion.form>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ─── Success Screen ───────────────────────────────────────────────────────────

function SuccessScreen({ visitorName, settings }: { visitorName: string; settings: PublicTenantSettings }) {
  const bc = settings.brand_color;
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.9 }}
      style={{
        width: "100vw",
        height: "100vh",
        background: "#1d1a15",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
      }}
    >
      {/* Circle + checkmark */}
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.55, delay: 0.2, ease: [0.34, 1.56, 0.64, 1] }}
        style={{
          width: 80,
          height: 80,
          borderRadius: "50%",
          background: `${bc}33`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke={bc} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ width: 40, height: 40 }}>
          <motion.path
            d="M5 12l5 5L20 6"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.6, ease: "easeOut" }}
          />
        </svg>
      </motion.div>

      {/* Name + message */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.95, ease }}
        style={{ textAlign: "center" }}
      >
        <div style={{ fontSize: 28, fontWeight: 600, color: "#fffefb" }}>{visitorName} 様</div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 1.25 }}
          style={{ fontSize: 16, color: "rgba(255,255,255,0.5)", marginTop: 8 }}
        >
          {settings.kiosk_complete_message}
        </motion.div>
      </motion.div>
    </motion.div>
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
