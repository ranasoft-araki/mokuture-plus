// プライバシーポリシー・利用規約の共通の枠(公開ページ・ログイン不要)。
// Google の OAuth 同意画面(「アプリケーション プライバシー ポリシー」リンク)からも開かれる。

import Link from "next/link";

const FONT_JP = '"Noto Sans JP", system-ui, sans-serif';

export const OPERATOR = "株式会社ラナソフト";
export const CONTACT_EMAIL = "mokuture@ranasoft.co.jp";

export function LegalPage({ title, updated, children }: { title: string; updated: string; children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: "#f4f1ea", padding: "40px 16px", fontFamily: FONT_JP, color: "#2d2a24" }}>
      <article style={{ maxWidth: 760, margin: "0 auto", background: "#fffefb", border: "1px solid #efece5", borderRadius: 12, padding: "32px 28px", lineHeight: 1.9, fontSize: 14.5 }}>
        <div style={{ fontSize: 13, color: "#6b6559", marginBottom: 6 }}>mokuture+</div>
        <h1 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 4px" }}>{title}</h1>
        <div style={{ fontSize: 12.5, color: "#8a8478", marginBottom: 28 }}>{updated}</div>
        {children}
        <nav style={{ marginTop: 36, paddingTop: 18, borderTop: "1px solid #efece5", fontSize: 13, display: "flex", gap: 18, flexWrap: "wrap" }}>
          <Link href="/privacy" style={{ color: "#4a7c4e" }}>プライバシーポリシー</Link>
          <Link href="/terms" style={{ color: "#4a7c4e" }}>利用規約</Link>
          <Link href="/login" style={{ color: "#4a7c4e" }}>ログイン</Link>
        </nav>
      </article>
    </div>
  );
}

export function H2({ children }: { children: React.ReactNode }) {
  return <h2 style={{ fontSize: 17, fontWeight: 700, margin: "28px 0 8px", paddingLeft: 10, borderLeft: "3px solid #4a7c4e" }}>{children}</h2>;
}

export function P({ children }: { children: React.ReactNode }) {
  return <p style={{ margin: "0 0 10px" }}>{children}</p>;
}

export function UL({ children }: { children: React.ReactNode }) {
  return <ul style={{ margin: "0 0 12px", paddingLeft: 22, listStyle: "disc" }}>{children}</ul>;
}
