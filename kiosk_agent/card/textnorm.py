"""文字列の正規化と、OCR に起因する取り違えの補正。

方針は「根拠のある置き換えだけを行い、無ければ手を触れない」。
たとえば 0/O の取り違えは、電話番号として解釈できる並びの中でだけ直す。
文章の中の O を勝手に 0 にはしない。補正した値は confidence を下げて返す
（呼び出し側が「要確認」として黄色で出せるように）。

存在しない文字を足して値を作ることはしない。唯一の例外はメールアドレスの "@" で、
これは日本語認識モデルの文字セットに "@" 自体が無く原理的に出力できないため、
「メールアドレスの形をしているのに区切り文字だけが別の字になっている」場合に限り
復元する（英数字モデルが使える端末ではそもそもこの経路に入らない）。
"""
from __future__ import annotations

import re
import unicodedata

# ハイフンに見える文字。数字の並びの中でだけ半角ハイフンに寄せる。
HYPHEN_LIKE = "‐‑‒–—―ー−ｰ－~〜"
_HYPHEN_RE = re.compile(f"[{re.escape(HYPHEN_LIKE)}]")

# 数字の並び（電話番号・郵便番号）の中で起きやすい取り違え
DIGIT_CONFUSIONS = {
    "O": "0", "o": "0", "Ｏ": "0", "ｏ": "0",
    "D": "0", "Q": "0",
    "I": "1", "l": "1", "|": "1", "ｌ": "1", "Ｉ": "1",
    "S": "5", "s": "5",
    "B": "8",
    "Z": "2", "z": "2",
    "G": "6",
    "T": "7",
}

# 〒 は日本語認識モデルの文字セットに無いことがあり、下記のような字に化ける。
POSTAL_MARK_CONFUSIONS = "〒テデ干千下亍武乎"


def to_halfwidth(text: str) -> str:
    """全角の英数字・記号を半角へ。かな・漢字はそのまま。"""
    return unicodedata.normalize("NFKC", text)


def normalize_line(text: str) -> str:
    """行全体の軽い正規化。文字そのものは置き換えない。

    - 連続空白（全角空白を含む）を半角スペース 1 つに
    - 前後の空白と、行頭行末の飾り記号を落とす

    ここで NFKC（全角→半角）はかけない。会社名の「（株）」のような全角記号は
    名刺の印字どおりに見せたいため。半角化が必要なのはメール・電話・郵便番号を
    解析するときだけなので、その場で to_halfwidth() を通している。
    """
    t = text.replace("　", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip(" \t·•・|")


def fix_digits(chunk: str) -> str:
    """数字であるべき塊の中の取り違えを直す。呼び出し側が文脈を保証すること。"""
    return "".join(DIGIT_CONFUSIONS.get(ch, ch) for ch in chunk)


def normalize_hyphens(chunk: str) -> str:
    """各種ハイフン様の文字を半角ハイフンに揃える。"""
    return _HYPHEN_RE.sub("-", chunk)


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def has_cjk(text: str) -> bool:
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF) or (0x3400 <= o <= 0x4DBF) or \
           (0x4E00 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF):
            return True
    return False


def is_all_kana(text: str) -> bool:
    """ひらがな・カタカナ（と空白・長音）だけで出来ているか。"""
    stripped = re.sub(r"[\s　ー・]", "", text)
    if not stripped:
        return False
    return all(0x3041 <= ord(ch) <= 0x30FF for ch in stripped)


def kata_to_hira(text: str) -> str:
    return "".join(
        chr(ord(ch) - 0x60) if 0x30A1 <= ord(ch) <= 0x30F6 else ch for ch in text
    )


# ── かな → ローマ字 ────────────────────────────────────────────────────────────
# メールアドレスのローカル部・ドメインと、氏名/社名の読みを突き合わせるために使う。
# 完全なヘボン式ではなく「比較に使えれば十分」の簡易版。

_ROMAJI_DIGRAPH = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "うぃ": "wi", "うぇ": "we", "てぃ": "ti", "でぃ": "di",
    "ちぇ": "che", "しぇ": "she", "じぇ": "je", "でゅ": "dyu",
    "ヴぁ": "va", "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
}

_ROMAJI_SINGLE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゔ": "vu",
}


def kana_to_romaji(text: str) -> str:
    """かな（カタカナ含む）を比較用のローマ字にする。かな以外は落とす。

    長音「ー」は落とす（"サンプル" と "sanpuru"/"sampuru" を比べたいだけなので、
    母音の伸ばしは比較の邪魔にしかならない）。促音「っ」は次の子音を重ねる。
    """
    s = kata_to_hira(text)
    out: list[str] = []
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two in _ROMAJI_DIGRAPH:
            out.append(_ROMAJI_DIGRAPH[two])
            i += 2
            continue
        ch = s[i]
        if ch == "っ":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            r = _ROMAJI_DIGRAPH.get(s[i + 1:i + 3], _ROMAJI_SINGLE.get(nxt, ""))
            if r:
                out.append(r[0])
            i += 1
            continue
        if ch in ("ー", "・", " ", "　"):
            i += 1
            continue
        if ch in _ROMAJI_SINGLE:
            out.append(_ROMAJI_SINGLE[ch])
        i += 1
    # ん の直後が b/m/p なら m（ヘボン式）。ドメインとの比較で効くことがある。
    joined = "".join(out)
    return re.sub(r"n(?=[bmp])", "m", joined)


def romaji_key(text: str) -> str:
    """比較用のキー。英字だけを小文字で残す。"""
    return re.sub(r"[^a-z]", "", to_halfwidth(text).lower())


def prefix_overlap(a: str, b: str) -> int:
    """先頭から何文字一致するか。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ── 辞書照合用の正規化 ─────────────────────────────────────────────────────────
# OCR は日本語で決まった取り違えをする。小書き文字を大書きに読む（ャ→ヤ）、
# ソとン、シとツ を入れ替える、など。これらは「辞書と突き合わせるとき」だけ
# 吸収する。表示する値は突き合わせに成功した辞書の語を使い、信頼度を下げる。

_SMALL_TO_LARGE = str.maketrans({
    "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ",
    "ッ": "ツ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ",
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
    "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ",
})

# 字形が近く OCR が取り違えやすい組。代表 1 文字に寄せる。
_SHAPE_CONFUSIONS = str.maketrans({
    "ソ": "ン", "ﾝ": "ン",
    "シ": "ツ",
    "ロ": "口",          # 漢字の口とカタカナのロ
    "エ": "工",
    "力": "カ",          # 漢字の力とカタカナのカ
    "才": "オ",
    "二": "ニ",
    "―": "ー", "‐": "ー", "−": "ー", "-": "ー",
})


def canon(text: str) -> str:
    """辞書照合用のキー。表示には使わない。

    NFKC → 空白除去 → 英字小文字化 → 小書き文字を大書きへ → 字形の近い文字を代表へ。
    """
    t = to_halfwidth(text)
    t = re.sub(r"[\s　・/|]", "", t).lower()
    t = t.translate(_SMALL_TO_LARGE)
    return t.translate(_SHAPE_CONFUSIONS)
