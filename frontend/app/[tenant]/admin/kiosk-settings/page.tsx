"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminShell, MkBtn, MkCard, MkSectionTitle } from "@/components/AdminShell";
import { api, TenantSettings } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

// 実キオスク(kiosk_agent/static/kiosk.html)の画面フローに対応したプレビュー。
// 文言はプレビュー上を直接クリックして編集(Canva風)。
type PreviewTab = "idle" | "welcome" | "menu" | "calling" | "complete";

const TABS: { id: PreviewTab; label: string }[] = [
  { id: "idle",     label: "待機" },
  { id: "welcome",  label: "ようこそ" },
  { id: "menu",     label: "受付メニュー" },
  { id: "calling",  label: "呼び出し中" },
  { id: "complete", label: "完了" },
];

// 実キオスクのデザイントークン(kiosk.html の T と一致)
const T = {
  bg: "#faf8f4", canvas: "#fffefb", panel: "#f4f1ea",
  border: "#e7e2d8", borderStrong: "#d8d3c7",
  ink: "#1d1a15", sub: "#6b6559", muted: "#a8a198",
  dark: "#1d1a15", idleBg: "#14110d",
  urgent: "#a84238", urgentBg: "#f6e0dc",
};
const FONT = "'Noto Sans JP', Inter, system-ui, sans-serif";

