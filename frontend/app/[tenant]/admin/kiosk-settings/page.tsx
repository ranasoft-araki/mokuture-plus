"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkSectionTitle } from "@/components/AdminShell";
import { api, TenantSettings } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

type PreviewTab = "top" | "calling" | "complete";

export default function KioskSettingsPage() {
  const params = useParams<{ tenant: string }>();

  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<PreviewTab>("top");

  // Kiosk text state
  const [kioskWelcome, setKioskWelcome] = useState("ようこそ");
  const [kioskSub, setKioskSub] = useState("ご用件をお選びください");
  const [kioskCalling, setKioskCalling] = useState("担当者をお呼びしています。少々お待ちください。");
  const [kioskComplete, setKioskComplete] = useState("担当者がご案内します");
  const [kioskIdleTimeout, setKioskIdleTimeout] = useState("60");
  const [kioskCompleteTimeout, setKioskCompleteTimeout] = useState("10");

  // Staff list state — one name per line in the textarea
  const [staffListText, setStaffListText] = useState("");
  const [staffSaving, setStaffSaving] = useState(false);
  const [staffSaved, setStaffSaved] = useState(false);
  const [staffError, setStaffError] = useState<string | null>(null);

  // Purpose list state — one purpose per line in the textarea
  const [purposeListText, setPurposeListText] = useState("");
  const [purposeSaving, setPurposeSaving] = useState(false);
  const [purposeSaved, setPurposeSaved] = useState(false);
  const [purposeError, setPurposeError] = useState<string | null>(null);

  // Logo placement state
  const [logoPosX, setLogoPosX] = useState(0.04);
  const [logoPosY, setLogoPosY] = useState(0.04);
  const [logoWidthPct, setLogoWidthPct] = useState(8);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token).then((s) => {
      setSettings(s);
      setKioskWelcome(s.kiosk_welcome_message);
      setKioskSub(s.kiosk_sub_message);
      setKioskCalling(s.kiosk_calling_message);
      setKioskComplete(s.kiosk_complete_message);
      setKioskIdleTimeout(String(s.kiosk_idle_timeout_sec));
      setKioskCompleteTimeout(String(s.kiosk_complete_timeout_sec));
      setLogoPosX(s.logo_pos_x);
      setLogoPosY(s.logo_pos_y);
      setLogoWidthPct(s.logo_width_pct);
      setLogoUrl(s.logo_url);
      // Populate staff list textarea: stored as CSV, display as one per line
      if (s.staff_list) {
        setStaffListText(
          s.staff_list.split(",").map((n) => n.trim()).filter(Boolean).join("\n")
        );
      }
      // Populate purpose list textarea: stored as CSV, display as one per line
      if (s.purpose_list) {
        setPurposeListText(
          s.purpose_list.split(",").map((p) => p.trim()).filter(Boolean).join("\n")
        );
      }
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    const token = getAccessToken();
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateTenantSettings(token, {
        kiosk_welcome_message: kioskWelcome,
        kiosk_sub_message: kioskSub,
        kiosk_calling_message: kioskCalling,
        kiosk_complete_message: kioskComplete,
        kiosk_idle_timeout_sec: Number(kioskIdleTimeout) || 60,
        kiosk_complete_timeout_sec: Number(kioskCompleteTimeout) || 10,
        logo_pos_x: logoPosX,
        logo_pos_y: logoPosY,
        logo_width_pct: logoWidthPct,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!settings) return;
    setKioskWelcome(settings.kiosk_welcome_message);
    setKioskSub(settings.kiosk_sub_message);
    setKioskCalling(settings.kiosk_calling_message);
    setKioskComplete(settings.kiosk_complete_message);
    setKioskIdleTimeout(String(settings.kiosk_idle_timeout_sec));
    setKioskCompleteTimeout(String(settings.kiosk_complete_timeout_sec));
    setLogoPosX(settings.logo_pos_x);
    setLogoPosY(settings.logo_pos_y);
    setLogoWidthPct(settings.logo_width_pct);
    if (settings.staff_list) {
      setStaffListText(
        settings.staff_list.split(",").map((n) => n.trim()).filter(Boolean).join("\n")
      );
    } else {
      setStaffListText("");
    }
    if (settings.purpose_list) {
      setPurposeListText(
        settings.purpose_list.split(",").map((p) => p.trim()).filter(Boolean).join("\n")
      );
    } else {
      setPurposeListText("");
    }
    setError(null);
  };

  const handleStaffSave = async () => {
    const token = getAccessToken();
    if (!token) return;
    setStaffSaving(true);
    setStaffError(null);
    try {
      // Convert newline-separated names back to CSV
      const csv = staffListText
        .split("\n")
        .map((n) => n.trim())
        .filter(Boolean)
        .join(",");
      const updated = await api.updateTenantSettings(token, { staff_list: csv || null });
      setSettings(updated);
      setStaffSaved(true);
      setTimeout(() => setStaffSaved(false), 2000);
    } catch (err: unknown) {
      setStaffError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setStaffSaving(false);
    }
  };

  const handlePurposeSave = async () => {
    const token = getAccessToken();
    if (!token) return;
    setPurposeSaving(true);
    setPurposeError(null);
    try {
      // Convert newline-separated purposes back to CSV
      const csv = purposeListText
        .split("\n")
        .map((p) => p.trim())
        .filter(Boolean)
        .join(",");
      const updated = await api.updateTenantSettings(token, { purpose_list: csv || null });
      setSettings(updated);
      setPurposeSaved(true);
      setTimeout(() => setPurposeSaved(false), 2000);
    } catch (err: unknown) {
      setPurposeError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setPurposeSaving(false);
    }
  };

  return (
    <AdminShell
      active="kiosk_settings"
      title="受付設定"
      breadcrumb="ホーム / 設定 / 受付設定"
      subtitle="キオスク受付画面の文言・ロゴ配置を設定します"
      actions={
        <>
          <MkBtn variant="ghost" size="sm" onClick={handleCancel}>変更をキャンセル</MkBtn>
          <MkBtn variant="primary" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : saved ? "保存しました ✓" : "保存"}
          </MkBtn>
        </>
      }
    >
      {error && (
        <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "10px 14px", fontSize: 12.5, color: "#a84238", marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div className="adm-grid-kiosk-settings" style={{ gap: 20 }}>
        {/* Left: Form */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <MkCard>
            <MkSectionTitle title="受付トップ画面の文言" subtitle="最初に表示されるウェルカム画面" />
            <div style={{ display: "grid", gap: 16 }}>
              <Field label="メインメッセージ">
                <TextInput value={kioskWelcome} onChange={setKioskWelcome} placeholder="ようこそ" />
              </Field>
              <Field label="サブメッセージ">
                <TextInput value={kioskSub} onChange={setKioskSub} placeholder="ご用件をお選びください" />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle title="呼び出し・完了画面の文言" subtitle="受付フォーム送信後に表示される画面" />
            <div style={{ display: "grid", gap: 16 }}>
              <Field label="呼び出し中メッセージ">
                <TextInput value={kioskCalling} onChange={setKioskCalling} placeholder="担当者をお呼びしています。少々お待ちください。" />
              </Field>
              <Field label="完了メッセージ">
                <TextInput value={kioskComplete} onChange={setKioskComplete} placeholder="担当者がご案内します" />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle title="タイムアウト" subtitle="無操作時に待機画面へ戻るまでの秒数" />
            <div className="adm-grid-2" style={{ gap: 16 }}>
              <Field label="受付画面のタイムアウト" hint="10〜300 秒">
                <TextInputNumber value={kioskIdleTimeout} onChange={setKioskIdleTimeout} suffix="秒" />
              </Field>
              <Field label="完了画面の表示時間" hint="5〜60 秒">
                <TextInputNumber value={kioskCompleteTimeout} onChange={setKioskCompleteTimeout} suffix="秒" />
              </Field>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle
              title="スタッフリスト"
              subtitle="受付フォームで担当者をドロップダウンから選択できるようにします"
            />
            {staffError && (
              <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "8px 12px", fontSize: 12, color: "#a84238", marginBottom: 10 }}>
                {staffError}
              </div>
            )}
            <Field label="スタッフ名" hint="名前を1行ずつ入力してください。設定すると受付フォームで担当者をドロップダウンから選択できます">
              <textarea
                value={staffListText}
                onChange={(e) => setStaffListText(e.target.value)}
                rows={5}
                placeholder={"山田太郎\n鈴木花子\n田中一郎"}
                style={{
                  width: "100%",
                  border: "1px solid #d8d3c7",
                  borderRadius: 7,
                  background: "#fffefb",
                  padding: "8px 10px",
                  fontSize: 12.5,
                  color: "#2d2a24",
                  resize: "vertical",
                  outline: "none",
                  fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
                  boxSizing: "border-box",
                }}
              />
            </Field>
            <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
              <MkBtn variant="primary" size="sm" onClick={handleStaffSave} disabled={staffSaving}>
                {staffSaving ? "保存中..." : staffSaved ? "保存しました ✓" : "保存"}
              </MkBtn>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle
              title="来訪目的リスト"
              subtitle="受付フォームで訪問目的をドロップダウンから選択できるようにします"
            />
            {purposeError && (
              <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "8px 12px", fontSize: 12, color: "#a84238", marginBottom: 10 }}>
                {purposeError}
              </div>
            )}
            <Field label="来訪目的" hint="空の場合は自由入力になります">
              <textarea
                value={purposeListText}
                onChange={(e) => setPurposeListText(e.target.value)}
                rows={7}
                placeholder={"商談・打合せ\n採用面接\n配送・搬入\n会議・打合せ\n視察・見学\nその他"}
                style={{
                  width: "100%",
                  border: "1px solid #d8d3c7",
                  borderRadius: 7,
                  background: "#fffefb",
                  padding: "8px 10px",
                  fontSize: 12.5,
                  color: "#2d2a24",
                  resize: "vertical",
                  outline: "none",
                  fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
                  boxSizing: "border-box",
                }}
              />
            </Field>
            <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
              <MkBtn variant="primary" size="sm" onClick={handlePurposeSave} disabled={purposeSaving}>
                {purposeSaving ? "保存中..." : purposeSaved ? "保存しました ✓" : "保存"}
              </MkBtn>
            </div>
          </MkCard>

          <MkCard>
            <MkSectionTitle
              title="ロゴ配置"
              subtitle="右のプレビューでドラッグして位置・サイズを調整"
            />
            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ background: "#f4f1ea", borderRadius: 7, padding: "10px 14px", fontSize: 12, color: "#6b6559" }}>
                右のプレビューの「トップ」タブでロゴをドラッグして移動、右下ハンドルをドラッグしてサイズ変更できます。
                {!logoUrl && <span style={{ color: "#a84238", marginLeft: 6 }}>※ 基本設定でロゴをアップロードしてください</span>}
              </div>
              <div className="adm-grid-2" style={{ gap: 12 }}>
                <Field label="X 位置" hint="左端からの比率 (0–0.9)">
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="range" min={0} max={0.9} step={0.01}
                      value={logoPosX}
                      onChange={(e) => setLogoPosX(Number(e.target.value))}
                      style={{ flex: 1 }}
                    />
                    <span style={{ fontSize: 12, color: "#2d2a24", fontFamily: "monospace", width: 40, textAlign: "right" }}>{(logoPosX * 100).toFixed(0)}%</span>
                  </div>
                </Field>
                <Field label="Y 位置" hint="上端からの比率 (0–0.9)">
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="range" min={0} max={0.9} step={0.01}
                      value={logoPosY}
                      onChange={(e) => setLogoPosY(Number(e.target.value))}
                      style={{ flex: 1 }}
                    />
                    <span style={{ fontSize: 12, color: "#2d2a24", fontFamily: "monospace", width: 40, textAlign: "right" }}>{(logoPosY * 100).toFixed(0)}%</span>
                  </div>
                </Field>
                <div style={{ gridColumn: "span 2" }}>
                  <Field label="ロゴサイズ" hint="画面幅に対する % (2–30)">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="range" min={2} max={30} step={0.5}
                        value={logoWidthPct}
                        onChange={(e) => setLogoWidthPct(Number(e.target.value))}
                        style={{ flex: 1 }}
                      />
                      <span style={{ fontSize: 12, color: "#2d2a24", fontFamily: "monospace", width: 40, textAlign: "right" }}>{logoWidthPct.toFixed(1)}%</span>
                    </div>
                  </Field>
                </div>
              </div>
            </div>
          </MkCard>
        </div>

        {/* Right: Preview */}
        <div style={{ position: "sticky", top: 0 }}>
          <MkCard padding="16px">
            <MkSectionTitle title="プレビュー" subtitle="実際のキオスク画面のイメージ" />

            {/* Tab bar */}
            <div style={{ display: "flex", gap: 4, marginBottom: 14 }}>
              {(["top", "calling", "complete"] as PreviewTab[]).map((tab) => {
                const labels: Record<PreviewTab, string> = { top: "トップ", calling: "呼び出し中", complete: "完了" };
                return (
                  <button
                    key={tab}
                    onClick={() => setPreviewTab(tab)}
                    style={{
                      padding: "5px 12px", borderRadius: 6, border: "1px solid",
                      fontSize: 11.5, fontWeight: previewTab === tab ? 600 : 400, cursor: "pointer",
                      background: previewTab === tab ? "#1d1a15" : "#fffefb",
                      color: previewTab === tab ? "#fffefb" : "#6b6559",
                      borderColor: previewTab === tab ? "#1d1a15" : "#efece5",
                    }}
                  >
                    {labels[tab]}
                  </button>
                );
              })}
            </div>

            {/* 16:9 Preview canvas */}
            <KioskPreview
              tab={previewTab}
              kioskWelcome={kioskWelcome}
              kioskSub={kioskSub}
              kioskCalling={kioskCalling}
              kioskComplete={kioskComplete}
              kioskIdleTimeout={kioskIdleTimeout}
              kioskCompleteTimeout={kioskCompleteTimeout}
              logoUrl={logoUrl}
              logoPosX={logoPosX}
              logoPosY={logoPosY}
              logoWidthPct={logoWidthPct}
              onLogoMove={(x, y) => {
                setLogoPosX(Math.max(0, Math.min(0.9, x)));
                setLogoPosY(Math.max(0, Math.min(0.9, y)));
              }}
              onLogoResize={(w) => setLogoWidthPct(Math.max(2, Math.min(30, w)))}
            />
          </MkCard>
        </div>
      </div>
    </AdminShell>
  );
}

