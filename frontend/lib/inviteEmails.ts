// 招待メールの宛先として貼り付けられた文字列から、メールアドレスを取り出す。
//
// 区切りは 改行 / , ; / タブ(Excel の列) / 全角の 、，；。・／ / 空白 のどれでもよい。
// Outlook・Gmail からコピーした「山田 太郎 <taro@example.jp>」の形はかっこの中だけを使う。
// 全角の英数字・＠は半角へ寄せる(NFKC)。
// 「@」を含むのに形が崩れているものは「形式の誤り」として見せる(黙って捨てない)。
// 「@」を含まない語(名前など)はアドレスではないので、別に「読み飛ばした語」として返す。
//
// 語の中からアドレスの部分だけを取り出す(「E-mail:taro@x.jp」「taro@x.jpまで」「taro@x.jp（山田）」
// 「文末の taro@x.jp.」)。取り出した値がそのままログインIDになり、メールもそこへ届く。
// 判定は ASCII だけの厳しい形。backend(services/invitations.STRICT_EMAIL_RE / _EXTRACT_RE)と同じにする。

const LOCAL = "[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*";
const LABEL = "[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?";
const EMAIL_RE = new RegExp(`^${LOCAL}@${LABEL}(?:\\.${LABEL})+$`);
const EXTRACT_RE = /[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+/;

export type ParsedStatus = "ok" | "invalid" | "duplicate";

export interface ParsedEmail {
  email: string;
  status: ParsedStatus;
}

export interface ParsedEmailList {
  entries: ParsedEmail[];
  /** 「@」を含まず、アドレスではないとして読み飛ばした語(名前など) */
  skipped: string[];
}

// 1語から取り出したアドレス(区切り記号なしで2件くっついた「a@x.jp／b@x.jp」も両方)。
// アドレスらしい部分が無ければ、前後を整えた語をそのまま1件で返す。
function clean(s: string): string[] {
  let v = s.trim().replace(/^["'“”‘’<>()[\]「」『』]+|["'“”‘’<>()[\]「」『』]+$/g, "");
  if (/^mailto:/i.test(v)) v = v.slice(7);
  const found = Array.from(v.matchAll(new RegExp(EXTRACT_RE.source, "g")))
    .map((m) => m[0].replace(/^\.+|\.+$/g, ""))
    .filter(Boolean);
  return found.length ? found : [v.trim()];
}

export function parseEmailList(text: string): ParsedEmailList {
  const src = (text || "").normalize("NFKC");
  const entries: ParsedEmail[] = [];
  const skipped: string[] = [];
  const seen = new Set<string>();

  // 「/」(全角の「／」も NFKC でこれになる)も区切りにする。アドレスに「/」を使う人はまずいない。
  for (const chunk of src.split(/[\r\n,;、。・/\t]+/)) {
    const part = chunk.trim();
    if (!part) continue;
    // 「名前 <アドレス>」はかっこの中を取り出し、残りは空白で区切って調べる
    // (残りの名前は「@」が無いので読み飛ばす語になり、かっこの外のアドレスも落とさない)。
    const bracketed = Array.from(part.matchAll(/<([^<>]*@[^<>]*)>/g)).map((m) => m[1]);
    const rest = part.replace(/<[^<>]*@[^<>]*>/g, " ");
    const candidates = [...bracketed, ...rest.split(/\s+/)];
    for (const v of candidates.flatMap(clean)) {
      if (!v) continue;
      if (!v.includes("@")) {
        skipped.push(v);
        continue;
      }
      const key = v.toLowerCase();
      if (!EMAIL_RE.test(v) || v.length > 254) {
        entries.push({ email: v, status: "invalid" });
      } else if (seen.has(key)) {
        entries.push({ email: v, status: "duplicate" });
      } else {
        seen.add(key);
        entries.push({ email: v, status: "ok" });
      }
    }
  }
  return { entries, skipped };
}
