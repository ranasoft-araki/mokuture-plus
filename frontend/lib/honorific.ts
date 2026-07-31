// 氏名への敬称「様」付与ユーティリティ。
// デモの来訪者名「審査員様」等、既に敬称で終わる名前に「様」を重ねて
// 「審査員様 様」になる二重敬称を防ぐ。バックエンド _with_honorific と同じ規則。

const HONORIFIC_RE = /(?:様|さま|さん)$/;

/** 名前が既に敬称(様/さま/さん)で終わっているか。 */
export function hasHonorific(name: string | null | undefined): boolean {
  return HONORIFIC_RE.test((name ?? "").trim());
}

/** 氏名に「様」を付ける。既に敬称で終わる名前には重ねない。 */
export function withHonorific(name: string | null | undefined): string {
  const n = (name ?? "").trim();
  if (!n) return n;
  return hasHonorific(n) ? n : `${n} 様`;
}