export default function KioskSettingsPage() {
  const params = useParams<{ tenant: string }>();

  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<PreviewTab>("idle");

  // ── キオスク文言(プレビュー上でインライン編集) ──
  const [kioskWelcome, setKioskWelcome] = useState("ようこそ");
  const [kioskSub, setKioskSub] = useState("ご用件をお選びください");
  const [kioskMenuTitle, setKioskMenuTitle] = useState("ご用件をお選びください");
  const [kioskQrGuide, setKioskQrGuide] = useState("ご予約QRをお持ちの方はカメラへかざしてください");
  const [kioskFormLabel, setKioskFormLabel] = useState("QRをお持ちでない方はこちら");
  const [kioskCalling, setKioskCalling] = useState("担当者をお呼びしています。少々お待ちください。");
  const [kioskComplete, setKioskComplete] = useState("お待ちしておりました");

  // ── 数値・その他設定 ──
  const [kioskIdleTimeout, setKioskIdleTimeout] = useState("60");
  const [kioskCompleteTimeout, setKioskCompleteTimeout] = useState("10");
  const [kioskPhone, setKioskPhone] = useState("");
  const [inquiryFormUrl, setInquiryFormUrl] = useState("");
  const [staffListText, setStaffListText] = useState("");
  const [purposeListText, setPurposeListText] = useState("");

  // ── ロゴ ──
  const [brandColor, setBrandColor] = useState("#4a7c4e");
  const [logoPosX, setLogoPosX] = useState(0.04);
  const [logoPosY, setLogoPosY] = useState(0.04);
  const [logoWidthPct, setLogoWidthPct] = useState(8);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    api.getTenantSettings(token).then((s) => {
      applyFromSettings(s);
      setSettings(s);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFromSettings(s: TenantSettings) {
    setKioskWelcome(s.kiosk_welcome_message);
    setKioskSub(s.kiosk_sub_message);
    setKioskMenuTitle(s.kiosk_menu_title || "ご用件をお選びください");
    setKioskQrGuide(s.kiosk_welcome_qr_guide || "ご予約QRをお持ちの方はカメラへかざしてください");
    setKioskFormLabel(s.kiosk_welcome_form_label || "QRをお持ちでない方はこちら");
    setKioskCalling(s.kiosk_calling_message);
    setKioskComplete(s.kiosk_complete_message || "お待ちしておりました");
    setKioskIdleTimeout(String(s.kiosk_idle_timeout_sec));
    setKioskCompleteTimeout(String(s.kiosk_complete_timeout_sec));
    setKioskPhone(s.kiosk_phone_number ?? "");
    setInquiryFormUrl(s.inquiry_form_url ?? "");
    setBrandColor(s.brand_color || "#4a7c4e");
    setLogoPosX(s.logo_pos_x);
    setLogoPosY(s.logo_pos_y);
    setLogoWidthPct(s.logo_width_pct);
    setLogoUrl(s.logo_url);
    setStaffListText(
      s.staff_list ? s.staff_list.split(",").map((n) => n.trim()).filter(Boolean).join("\n") : ""
    );
    setPurposeListText(
      s.purpose_list ? s.purpose_list.split(",").map((p) => p.trim()).filter(Boolean).join("\n") : ""
    );
  }

  const handleSave = async () => {
    const token = getAccessToken();
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const staffCsv = staffListText.split("\n").map((n) => n.trim()).filter(Boolean).join(",");
      const purposeCsv = purposeListText.split("\n").map((p) => p.trim()).filter(Boolean).join(",");
      const updated = await api.updateTenantSettings(token, {
        kiosk_welcome_message: kioskWelcome,
        kiosk_sub_message: kioskSub,
        kiosk_menu_title: kioskMenuTitle,
        kiosk_welcome_qr_guide: kioskQrGuide,
        kiosk_welcome_form_label: kioskFormLabel,
        kiosk_calling_message: kioskCalling,
        kiosk_complete_message: kioskComplete,
        kiosk_idle_timeout_sec: Number(kioskIdleTimeout) || 60,
        kiosk_complete_timeout_sec: Number(kioskCompleteTimeout) || 10,
        kiosk_phone_number: kioskPhone.trim() || null,
        inquiry_form_url: inquiryFormUrl.trim() || null,
        logo_pos_x: logoPosX,
        logo_pos_y: logoPosY,
        logo_width_pct: logoWidthPct,
        staff_list: staffCsv || null,
        purpose_list: purposeCsv || null,
      });
      setSettings(updated);
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
    applyFromSettings(settings);
    setError(null);
  };

  return (
    <AdminShell
      active="kiosk_settings"
      title="受付設定"
      breadcrumb="ホーム / 設定 / 受付設定"
      subtitle="キオスク受付画面をそのままプレビューしながら文言・ロゴを編集します"
      actions={
        <>
          <MkBtn variant="ghost" size="sm" onClick={handleCancel}>変更をキャンセル</MkBtn>
          <MkBtn variant="primary" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : saved ? "保存しました ✓" : "保存"}
          </MkBtn>
        </>
      }
    >
      <style>{`
        .mk-edit { cursor: text; outline: none; border-radius: 4px; transition: background .12s, box-shadow .12s; }
        .mk-edit:empty::before { content: attr(data-ph); color: rgba(120,120,120,.5); }
        .mk-edit:hover { box-shadow: 0 0 0 2px rgba(74,124,78,.45); background: rgba(74,124,78,.05); }
        .mk-edit:focus { box-shadow: 0 0 0 2px #4a7c4e; background: rgba(74,124,78,.08); }
        @keyframes mkpv-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.06)} }
      `}</style>

      {error && (
        <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 7, padding: "10px 14px", fontSize: 12.5, color: "#a84238", marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* ── WYSIWYG プレビュー ── */}
      <MkCard padding="16px" style={{ marginBottom: 20 }}>
        <MkSectionTitle
          title="ライブプレビュー"
          subtitle="実際のキオスク画面です。青くハイライトされる文字をクリックすると直接編集できます"
        />

        {/* Tab bar */}
        <div style={{ display: "flex", gap: 4, marginBottom: 14, flexWrap: "wrap" }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setPreviewTab(t.id)}
              style={{
                padding: "6px 14px", borderRadius: 7, border: "1px solid",
                fontSize: 12, fontWeight: previewTab === t.id ? 600 : 400, cursor: "pointer",
                background: previewTab === t.id ? "#1d1a15" : "#fffefb",
                color: previewTab === t.id ? "#fffefb" : "#6b6559",
                borderColor: previewTab === t.id ? "#1d1a15" : "#efece5",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <ScaledCanvas>
          {previewTab === "idle" && (
            <IdleScreen
              bc={brandColor} logoUrl={logoUrl}
              welcome={kioskWelcome} onWelcome={setKioskWelcome}
              sub={kioskSub} onSub={setKioskSub}
            />
          )}
          {previewTab === "welcome" && (
            <WelcomeScreen
              bc={brandColor} welcome={kioskWelcome} onWelcome={setKioskWelcome}
              qrGuide={kioskQrGuide} onQrGuide={setKioskQrGuide}
              formLabel={kioskFormLabel} onFormLabel={setKioskFormLabel}
              idleTimeout={kioskIdleTimeout}
            />
          )}
          {previewTab === "menu" && (
            <MenuScreen
              bc={brandColor} logoUrl={logoUrl}
              menuTitle={kioskMenuTitle} onMenuTitle={setKioskMenuTitle}
              idleTimeout={kioskIdleTimeout}
              logoPosX={logoPosX} logoPosY={logoPosY} logoWidthPct={logoWidthPct}
              onLogoMove={(x, y) => { setLogoPosX(clamp(x, 0, 0.9)); setLogoPosY(clamp(y, 0, 0.9)); }}
              onLogoResize={(w) => setLogoWidthPct(clamp(w, 2, 30))}
            />
          )}
          {previewTab === "calling" && (
            <CallingScreen bc={brandColor} calling={kioskCalling} onCalling={setKioskCalling} />
          )}
          {previewTab === "complete" && (
            <CompleteScreen
              bc={brandColor} complete={kioskComplete} onComplete={setKioskComplete}
              completeTimeout={kioskCompleteTimeout}
            />
          )}
        </ScaledCanvas>

        {previewTab === "menu" && (
          <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <div style={{ fontSize: 12, color: "#6b6559", background: "#f4f1ea", borderRadius: 7, padding: "8px 12px" }}>
              {logoUrl
                ? "ロゴをドラッグして位置を、右下ハンドルでサイズを調整できます。"
                : "※ ロゴは「基本設定」でアップロードすると、ここで位置・サイズを調整できます。"}
            </div>
            {logoUrl && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 220, flex: 1 }}>
                <span style={{ fontSize: 11.5, color: "#2d2a24", fontWeight: 600 }}>ロゴサイズ</span>
                <input
                  type="range" min={2} max={30} step={0.5} value={logoWidthPct}
                  onChange={(e) => setLogoWidthPct(Number(e.target.value))}
                  style={{ flex: 1 }}
                />
                <span style={{ fontSize: 12, color: "#2d2a24", fontFamily: "monospace", width: 44, textAlign: "right" }}>{logoWidthPct.toFixed(1)}%</span>
              </div>
            )}
          </div>
        )}
      </MkCard>

      {/* ── 補助設定(数値・リスト) ── */}
      <div className="adm-grid-2" style={{ gap: 20 }}>
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
          <MkSectionTitle title="受付応答（電話・お断り）" subtitle="スタッフが「電話」「お断り」で応答したときにキオスクへ表示する内容" />
          <div style={{ display: "grid", gap: 16 }}>
            <Field label="受付電話番号" hint="スタッフが「電話（対応不可）」で応答したとき、来訪者にこの番号を表示します">
              <TextInput value={kioskPhone} onChange={setKioskPhone} placeholder="03-1234-5678" />
            </Field>
            <Field label="問い合わせフォームURL（任意）" hint="スタッフが「お断り」で応答したとき、このURLのQRを表示します。空欄の場合は mokuture 共通フォームを表示します">
              <TextInput value={inquiryFormUrl} onChange={setInquiryFormUrl} placeholder="https://example.com/contact" />
            </Field>
          </div>
        </MkCard>

        <MkCard>
          <MkSectionTitle title="スタッフリスト" subtitle="受付フォームで担当者をドロップダウンから選択できるようにします" />
          <Field label="スタッフ名" hint="名前を1行ずつ入力してください">
            <Textarea value={staffListText} onChange={setStaffListText} rows={5} placeholder={"山田太郎\n鈴木花子\n田中一郎"} />
          </Field>
        </MkCard>

        <MkCard>
          <MkSectionTitle title="来訪目的リスト" subtitle="受付フォームで訪問目的を選択肢にします" />
          <Field label="来訪目的" hint="1行ずつ入力。空の場合は既定の選択肢になります">
            <Textarea value={purposeListText} onChange={setPurposeListText} rows={6} placeholder={"ご予約のあるお客様\nお打ち合わせ\n納品\n採用面接\nその他"} />
          </Field>
        </MkCard>
      </div>
    </AdminShell>
  );
}

// ─── Scaled 1920×1080 canvas ──────────────────────────────────────────────────

function ScaledCanvas({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.3);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / 1920);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      style={{ width: "100%", position: "relative", overflow: "hidden", borderRadius: 12, border: "1px solid #efece5", height: 1080 * scale, background: "#000", userSelect: "none" }}
    >
      <div style={{ width: 1920, height: 1080, transform: `scale(${scale})`, transformOrigin: "top left", position: "absolute", top: 0, left: 0 }}>
        {children}
      </div>
    </div>
  );
}

