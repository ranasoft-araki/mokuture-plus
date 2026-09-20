"""認識結果の整形(§4)。

話し言葉には入力欄に入れたくない定型表現が混ざる:

    「株式会社ラナソフトから来ました」 → 株式会社ラナソフト
    「ラナソフトです」                 → ラナソフト
    「荒木秀人と申します」             → 荒木秀人

**法人格(株式会社・有限会社など)は定型表現ではないので削らない**(§4)。
「株式会社」で始まる社名を「ラナソフト」にしてしまうと、受付通知を受け取る側が
別の会社と区別できなくなる。

ここは純粋な文字列処理だけで、外部辞書も推測もしない。整形前の文字列(raw)も一緒に
画面へ返し、削りすぎたときは利用者がその場で戻せるようにする。
"""
from __future__ import annotations

import re
import unicodedata

# ── 共通 ──────────────────────────────────────────────────────────────────────

# whisper が付ける句読点・記号。氏名や社名には不要。
_PUNCT = "。、，．！？!?…・「」『』（）()〈〉《》【】"
_PUNCT_RE = re.compile("[" + re.escape(_PUNCT) + "]")

# 言い淀み。先頭に来たものだけ落とす(社名の一部の可能性を避ける)。
_FILLERS = ("えーと", "えっと", "ええと", "あのー", "あの", "えー", "ええ", "まあ", "その")

# 日本語の文字どうしの間に入った空白。whisper がトークン境界で入れることがある。
_JA = r"[぀-ヿ㐀-鿿ｦ-ﾟ]"
_JA_SPACE_RE = re.compile(rf"(?<={_JA})[ 　]+(?={_JA})")


def _strip_edges(text: str) -> str:
    return text.strip(" 　\t\r\n-‐‑–—ー_")


def normalize_common(text: str) -> str:
    """どの項目にも共通の掃除。記号を落とし、空白を詰める。"""
    if not text:
        return ""
    # 互換文字だけ畳む(全角英数 → 半角、半角カナ → 全角カナ)。
    # ㈱ → (株) のような変換も NFKC の範囲なので、法人格は失われない。
    t = unicodedata.normalize("NFKC", text)
    t = _PUNCT_RE.sub(" ", t)
    t = t.replace("　", " ")
    t = re.sub(r"\s+", " ", t)
    t = _JA_SPACE_RE.sub("", t)
    return _strip_edges(t)


def strip_fillers(text: str) -> str:
    """先頭の言い淀みを落とす。"""
    t = text
    changed = True
    while changed:
        changed = False
        t = _strip_edges(t)
        for f in _FILLERS:
            if t.startswith(f) and len(t) > len(f):
                t = t[len(f):]
                changed = True
                break
    return _strip_edges(t)


def _strip_repeatedly(text: str, patterns: list[re.Pattern[str]]) -> str:
    """当てはまる表現が無くなるまで削る。「荒木ですと申します」のような重なりに対応。"""
    t = text
    for _ in range(4):
        before = t
        for p in patterns:
            t = _strip_edges(p.sub("", t))
        if t == before:
            break
    return t


# ── 会社名 ────────────────────────────────────────────────────────────────────

# 先頭に付く自己紹介。「私は」「弊社は」など。
_COMPANY_PREFIX = [
    re.compile(r"^(?:私|わたし|わたくし|僕|自分)は"),
    re.compile(r"^(?:弊社|当社|わが社)は"),
]

# 末尾に付く定型表現。法人格は含めない。
_COMPANY_SUFFIX = [
    re.compile(r"(?:から)?(?:参りました|まいりました|来ました|きました|伺いました|お伺いしました)$"),
    re.compile(r"(?:から)?(?:来ています|きています|参っております)$"),
    re.compile(r"の(?:者|もの)(?:です|でございます)?$"),
    re.compile(r"(?:と申します|と言います|といいます|申します)$"),
    re.compile(r"(?:でございます|です|になります|ます)$"),
    re.compile(r"(?:の)?(?:担当|営業)$"),
    re.compile(r"から$"),
]


def normalize_company(text: str) -> str:
    """会社名の候補を作る。法人格(株式会社など)は保持する(§4)。"""
    t = strip_fillers(normalize_common(text))
    t = _strip_repeatedly(t, _COMPANY_PREFIX)
    t = _strip_repeatedly(t, _COMPANY_SUFFIX)
    return _strip_edges(t)


# ── 氏名 ──────────────────────────────────────────────────────────────────────

_PERSON_PREFIX = [
    re.compile(r"^(?:私|わたし|わたくし|僕|自分)は"),
    re.compile(r"^(?:名前は|お名前は)"),
]

