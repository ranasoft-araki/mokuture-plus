"use client";
import { useState } from "react";

// 50-on grid: null = empty cell (ya/wa rows have gaps)
const HIRAGANA_ROWS: (string | null)[][] = [
  ["あ", "か", "さ", "た", "な", "は", "ま", "や", "ら", "わ"],
  ["い", "き", "し", "ち", "に", "ひ", "み", null,  "り", null],
  ["う", "く", "す", "つ", "ぬ", "ふ", "む", "ゆ", "る", null],
  ["え", "け", "せ", "て", "ね", "へ", "め", null,  "れ", null],
  ["お", "こ", "そ", "と", "の", "ほ", "も", "よ", "ろ", "を"],
];

// Dakuten toggle (voiced ↔ unvoiced, includes unvoicing voiced chars)
const DAKUTEN_MAP: Record<string, string> = {
  か:"が",き:"ぎ",く:"ぐ",け:"げ",こ:"ご",
  さ:"ざ",し:"じ",す:"ず",せ:"ぜ",そ:"ぞ",
  た:"だ",ち:"ぢ",つ:"づ",て:"で",と:"ど",
  は:"ば",ひ:"び",ふ:"ぶ",へ:"べ",ほ:"ぼ",
  が:"か",ぎ:"き",ぐ:"く",げ:"け",ご:"こ",
  ざ:"さ",じ:"し",ず:"す",ぜ:"せ",ぞ:"そ",
  だ:"た",ぢ:"ち",づ:"つ",で:"て",ど:"と",
  ば:"は",び:"ひ",ぶ:"ふ",べ:"へ",ぼ:"ほ",
  ぱ:"ば",ぴ:"び",ぷ:"ぶ",ぺ:"べ",ぽ:"ぼ",
};

// Handakuten toggle (は行 ↔ ぱ行; ば行→ぱ行 also supported)
const HANDAKUTEN_MAP: Record<string, string> = {
  は:"ぱ",ひ:"ぴ",ふ:"ぷ",へ:"ぺ",ほ:"ぽ",
  ぱ:"は",ぴ:"ひ",ぷ:"ふ",ぺ:"へ",ぽ:"ほ",
  ば:"ぱ",び:"ぴ",ぶ:"ぷ",べ:"ぺ",ぼ:"ぽ",
};

// Small kana toggle (large ↔ small)
const SMALL_MAP: Record<string, string> = {
  あ:"ぁ",い:"ぃ",う:"ぅ",え:"ぇ",お:"ぉ",
  つ:"っ",や:"ゃ",ゆ:"ゅ",よ:"ょ",わ:"ゎ",
  ぁ:"あ",ぃ:"い",ぅ:"う",ぇ:"え",ぉ:"お",
  っ:"つ",ゃ:"や",ゅ:"ゆ",ょ:"よ",ゎ:"わ",
};

// Convert a hiragana character/map to katakana (U+3041-U+3096 → +0x60)
function hiraToKata(ch: string): string {
  return ch.replace(/[ぁ-ゖ]/g, (c) =>
    String.fromCharCode(c.charCodeAt(0) + 0x60)
  );
}

function buildKatakanaMap(base: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [k, v] of Object.entries(base)) {
    result[hiraToKata(k)] = hiraToKata(v);
  }
  return result;
}

const DAKUTEN_KATA = buildKatakanaMap(DAKUTEN_MAP);
const HANDAKUTEN_KATA = buildKatakanaMap(HANDAKUTEN_MAP);
const SMALL_KATA = buildKatakanaMap(SMALL_MAP);

export type JapaneseKeyboardProps = {
  value: string;
  onChange: (v: string) => void;
  onClose: () => void;
};

const KEY_W = 68;
const KEY_H = 54;
const GAP = 5;