// ─── Editable text (Canva-like inline edit) ───────────────────────────────────

function Editable({
  value, onChange, placeholder, style,
}: {
  value: string; onChange: (v: string) => void; placeholder?: string; style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el && el.innerText !== (value ?? "")) el.innerText = value ?? "";
  }, [value]);
  return (
    <span
      ref={ref}
      className="mk-edit"
      contentEditable
      suppressContentEditableWarning
      data-ph={placeholder || "クリックして入力"}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); (e.currentTarget as HTMLSpanElement).blur(); }
      }}
      onBlur={(e) => {
        const t = (e.currentTarget as HTMLSpanElement).innerText.replace(/\s*\n\s*/g, " ").trim();
        onChange(t);
      }}
      style={{ display: "inline-block", ...style }}
    />
  );
}

// ─── Screen previews (faithful to kiosk.html) ─────────────────────────────────

function IdleScreen({ bc, logoUrl, welcome, onWelcome, sub, onSub }: {
  bc: string; logoUrl: string | null;
  welcome: string; onWelcome: (v: string) => void; sub: string; onSub: (v: string) => void;
}) {
  return (
    <div style={{ width: 1920, height: 1080, position: "relative", overflow: "hidden", background: T.idleBg, fontFamily: FONT }}>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 38, textAlign: "center", padding: "0 140px" }}>
        {logoUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={logoUrl} alt="logo" style={{ maxWidth: 820, maxHeight: 320, objectFit: "contain" }} />
        ) : (
          <Editable value={welcome} onChange={onWelcome} placeholder="屋号・メインメッセージ"
            style={{ fontSize: 120, fontWeight: 600, color: "#f5efe3", letterSpacing: "-3px", lineHeight: 1.04 }} />
        )}
        <div style={{ width: 84, height: 2, background: bc, opacity: 0.9 }} />
        <Editable value={sub} onChange={onSub} placeholder="タグライン"
          style={{ fontSize: 34, color: "rgba(245,239,227,.7)", letterSpacing: "3px", fontWeight: 300 }} />
      </div>
      {logoUrl && (
        <div style={{ position: "absolute", left: 40, bottom: 34, fontSize: 20, color: "rgba(245,239,227,.4)" }}>
          ※ ロゴ設定時、待機画面はロゴを中央表示します（メインメッセージは非表示）
        </div>
      )}
    </div>
  );
}

