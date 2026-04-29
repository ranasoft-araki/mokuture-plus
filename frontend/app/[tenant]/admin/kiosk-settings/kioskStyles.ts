export interface KioskStyleDef {
  id: string;
  name: string;
  description: string;
  bg: string;
  text: string;
  accent: string;
  accentGradient?: string;
}

// パターンを追加する場合はここにエントリを追加し、
// backend/app/api/settings.py の ALLOWED_KIOSK_STYLES にも id を追加すること。
export const KIOSK_STYLES: KioskStyleDef[] = [
  {
    id: "default",
    name: "スタンダード",
    description: "木工×モダン。暗背景に苔緑アクセント",
    bg: "#1d1a15",
    text: "#fffefb",
    accent: "#4a7c4e",
  },
  {
    id: "medical",
    name: "医療・クリニック",
    description: "清潔感のある白×ブルー。信頼と安心",
    bg: "#f5f9fc",
    text: "#0e2a3d",
    accent: "#1f6fa8",
  },
  {
    id: "retail",
    name: "小売・コンビニ",
    description: "赤×黄の元気な販促トーン",
    bg: "#fffbe6",
    text: "#1a1a1a",
    accent: "#ff5b3a",
  },
  {
    id: "hotel",
    name: "高級ホテル",
    description: "黒×金のラグジュアリー。静謐な歓迎",
    bg: "#0a0907",
    text: "#e8d8a8",
    accent: "#c9a55a",
  },
  {
    id: "startup",
    name: "B2B SaaS",
    description: "紫グラデ×グラスモーフィズム",
    bg: "#0a0a14",
    text: "#ffffff",
    accent: "#6b3aff",
    accentGradient: "linear-gradient(135deg, #6b3aff, #ff3a8e)",
  },
  {
    id: "school",
    name: "こども施設",
    description: "パステル×絵文字。園・塾・習い事",
    bg: "#fff5e6",
    text: "#3a2818",
    accent: "#ff9d6c",
  },
  {
    id: "craft",
    name: "工芸・工房",
    description: "紙テクスチャ×明朝。ギャラリー・作家",
    bg: "#f4ede0",
    text: "#1a1612",
    accent: "#6a5a48",
  },
  {
    id: "industrial",
    name: "物流・工場",
    description: "ハザード黄×ダーク。視認性最優先",
    bg: "#1a1d22",
    text: "#ffffff",
    accent: "#ffd23a",
  },
  {
    id: "restaurant",
    name: "飲食店",
    description: "琥珀×ダークブラウン。温かいおもてなし",
    bg: "#2a1810",
    text: "#f5e6c8",
    accent: "#d4a868",
  },
  {
    id: "mono",
    name: "コワーキング",
    description: "純モノクロ×超大タイポ。建築的ミニマル",
    bg: "#ffffff",
    text: "#000000",
    accent: "#000000",
  },
  {
    id: "gym",
    name: "ジム・スポーツ",
    description: "ネオン緑×ダーク。エネルギッシュ",
    bg: "#0a0e0a",
    text: "#ffffff",
    accent: "#c4ff3a",
  },
];