export function JapaneseKeyboard({ value, onChange, onClose }: JapaneseKeyboardProps) {
  const [katakana, setKatakana] = useState(false);

  const grid = katakana
    ? HIRAGANA_ROWS.map((row) => row.map((c) => (c ? hiraToKata(c) : null)))
    : HIRAGANA_ROWS;

  const dakutenMap = katakana ? DAKUTEN_KATA : DAKUTEN_MAP;
  const handakutenMap = katakana ? HANDAKUTEN_KATA : HANDAKUTEN_MAP;
  const smallMap = katakana ? SMALL_KATA : SMALL_MAP;

  const append = (char: string) => onChange(value + char);

  const modifyLast = (map: Record<string, string>) => {
    if (!value) return;
    const last = value[value.length - 1];
    if (map[last] !== undefined) {
      onChange(value.slice(0, -1) + map[last]);
    }
  };

  const backspace = () => {
    if (value.length > 0) onChange(value.slice(0, -1));
  };

  // Use onMouseDown+preventDefault to avoid stealing focus from the input
  const tap = (fn: () => void) => ({
    onMouseDown: (e: React.MouseEvent) => { e.preventDefault(); fn(); },
    onTouchStart: (e: React.TouchEvent) => { e.preventDefault(); fn(); },
  });

  const keyBase: React.CSSProperties = {
    height: KEY_H,
    borderRadius: 8,
    border: "1.5px solid #d8d3c7",
    background: "#fffefb",
    color: "#2d2a24",
    fontSize: 19,
    fontWeight: 400,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "'Noto Sans JP', 'Hiragino Kaku Gothic ProN', sans-serif",
    userSelect: "none",
    flexShrink: 0,
    boxShadow: "0 1px 3px rgba(0,0,0,0.07)",
    touchAction: "manipulation",
  };

  const charKey: React.CSSProperties = { ...keyBase, width: KEY_W };
  const ctrlKey: React.CSSProperties = { ...keyBase, width: KEY_W, fontSize: 14, color: "#4a4338" };
  const wideKey = (mult: number): React.CSSProperties => ({
    ...keyBase,
    width: KEY_W * mult + GAP * (mult - 1),
    fontSize: 14,
    color: "#4a4338",
  });
  const accentKey = (color: string): React.CSSProperties => ({
    ...wideKey(1.6),
    background: color,
    borderColor: color,
    color: "#fff",
    fontWeight: 600,
    fontSize: 14,
  });
  const toggleKey: React.CSSProperties = {
    ...ctrlKey,
    background: katakana ? "#5a4a3a" : "#fffefb",
    borderColor: katakana ? "#5a4a3a" : "#d8d3c7",
    color: katakana ? "#fff" : "#4a4338",
    fontWeight: katakana ? 700 : 400,
  };

  return (
    <div
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        background: "#edeae3",
        borderTop: "1.5px solid #c8c3bc",
        padding: `14px 0 20px`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: GAP,
        zIndex: 9000,
        boxShadow: "0 -6px 32px rgba(0,0,0,0.12)",
      }}
    >
      {/* 50-on grid (5 rows × 10 cols) */}
      {grid.map((row, ri) => (
        <div key={ri} style={{ display: "flex", gap: GAP }}>
          {row.map((char, ci) =>
            char ? (
              <button key={ci} type="button" {...tap(() => append(char))} style={charKey}>
                {char}
              </button>
            ) : (
              <div key={ci} style={{ width: KEY_W, height: KEY_H, flexShrink: 0 }} />
            )
          )}
        </div>
      ))}

      {/* Control row */}
      <div style={{ display: "flex", gap: GAP, marginTop: 3 }}>
        {/* ん / ン */}
        <button type="button" {...tap(() => append(katakana ? "ン" : "ん"))} style={charKey}>
          {katakana ? "ン" : "ん"}
        </button>

        {/* ゛ dakuten */}
        <button type="button" {...tap(() => modifyLast(dakutenMap))} style={ctrlKey}>
          ゛
        </button>

        {/* ゜ handakuten */}
        <button type="button" {...tap(() => modifyLast(handakutenMap))} style={ctrlKey}>
          ゜
        </button>

        {/* 小 small kana */}
        <button type="button" {...tap(() => modifyLast(smallMap))} style={ctrlKey}>
          小
        </button>

        {/* ー long vowel */}
        <button type="button" {...tap(() => append("ー"))} style={ctrlKey}>
          ー
        </button>

        {/* Space */}
        <button type="button" {...tap(() => append("　"))} style={wideKey(1.8)}>
          スペース
        </button>

        {/* カナ / ひら toggle */}
        <button type="button" {...tap(() => setKatakana((k) => !k))} style={toggleKey}>
          {katakana ? "ひら" : "カナ"}
        </button>

        {/* Backspace */}
        <button type="button" {...tap(backspace)} style={wideKey(1.6)}>
          ⌫ 削除
        </button>

        {/* 確定 */}
        <button type="button" {...tap(onClose)} style={accentKey("#4a7c59")}>
          確定
        </button>
      </div>
    </div>
  );
}
