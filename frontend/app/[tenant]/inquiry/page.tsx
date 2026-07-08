"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

// mokuture 共通問い合わせフォーム（公開・認証不要）。
// キオスクの「営業お断り」画面が案内する QR のリンク先。テナントが外部フォールURLを
// 設定していない場合の共通受け皿で、送信内容は管理画面「問い合わせ」で確認できる。
export default function InquiryPage() {
  const params = useParams<{ tenant: string }>();
  const tenant = params.tenant;

  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) { setError("お名前を入力してください"); return; }
    if (!message.trim()) { setError("お問い合わせ内容を入力してください"); return; }
    setSubmitting(true);
    try {
      await api.submitInquiry(tenant, {
        name: name.trim(),
        company: company.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        message: message.trim(),
      });
      setDone(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "送信に失敗しました。時間をおいて再度お試しください。");
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%", border: "1px solid #d8d3c7", borderRadius: 10, background: "#fffefb",
    padding: "12px 14px", fontSize: 16, color: "#1d1a15", outline: "none", boxSizing: "border-box",
    fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif",
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: "#2d2a24", marginBottom: 6, display: "block" };

  return (
    <div style={{ minHeight: "100vh", background: "#faf8f4", display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 20px", fontFamily: "'Noto Sans JP', Inter, system-ui, sans-serif" }}>
      <div style={{ width: "100%", maxWidth: 560 }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.3em", color: "#a8a198", textTransform: "uppercase", marginBottom: 8 }}>CONTACT</div>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: "#1d1a15", margin: 0 }}>お問い合わせ</h1>
          <p style={{ fontSize: 14, color: "#6b6559", marginTop: 10, lineHeight: 1.7 }}>
            以下のフォームよりお問い合わせください。<br />受付でのお取次ぎは行っておりません。
          </p>
        </div>

        {done ? (
          <div style={{ background: "#fffefb", border: "1px solid #e7e2d8", borderRadius: 16, padding: "40px 28px", textAlign: "center" }}>
            <div style={{ width: 64, height: 64, borderRadius: "50%", background: "rgba(74,124,78,0.14)", color: "#2e5c32", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 6" /></svg>
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#1d1a15", marginBottom: 10 }}>送信しました</div>
            <p style={{ fontSize: 14, color: "#6b6559", lineHeight: 1.7, margin: 0 }}>
              お問い合わせありがとうございます。<br />内容を確認のうえ、担当者よりご連絡いたします。
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ background: "#fffefb", border: "1px solid #e7e2d8", borderRadius: 16, padding: "28px 24px", display: "flex", flexDirection: "column", gap: 18 }}>
            {error && (
              <div style={{ background: "#fdf2f1", border: "1px solid #f0b9b5", borderRadius: 10, padding: "12px 14px", fontSize: 13.5, color: "#a84238" }}>
                {error}
              </div>
            )}
            <div>
              <label style={labelStyle}>お名前 <span style={{ color: "#a84238" }}>*</span></label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="山田 太郎" style={inputStyle} autoComplete="name" />
            </div>
            <div>
              <label style={labelStyle}>会社名</label>
              <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="株式会社〇〇" style={inputStyle} autoComplete="organization" />
            </div>
            <div>
              <label style={labelStyle}>メールアドレス</label>
              <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" type="email" style={inputStyle} autoComplete="email" />
            </div>
            <div>
              <label style={labelStyle}>電話番号</label>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="03-1234-5678" type="tel" style={inputStyle} autoComplete="tel" />
            </div>
            <div>
              <label style={labelStyle}>お問い合わせ内容 <span style={{ color: "#a84238" }}>*</span></label>
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={6} placeholder="お問い合わせ内容をご記入ください" style={{ ...inputStyle, resize: "vertical" }} />
            </div>
            <button
              type="submit"
              disabled={submitting}
              style={{ marginTop: 4, width: "100%", height: 52, background: submitting ? "#4a7c4e" : "#1d1a15", border: "none", borderRadius: 12, color: "#fff", fontSize: 16, fontWeight: 700, cursor: submitting ? "not-allowed" : "pointer", fontFamily: "inherit" }}
            >
              {submitting ? "送信中…" : "送信する"}
            </button>
          </form>
        )}

        <div style={{ textAlign: "center", marginTop: 22, fontSize: 11, color: "#a8a198", letterSpacing: "0.05em" }}>Powered by mokuture+</div>
      </div>
    </div>
  );
}
