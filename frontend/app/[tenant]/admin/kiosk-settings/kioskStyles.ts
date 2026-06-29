export interface KioskStyleDef {
  id: string;
  name: string;
  description: string;
  bg: string;
  text: string;
  accent: string;
  accentGradient?: string;
}

// テーマ機能は廃止。キオスクは単一デザイン（default）のみを使用する。
export const KIOSK_STYLES: KioskStyleDef[] = [
  {
    id: "default",
    name: "和モダン",
    description: "木工×モダン。暗背景に苔緑アクセント",
    bg: "#1d1a15",
    text: "#fffefb",
    accent: "#2d6a4f",
  },
];