function WelcomeScreen({ bc, welcome, onWelcome, qrGuide, onQrGuide, formLabel, onFormLabel, idleTimeout }: {
  bc: string; welcome: string; onWelcome: (v: string) => void;
  qrGuide: string; onQrGuide: (v: string) => void; formLabel: string; onFormLabel: (v: string) => void;
  idleTimeout: string;
}) {
  const corners = [[0, 0, 0], [0, 1, 90], [1, 1, 180], [1, 0, 270]] as const;
  return (
    <div style={{ width: 1920, height: 1080, background: T.bg, display: "flex", flexDirection: "column", fontFamily: FONT }}>
      <div style={{ padding: "28px 80px 4px", flexShrink: 0, display: "flex", alignItems: "center", gap: 40 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 14, padding: "24px 52px", background: T.canvas, border: `2px solid ${T.borderStrong}`, borderRadius: 999, fontSize: 32, fontWeight: 600, color: T.sub }}>← 戻る</div>
        <div>
          <div style={{ fontSize: 16, color: T.muted, letterSpacing: "4px", textTransform: "uppercase", fontFamily: "Inter, system-ui, sans-serif" }}>WELCOME</div>
          <Editable value={welcome} onChange={onWelcome} placeholder="ようこそ"
            style={{ fontSize: 56, fontWeight: 600, color: T.ink, letterSpacing: "-2px", lineHeight: 1.05 }} />
        </div>
      </div>
      <div style={{ flex: 1, padding: "12px 80px 0", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 56, alignItems: "center", minHeight: 0 }}>
        {/* Camera box */}
        <div style={{ background: T.dark, borderRadius: 28, position: "relative", overflow: "hidden", width: "100%", height: 640 }}>
          <div style={{ position: "absolute", inset: 64, border: "3px dashed rgba(255,255,255,.2)", borderRadius: 22 }}>
            {corners.map(([tb, lr, rot], i) => (
              <div key={i} style={{ position: "absolute", [tb ? "bottom" : "top"]: -3, [lr ? "right" : "left"]: -3, width: 60, height: 60, transform: `rotate(${rot}deg)`, borderTop: `5px solid ${bc}`, borderLeft: `5px solid ${bc}`, borderRadius: "14px 0 0 0" } as React.CSSProperties} />
            ))}
          </div>
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, padding: "34px 40px 60px", background: "linear-gradient(180deg,rgba(0,0,0,.66),transparent)", textAlign: "center" }}>
            <Editable value={qrGuide} onChange={onQrGuide} placeholder="QR案内文"
              style={{ fontSize: 40, fontWeight: 700, color: "#fff", lineHeight: 1.35 }} />
            <div style={{ fontSize: 19, color: "rgba(255,255,255,.78)", marginTop: 10, fontFamily: "Inter, system-ui, sans-serif" }}>Hold your reservation QR code over the camera</div>
          </div>
          <div style={{ position: "absolute", bottom: 24, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(0,0,0,.5)", color: "#fff", padding: "10px 22px", borderRadius: 999, fontSize: 17 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: bc }} />読み取り中…
            </span>
          </div>
        </div>
        {/* Form button */}
        <div style={{ display: "flex", flexDirection: "column", height: 640 }}>
          <div style={{ flex: 1, width: "100%", background: T.dark, borderRadius: 28, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 30, textAlign: "center", padding: "40px 24px" }}>
            <div style={{ width: 150, height: 150, borderRadius: 36, background: "rgba(255,255,255,.12)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Ico.Reception size={64} />
            </div>
            <div>
              <Editable value={formLabel} onChange={onFormLabel} placeholder="ボタン見出し"
                style={{ fontSize: 56, fontWeight: 700, color: "#fff", lineHeight: 1.15, whiteSpace: "nowrap" }} />
              <div style={{ fontSize: 27, color: "rgba(255,255,255,.74)", marginTop: 18, lineHeight: 1.6 }}>ご予約の無い方・お荷物の配達、<br />ロッカーのご利用</div>
            </div>
          </div>
        </div>
      </div>
      <Footer bc={bc} idleTimeout={idleTimeout} />
    </div>
  );
}

function MenuScreen({ bc, logoUrl, menuTitle, onMenuTitle, idleTimeout, logoPosX, logoPosY, logoWidthPct, onLogoMove, onLogoResize }: {
  bc: string; logoUrl: string | null; menuTitle: string; onMenuTitle: (v: string) => void; idleTimeout: string;
  logoPosX: number; logoPosY: number; logoWidthPct: number;
  onLogoMove: (x: number, y: number) => void; onLogoResize: (w: number) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const drag = useRef({ mx: 0, my: 0, px: 0, py: 0 });
  const resz = useRef({ mx: 0, w: 0 });

  const onLogoDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    drag.current = { mx: e.clientX, my: e.clientY, px: logoPosX, py: logoPosY };
    const move = (me: MouseEvent) => {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect) return;
      onLogoMove(drag.current.px + (me.clientX - drag.current.mx) / rect.width, drag.current.py + (me.clientY - drag.current.my) / rect.height);
    };
    const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }, [logoPosX, logoPosY, onLogoMove]);

  const onResizeDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    resz.current = { mx: e.clientX, w: logoWidthPct };
    const move = (me: MouseEvent) => {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect) return;
      onLogoResize(resz.current.w + (me.clientX - resz.current.mx) / rect.width * 100);
    };
    const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }, [logoWidthPct, onLogoResize]);

  const TILES = [
    { icon: <Ico.Reception size={72} />, label: "ご訪問", en: "Visit", desc: "ご来訪の受付", primary: true },
    { icon: <Ico.Truck size={72} />, label: "荷物の配達", en: "Delivery", desc: "宅配・配送のお届け", primary: false },
    { icon: <Ico.Locker size={72} />, label: "ロッカー", en: "Locker", desc: "お預け・お受け取り", primary: false },
  ];

  return (
    <div ref={rootRef} style={{ width: 1920, height: 1080, background: T.bg, display: "flex", flexDirection: "column", fontFamily: FONT, position: "relative" }}>
      {logoUrl && (
        <div onMouseDown={onLogoDown}
          style={{ position: "absolute", left: `${logoPosX * 100}%`, top: `${logoPosY * 100}%`, width: `${logoWidthPct}%`, cursor: "grab", zIndex: 5 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={logoUrl} alt="logo" style={{ width: "100%", height: "auto", objectFit: "contain", display: "block", pointerEvents: "none" }} />
          <div onMouseDown={onResizeDown}
            style={{ position: "absolute", bottom: -8, right: -8, width: 26, height: 26, background: bc, borderRadius: 5, cursor: "se-resize", border: "3px solid #fff" }} />
        </div>
      )}
      <div style={{ padding: "48px 80px 0", flexShrink: 0, display: "flex", alignItems: "flex-end", gap: 32 }}>
        <div>
          <Editable value={menuTitle} onChange={onMenuTitle} placeholder="ご用件をお選びください"
            style={{ fontSize: 58, fontWeight: 600, color: T.ink, letterSpacing: "-1.5px", lineHeight: 1.1 }} />
          <div style={{ fontSize: 38, color: T.muted, fontFamily: "Inter, system-ui, sans-serif", letterSpacing: "1px", marginTop: 8 }}>Please select</div>
        </div>
      </div>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 28, padding: "44px 80px", minHeight: 0 }}>
        {TILES.map((t, i) => (
          <div key={i} style={{ background: t.primary ? T.dark : T.canvas, color: t.primary ? "#fff" : T.ink, border: `2px solid ${t.primary ? T.dark : T.border}`, borderRadius: 28, padding: "56px 44px", display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "space-between", position: "relative", overflow: "hidden" }}>
            <div style={{ width: 150, height: 150, borderRadius: 32, background: t.primary ? "rgba(255,255,255,.1)" : bc + "1a", color: t.primary ? "#fff" : bc, display: "flex", alignItems: "center", justifyContent: "center" }}>{t.icon}</div>
            <div>
              <div style={{ fontSize: 58, fontWeight: 600, letterSpacing: "-1px", lineHeight: 1.1 }}>{t.label}</div>
              <div style={{ fontSize: 36, fontWeight: 500, opacity: 0.55, letterSpacing: "1.5px", fontFamily: "Inter, system-ui, sans-serif", marginTop: 4 }}>{t.en}</div>
              <div style={{ fontSize: 25, marginTop: 18, color: t.primary ? "rgba(255,255,255,.7)" : T.sub }}>{t.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <Footer bc={T.sub} idleTimeout={idleTimeout} />
    </div>
  );
}

function CallingScreen({ bc, calling, onCalling }: { bc: string; calling: string; onCalling: (v: string) => void }) {
  return (
    <div style={{ width: 1920, height: 1080, background: T.bg, display: "flex", flexDirection: "column", fontFamily: FONT }}>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "auto 1fr", gap: 90, padding: "0 110px", alignItems: "center", minHeight: 0 }}>
        <div style={{ position: "relative", width: 380, height: 380, flexShrink: 0 }}>
          {[1, 0.7, 0.4].map((s, i) => (
            <div key={i} style={{ position: "absolute", inset: `${(1 - s) * 40}%`, border: `2px solid ${bc}`, borderRadius: "50%", opacity: 0.15 + i * 0.18 }} />
          ))}
          <div style={{ position: "absolute", inset: "32%", background: bc, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}>
            <Ico.Bell size={90} />
          </div>
        </div>
        <div>
          <div style={{ fontSize: 20, color: T.muted, letterSpacing: "4px", textTransform: "uppercase", marginBottom: 18, fontFamily: "Inter, system-ui, sans-serif" }}>PLEASE WAIT</div>
          <div style={{ fontSize: 92, fontWeight: 600, color: T.ink, letterSpacing: "-3px", lineHeight: 1.04, marginBottom: 24 }}>お待ちください</div>
          <div style={{ fontSize: 34, color: T.sub, marginBottom: 10 }}>山田 太郎 様</div>
          <Editable value={calling} onChange={onCalling} placeholder="呼び出し中メッセージ"
            style={{ fontSize: 24, color: T.sub, lineHeight: 1.7, marginBottom: 30, maxWidth: 900 }} />
        </div>
      </div>
      <div style={{ padding: "0 110px 36px", flexShrink: 0 }}>
        <div style={{ background: T.canvas, border: `1px solid ${T.border}`, borderRadius: 18, padding: 24, display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ width: 52, height: 52, borderRadius: 13, background: bc + "1a", color: bc, display: "flex", alignItems: "center", justifyContent: "center" }}><Ico.Check size={26} /></div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 600, color: T.ink }}>通知を送信しました</div>
            <div style={{ fontSize: 15, color: T.muted, marginTop: 3 }}>Slack · スマートフォン</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CompleteScreen({ bc, complete, onComplete, completeTimeout }: {
  bc: string; complete: string; onComplete: (v: string) => void; completeTimeout: string;
}) {
  const rows = [
    { l: "ご担当", v: "佐藤 花子" },
    { l: "ご予約", v: "14:30", m: true },
    { l: "通知方法", v: "Slack / プッシュ" },
    { l: "ステータス", v: "通知済み" },
  ];
  return (
    <div style={{ width: 1920, height: 1080, background: T.bg, display: "flex", flexDirection: "column", fontFamily: FONT }}>
      <div style={{ height: 6, background: `linear-gradient(90deg,${bc},#b8763a,#2e6b8e)`, flexShrink: 0 }} />
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 56, padding: "48px 80px", minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ width: 96, height: 96, borderRadius: 24, background: bc + "1a", color: bc, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 28 }}><Ico.Check size={48} /></div>
          <div style={{ fontSize: 18, color: T.muted, letterSpacing: "4px", textTransform: "uppercase", fontFamily: "Inter, system-ui, sans-serif", marginBottom: 14 }}>WELCOME</div>
          <div style={{ fontSize: 84, fontWeight: 600, color: T.ink, letterSpacing: "-3px", lineHeight: 1.06, marginBottom: 18 }}>山田 太郎 様</div>
          <Editable value={complete} onChange={onComplete} placeholder="お待ちしておりました"
            style={{ fontSize: 34, color: T.sub, lineHeight: 1.5 }} />
          <div style={{ marginTop: 38 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}>
              <Ico.Clock size={22} />
              <span style={{ fontSize: 18, color: T.sub, flex: 1 }}>待機画面に戻るまで</span>
              <span style={{ fontSize: 40, fontWeight: 700, fontFamily: "monospace", color: bc }}>{completeTimeout || "10"}</span>
              <span style={{ fontSize: 18, color: T.sub }}>秒</span>
            </div>
            <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: "hidden" }}><div style={{ width: "70%", height: "100%", background: bc }} /></div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 24, justifyContent: "center" }}>
          <div style={{ background: T.canvas, border: `1px solid ${T.border}`, borderRadius: 22, padding: "34px 38px" }}>
            <div style={{ fontSize: 18, color: T.muted, letterSpacing: "2px", textTransform: "uppercase", fontFamily: "Inter, system-ui, sans-serif", marginBottom: 22 }}>予約情報 · Reservation</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "26px 32px" }}>
              {rows.map(({ l, v, m }) => (
                <div key={l}>
                  <div style={{ fontSize: 18, color: T.muted, fontWeight: 600, marginBottom: 8 }}>{l}</div>
                  <div style={{ fontSize: 34, fontWeight: 600, color: T.ink, fontFamily: m ? "monospace" : "inherit", lineHeight: 1.2 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Footer({ bc, idleTimeout }: { bc: string; idleTimeout: string }) {
  return (
    <div style={{ padding: "16px 80px 28px", display: "flex", alignItems: "center", color: T.muted, fontSize: 22, flexShrink: 0 }}>
      <span style={{ fontFamily: "monospace" }}>—:—</span>
      <span style={{ flex: 1 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span>待機画面に戻るまで</span>
        <span style={{ fontSize: 32, fontWeight: 700, fontFamily: "monospace", color: T.sub }}>{idleTimeout || "60"}</span>
        <span>秒</span>
        <div style={{ width: 200, height: 8, background: T.border, borderRadius: 4, overflow: "hidden" }}><div style={{ width: "100%", height: "100%", background: bc, borderRadius: 4 }} /></div>
      </div>
      <span style={{ flex: 1 }} />
      <span style={{ fontFamily: "monospace" }}>kiosk</span>
    </div>
  );
}

// ─── Icons (subset matching kiosk ICO) ────────────────────────────────────────
const Ico = {
  Reception: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 21v-2a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v2" /><circle cx="12" cy="8" r="4" /></svg>
  ),
  Truck: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="6" width="14" height="11" rx="1.5" /><path d="M15 9h4l3 3v5h-7z" /><circle cx="6" cy="18.5" r="1.8" /><circle cx="18" cy="18.5" r="1.8" /></svg>
  ),
  Locker: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="1.5" /><path d="M3 12h18M12 3v18" /><circle cx="8" cy="8" r="0.9" fill="currentColor" /><circle cx="16" cy="8" r="0.9" fill="currentColor" /></svg>
  ),
  Bell: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0v5l2 3H4l2-3z" /><path d="M10 19a2 2 0 0 0 4 0" /></svg>
  ),
  Check: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 6" /></svg>
  ),
  Clock: ({ size = 24 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#a8a198" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
  ),
};

// ─── Form primitives ──────────────────────────────────────────────────────────

function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)); }

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
      <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", height: "100%" }} />
    </div>
  );
}

function TextInputNumber({ value, onChange, suffix }: { value: string; onChange: (v: string) => void; suffix?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "0 10px", height: 34, gap: 4 }}>
      <input value={value} onChange={(e) => onChange(e.target.value)} type="number"
        style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 12.5, color: "#2d2a24", fontFamily: "monospace", height: "100%" }} />
      {suffix && <span style={{ color: "#a8a198", fontSize: 12 }}>{suffix}</span>}
    </div>
  );
}

function Textarea({ value, onChange, rows, placeholder }: { value: string; onChange: (v: string) => void; rows: number; placeholder?: string }) {
  return (
    <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={rows} placeholder={placeholder}
      style={{ width: "100%", border: "1px solid #d8d3c7", borderRadius: 7, background: "#fffefb", padding: "8px 10px", fontSize: 12.5, color: "#2d2a24", resize: "vertical", outline: "none", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif", boxSizing: "border-box" }} />
  );
}