// ─── Kiosk Preview Component ──────────────────────────────────────────────────

function KioskPreview({
  tab, kioskWelcome, kioskSub, kioskCalling, kioskComplete,
  kioskIdleTimeout, kioskCompleteTimeout,
  logoUrl, logoPosX, logoPosY, logoWidthPct,
  onLogoMove, onLogoResize,
}: {
  tab: PreviewTab;
  kioskWelcome: string; kioskSub: string;
  kioskCalling: string; kioskComplete: string;
  kioskIdleTimeout: string; kioskCompleteTimeout: string;
  logoUrl: string | null;
  logoPosX: number; logoPosY: number; logoWidthPct: number;
  onLogoMove: (x: number, y: number) => void;
  onLogoResize: (w: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const isResizing = useRef(false);
  const dragStart = useRef({ mouseX: 0, mouseY: 0, posX: 0, posY: 0 });
  const resizeStart = useRef({ mouseX: 0, mouseY: 0, width: 0, containerW: 0 });

  const handleLogoDragStart = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return;
    e.preventDefault();
    isDragging.current = true;
    dragStart.current = { mouseX: e.clientX, mouseY: e.clientY, posX: logoPosX, posY: logoPosY };

    const onMove = (me: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const dx = (me.clientX - dragStart.current.mouseX) / rect.width;
      const dy = (me.clientY - dragStart.current.mouseY) / rect.height;
      onLogoMove(dragStart.current.posX + dx, dragStart.current.posY + dy);
    };
    const onUp = () => {
      isDragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [logoPosX, logoPosY, onLogoMove]);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    isResizing.current = true;
    const rect = containerRef.current.getBoundingClientRect();
    resizeStart.current = { mouseX: e.clientX, mouseY: e.clientY, width: logoWidthPct, containerW: rect.width };

    const onMove = (me: MouseEvent) => {
      if (!isResizing.current) return;
      const dx = (me.clientX - resizeStart.current.mouseX) / resizeStart.current.containerW * 100;
      onLogoResize(resizeStart.current.width + dx);
    };
    const onUp = () => {
      isResizing.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [logoWidthPct, onLogoResize]);

  return (
    <div
      ref={containerRef}
      style={{ aspectRatio: "16/9", background: "#faf8f4", borderRadius: 8, border: "1px solid #efece5", overflow: "hidden", position: "relative", userSelect: "none" }}
    >
      {tab === "top" && (
        <TopPreview
          kioskWelcome={kioskWelcome}
          kioskSub={kioskSub}
          kioskIdleTimeout={kioskIdleTimeout}
          logoUrl={logoUrl}
          logoPosX={logoPosX}
          logoPosY={logoPosY}
          logoWidthPct={logoWidthPct}
          onLogoDragStart={handleLogoDragStart}
          onResizeStart={handleResizeStart}
        />
      )}
      {tab === "calling" && (
        <CallingPreview kioskCalling={kioskCalling} />
      )}
      {tab === "complete" && (
        <CompletePreview kioskComplete={kioskComplete} kioskCompleteTimeout={kioskCompleteTimeout} />
      )}
    </div>
  );
}

// ─── Top Screen Preview ───────────────────────────────────────────────────────

function TopPreview({
  kioskWelcome, kioskSub, kioskIdleTimeout,
  logoUrl, logoPosX, logoPosY, logoWidthPct,
  onLogoDragStart, onResizeStart,
}: {
  kioskWelcome: string; kioskSub: string; kioskIdleTimeout: string;
  logoUrl: string | null; logoPosX: number; logoPosY: number; logoWidthPct: number;
  onLogoDragStart: (e: React.MouseEvent) => void;
  onResizeStart: (e: React.MouseEvent) => void;
}) {
  const tiles = [
    { label: "ご訪問", sub: "お約束の方", primary: true },
    { label: "QR で受付", sub: "招待コードをお持ちの方", primary: false },
    { label: "配送・宅配便", sub: "お荷物のお届け", primary: false },
    { label: "その他", sub: "上記以外のご用件", primary: false },
  ];

  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", padding: "3% 4.2%", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
      {/* Logo draggable overlay */}
      {logoUrl && (
        <div
          onMouseDown={onLogoDragStart}
          style={{
            position: "absolute",
            left: `${logoPosX * 100}%`,
            top: `${logoPosY * 100}%`,
            width: `${logoWidthPct}%`,
            cursor: "grab",
            zIndex: 20,
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={logoUrl} alt="logo" style={{ width: "100%", height: "auto", objectFit: "contain", display: "block", pointerEvents: "none" }} />
          {/* Resize handle */}
          <div
            onMouseDown={onResizeStart}
            style={{
              position: "absolute", bottom: -4, right: -4,
              width: 10, height: 10, background: "#4a7c4e", borderRadius: 2,
              cursor: "se-resize", border: "1.5px solid #fffefb", zIndex: 21,
            }}
          />
        </div>
      )}

      {/* Header */}
      <div style={{ marginBottom: "2%", flexShrink: 0 }}>
        <div style={{ fontSize: "1.2%", color: "#a8a198", letterSpacing: "0.3em", textTransform: "uppercase", marginBottom: "0.5%", fontFamily: "Inter, system-ui, sans-serif" }}>RECEPTION</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: "2%" }}>
          <div style={{ fontSize: "5.5%", fontWeight: 600, color: "#1d1a15", letterSpacing: "-0.02em", lineHeight: 1.1 }}>{kioskWelcome || "ようこそ"}</div>
          <div style={{ fontSize: "1.6%", color: "#6b6559" }}>{kioskSub || "ご用件をお選びください"}</div>
        </div>
      </div>

      {/* Tiles */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1.2%", flex: 1, minHeight: 0 }}>
        {tiles.map((t, i) => (
          <div
            key={i}
            style={{
              background: t.primary ? "#1d1a15" : "#fffefb",
              border: `1px solid ${t.primary ? "#1d1a15" : "#efece5"}`,
              borderRadius: "4%",
              padding: "4% 5%",
              display: "flex", flexDirection: "column", justifyContent: "space-between",
            }}
          >
            <div style={{ width: "28%", aspectRatio: "1", borderRadius: "25%", background: t.primary ? "rgba(255,255,255,0.1)" : "#eaf0e8" }} />
            <div>
              <div style={{ fontSize: "2.5%", fontWeight: 600, color: t.primary ? "#ffffff" : "#1d1a15", lineHeight: 1.2 }}>{t.label}</div>
              <div style={{ fontSize: "1.3%", color: t.primary ? "rgba(255,255,255,0.6)" : "#6b6559", marginTop: "3%" }}>{t.sub}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div style={{ marginTop: "1.5%", display: "flex", justifyContent: "flex-end", fontSize: "1.1%", color: "#a8a198", flexShrink: 0 }}>
        {kioskIdleTimeout || "60"}秒で待機画面に戻ります
      </div>
    </div>
  );
}

// ─── Calling Screen Preview ───────────────────────────────────────────────────

function CallingPreview({ kioskCalling }: { kioskCalling: string }) {
  return (
    <div style={{ position: "absolute", inset: 0, background: "#faf8f4", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "3%", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
      <div style={{
        width: "12%", aspectRatio: "1", borderRadius: "50%", background: "#eaf0e8",
        display: "flex", alignItems: "center", justifyContent: "center",
        animation: "kiosk-pulse 1.8s ease-in-out infinite",
      }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ width: "50%", height: "50%" }}>
          <path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" /><path d="M10 19a2 2 0 0 0 4 0" />
        </svg>
      </div>
      <div style={{ textAlign: "center", maxWidth: "60%" }}>
        <div style={{ fontSize: "2%", fontWeight: 600, color: "#1d1a15", lineHeight: 1.4 }}>{kioskCalling || "担当者をお呼びしています"}</div>
      </div>
      <style>{`@keyframes kiosk-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.08)} }`}</style>
    </div>
  );
}

// ─── Complete Screen Preview ──────────────────────────────────────────────────

function CompletePreview({ kioskComplete, kioskCompleteTimeout }: { kioskComplete: string; kioskCompleteTimeout: string }) {
  return (
    <div style={{ position: "absolute", inset: 0, background: "#1d1a15", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "2.5%", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
      <div style={{ width: "10%", aspectRatio: "1", borderRadius: "50%", background: "rgba(74,124,78,0.3)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ width: "50%", height: "50%" }}>
          <path d="M5 12l5 5L20 6" />
        </svg>
      </div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "2.5%", fontWeight: 600, color: "#fffefb", letterSpacing: "-0.01em" }}>山田 太郎 様</div>
        <div style={{ fontSize: "1.4%", color: "rgba(255,255,255,0.5)", marginTop: "1%" }}>{kioskComplete || "担当者がご案内します"}</div>
      </div>
      <div style={{ fontSize: "1.2%", color: "rgba(255,255,255,0.35)" }}>{kioskCompleteTimeout || "10"}秒後に待機画面へ</div>
    </div>
  );
}

// ─── Shared primitives ────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: "#2d2a24", marginBottom: 6 }}>{label}</div>
      {children}
      {hint && <div style={{ fontSize: 11, color: "#a8a198", marginTop: 5 }}>{hint}</div>}
    </label>
  );
}

function TextInput({ value, placeholder, onChange }: { value: string; placeholder?: string; onChange: (v: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34 }}>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }}
      />
    </div>
  );
}

function TextInputNumber({ value, onChange, suffix }: { value: string; onChange: (v: string) => void; suffix?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34, gap: 4 }}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type="number"
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: "monospace", height: "100%" }}
      />
      {suffix && <span style={{ color: "#a8a198", fontSize: 12 }}>{suffix}</span>}
    </div>
  );
}