_PERSON_SUFFIX = [
    re.compile(r"(?:と申します|と言います|といいます|申します)$"),
    re.compile(r"(?:と申しますが|ともうします)$"),
    re.compile(r"(?:でございます|です|になります|ます)$"),
    re.compile(r"(?:と)?いいます$"),
]


def normalize_person(text: str) -> str:
    """訪問者名の候補を作る。

    敬称(様・さん)は落とさない。自分の名前に付ける人は少ないが、外国語話者の
    「ミスター〇〇」のような自称を勝手に削ると別人の表記になりかねないため、
    判断は画面(利用者)に委ねる。
    """
    t = strip_fillers(normalize_common(text))
    t = _strip_repeatedly(t, _PERSON_PREFIX)
    t = _strip_repeatedly(t, _PERSON_SUFFIX)
    return _strip_edges(t)


# ── 照合用(担当者名・第3段階) ────────────────────────────────────────────────

_HONORIFIC = re.compile(r"(?:さん|サン|様|さま|氏|くん|君|ちゃん)$")
_DEPT_TAIL = re.compile(r"(?:部|課|室|グループ|チーム|本部|事業部)$")


def to_hiragana(text: str) -> str:
    """カタカナをひらがなに寄せる。読み仮名どうしを比べるため。"""
    out = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:        # ァ-ヶ
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


# 五十音の段(母音)。長音の書き方の揺れを吸収するのに使う。
# 小書き(ゃゅょ)も段に入れる。「しょうじ」の「う」は「ょ」(お段)に続く長音なので、
# ここに無いと「ショージ」と同じキーにならない。
_VOWEL_ROWS = {
    "a": "あかさたなはまやらわがざだばぱぁゃゎ",
    "i": "いきしちにひみりぎじぢびぴぃ",
    "u": "うくすつぬふむゆるぐずづぶぷぅゅ",
    "e": "えけせてねへめれげぜでべぺぇ",
    "o": "おこそとのほもよろごぞどぼぽぉょ",
}
_VOWEL_OF = {ch: v for v, chars in _VOWEL_ROWS.items() for ch in chars}


def _collapse_long_vowels(text: str) -> str:
    """長音の書き方の違いを畳む。

        さとう / サトー → さと
        こうの / コーノ → この
        せいじ / セージ → せじ

    「おう」「うう」「えい」は日本語で長音を表す綴り。伸ばし棒を消すだけだと
    「コーノ」と「こうの」が別物になり、読み仮名の照合が当たらない。
    """
    out: list[str] = []
    for ch in text:
        if out:
            prev = _VOWEL_OF.get(out[-1])
            if ch == "う" and prev in ("o", "u"):
                continue
            if ch == "い" and prev == "e":
                continue
        out.append(ch)
    return "".join(out)


def normalize_reading(text: str) -> str:
    """読み比べ用のキーにする。ひらがな化し、長音・促音・拗音・空白の揺れを吸収する。

    別人が同じキーになることはあり得る(「さとう」と「さと」)。それでも構わない。
    ここで作るのは**候補を見つけるためのキー**で、確定は必ず利用者が画面で行う(§4)。
    """
    t = to_hiragana(normalize_common(text))
    t = _HONORIFIC.sub("", t)
    t = t.replace("ー", "")
    t = _collapse_long_vowels(t)
    t = t.replace("っ", "").replace("ゃ", "や").replace("ゅ", "ゆ").replace("ょ", "よ")
    t = re.sub(r"[\s・]", "", t)
    return t


def split_department(text: str) -> tuple[str, str]:
    """「営業部の田中さん」→ ("営業部", "田中")。部署が無ければ ("", 全体)。

    「の」で切れるときだけ部署とみなす。取れなければ推測しない。
    """
    t = strip_fillers(normalize_common(text))
    m = re.match(r"^(.{1,12}?(?:部|課|室|グループ|チーム|本部|事業部))の(.+)$", t)
    if m:
        return m.group(1), _HONORIFIC.sub("", _strip_edges(m.group(2)))
    # 「営業の田中さん」のように部/課が略される言い方も拾う
    m = re.match(r"^(.{1,8}?)の(.{1,12})$", t)
    if m:
        return m.group(1), _HONORIFIC.sub("", _strip_edges(m.group(2)))
    return "", _HONORIFIC.sub("", t)


def strip_honorific(text: str) -> str:
    return _strip_edges(_HONORIFIC.sub("", _strip_edges(text)))


def department_stem(text: str) -> str:
    """「営業部」「営業」を同じキーにする。"""
    return _DEPT_TAIL.sub("", normalize_reading(text))


# ── 項目ごとの入口 ────────────────────────────────────────────────────────────

def normalize(field: str, text: str) -> str:
    if field == "company":
        return normalize_company(text)
    if field == "person_name":
        return normalize_person(text)
    if field == "staff":
        return strip_fillers(normalize_common(text))
    return normalize_common(text)
