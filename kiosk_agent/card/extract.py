"""OCR 結果からの項目抽出と信頼度付与（§8 / §9）。

抽出の順番には意味がある。確実なもの（正規表現で判定できる連絡先）から先に決めて、
その行を「使用済み」にしてから、曖昧なもの（会社名・氏名）を残りの行から選ぶ。
こうしないと、住所やメールの行が会社名や氏名の候補として混ざる。

    連絡先（メール / URL / 電話 / 郵便番号 / 住所）
      → 会社名（法人格 → 無ければ文字サイズ・位置・メールドメインとの一致）
      → 部署 / 役職（辞書）
      → 氏名（文字サイズ・位置・姓辞書・メールのローカル部との一致）
      → 氏名の読み（氏名の近くにあるかな行）

画像に無い文字列を作らないこと。補正するのは「その並びが数字であるべき」と
分かっている場所だけで、補正した値は信頼度を下げて返す。
ログに値そのものを出さない（この模組は logging を一切呼ばない）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from card import dicts, settings
from card.textnorm import (
    DIGIT_CONFUSIONS,
    canon,
    POSTAL_MARK_CONFUSIONS,
    digits_only,
    has_cjk,
    is_all_kana,
    kana_to_romaji,
    normalize_hyphens,
    normalize_line,
    prefix_overlap,
    romaji_key,
    to_halfwidth,
)
from card.types import CardFields, Field, OcrLine

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)
BARE_DOMAIN_RE = re.compile(r"^[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+\.[A-Za-z]{2,}$")
# 〒 が別の字に化けて数字とくっつくことがあるため、直前の文字は後段で個別に見る。
POSTAL_RE = re.compile(r"(\d{3})[\-ー‐−](\d{4})(?![\d\-])")
# 電話らしい並び: 先頭に + が付くこともある。区切りは半角ハイフン/空白/括弧。
PHONE_RE = re.compile(r"\+?\d[\d\-()\s]{7,}\d")
# "@" が別の字に化けたメールを復元するための部品（下の _recover_email を参照）
LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._%+\-]*$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")

# 英文氏名（"Alex Morgan" / "ALEX MORGAN"）
EN_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2}$")
EN_NAME_UPPER_RE = re.compile(r"^[A-Z][A-Z'\-]+(?:\s+[A-Z][A-Z'\-]+){1,2}$")
# 和文氏名（姓名の間の空白はあってもなくてもよい）
JA_NAME_RE = re.compile(r"^[一-鿿぀-ヿ]{1,5}[\s　]?[一-鿿぀-ヿ]{1,5}$")
# 「漢字のかたまり → ひらがな → 漢字のかたまり」は氏名ではなく語句。
# 実機で名刺の惹句「難しいほど面白い」が氏名として採られ、本当の氏名（磯野敏寛）に
# 競り勝った。JA_NAME_RE は 2〜10 文字の和文なら何でも通すので、ここで落とす。
# 氏名にもひらがなは出るが（小野ゆかり・佐々木みゆき）、それは**末尾のひと続き**で
# あって、漢字を挟み込む形にはならない。
JA_PHRASE_RE = re.compile(r"[一-鿿][ぁ-ゖ]+[一-鿿]")


@dataclass
class Item:
    """抽出の作業単位。OcrLine に正規化済みテキストと「使用済み」の印を足したもの。"""
    idx: int
    raw: str
    text: str
    conf: float
    height: float
    cx: float
    cy: float
    used_by: set[str] = dc_field(default_factory=set)

    @property
    def free(self) -> bool:
        return not self.used_by


def _items(lines: list[OcrLine]) -> list[Item]:
    out = []
    for line in lines:
        text = normalize_line(line.text)
        if not text:
            continue
        cx, cy = line.center
        out.append(Item(idx=line.order, raw=line.text, text=text, conf=line.conf,
                        height=line.height, cx=cx, cy=cy))
    return out


def _label_of(chunk: str) -> str | None:
    """文字列の中から電話番号の種別ラベルを探す。最後に現れたものを採る。"""
    if not chunk:
        return None
    best: tuple[int, str] | None = None
    for kind, word, pos in _find_labels(chunk):
        if best is None or pos > best[0]:
            best = (pos, kind)
    return best[1] if best else None


def _find_labels(text: str) -> list[tuple[str, str, int]]:
    """行の中のラベルを (種別, 表記, 開始位置) で全部返す。位置順。

    OCR の 0/O 取り違えを吸収するため、大文字化して 0 を O に寄せた文字列で探す。
    置き換えは 1 文字→1 文字なので、見つかった位置は元の文字列にそのまま使える。
    """
    probe = to_halfwidth(text).upper().replace("0", "O")
    found: list[tuple[str, str, int]] = []
    taken: list[tuple[int, int]] = []
    for kind, word in dicts.phone_labels():     # 長い表記から順に見る
        w = to_halfwidth(word).upper().replace("0", "O")
        start = 0
        while True:
            pos = probe.find(w, start)
            if pos < 0:
                break
            start = pos + 1
            if any(a <= pos < b for a, b in taken):   # 長いラベルの一部なら飛ばす
                continue
            taken.append((pos, pos + len(w)))
            found.append((kind, word, pos))
    found.sort(key=lambda t: t[2])
    return found


def _fix_number_tokens(text: str) -> str:
    """「ほぼ数字」の塊の中だけ、英字を数字へ寄せる。

    ラベル（TEL / FAX / Mobile）を巻き込まないよう、塊ごとに数字の割合を見る。
    ラベルは呼び出し側で切り離してあるので、ここに残っているのは番号本体に近い。
    """
    out = []
    for token in re.split(r"(\s+)", text):
        digits = sum(1 for ch in token if ch.isdigit())
        letters = sum(1 for ch in token if ch.isalpha())
        if digits >= 5 and digits >= letters:
            out.append("".join(DIGIT_CONFUSIONS.get(ch, ch) for ch in token))
        else:
            out.append(token)
    return "".join(out)


def _normalize_phone_digits(raw: str) -> str | None:
    """電話番号として妥当なら、国内表記の数字列を返す。妥当でなければ None。"""
    d = digits_only(raw)
    if d.startswith("81") and 11 <= len(d) <= 12:
        d = "0" + d[2:]
    if not d.startswith("0"):
        return None
    if len(d) not in (10, 11):
        return None
    return d


def _format_phone(raw: str, digits: str) -> str:
    """名刺に書かれている区切りを尊重しつつ、記号だけ半角に揃えて返す。"""
    cleaned = normalize_hyphens(to_halfwidth(raw)).strip()
    # "+81-3-1234-5678" は国内表記 "03-1234-5678"。市外局番の桁数は地域で違うので
    # 数字から組み立て直さず、国番号だけを 0 に置き換えて印字どおりの区切りを残す。
    cleaned = re.sub(r"^\+?81[-\s]?", "0", cleaned)
    cleaned = re.sub(r"[()]", "-", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    # 記号を除いた数字が一致しないなら、素直に数字だけ返す（勝手に整形しない）
    if digits_only(cleaned) != digits:
        return digits
    return cleaned


# ── 連絡先 ────────────────────────────────────────────────────────────────────

def _extract_email(items: list[Item]) -> Field:
    for it in items:
        m = EMAIL_RE.search(to_halfwidth(it.text))
        if m:
            it.used_by.add("email")
            return Field(value=m.group(0), confidence=min(0.99, 0.97 * it.conf),
                         source_line=it.idx)

    # "@" が別の字に化けた形からの復元。日本語の認識モデルには文字セットに "@" が
    # 無く、メールアドレスを原理的に出力できない端末があるため。
    for it in items:
        value = _recover_email(to_halfwidth(it.text).strip())
        if value:
            it.used_by.add("email")
            return Field(value=value, confidence=min(0.70, 0.62 * it.conf), source_line=it.idx)

    return Field()


def _recover_email(token: str) -> str | None:
    """"@" が 1 文字だけ別の字に化けたメールアドレスを元に戻す。

    復元してよいのは「そこが "@" 以外ではあり得ない」と言い切れる場合だけ:
      - 空白を含まない 1 トークンで、CJK を含まない
      - ドメインにもローカル部にも使えない文字（大文字や記号）がちょうど 1 つある
      - その文字を挟んで左がローカル部、右がドメインとして成立する
    小文字の英字に化けた場合（"...yamadagexample.jp"）は位置を特定できないので
    復元しない。読めなかったものを勝手に作るより、空欄で返して手入力してもらう。
    """
    if not token or " " in token or has_cjk(token) or "@" in token:
        return None
    if "." not in token:            # ドメインが無いものは相手にしない
        return None

    # ローカル部にもドメインにも現れない文字＝ "@" だったはずの場所
    odd = [i for i, ch in enumerate(token)
           if not (ch.islower() and ch.isascii()) and not ch.isdigit() and ch not in "._-+%"]
    if len(odd) != 1:
        return None
    i = odd[0]
    left, right = token[:i], token[i + 1:]
    if not LOCAL_PART_RE.match(left) or not DOMAIN_RE.match(right):
        return None
    return f"{left}@{right}"


def _extract_website(items: list[Item]) -> Field:
    for it in items:
        m = URL_RE.search(to_halfwidth(it.text))
        if m:
            url = m.group(0).rstrip(".,;")
            if "@" in url:                 # メール行を URL と取り違えない
                continue
            it.used_by.add("website")
            return Field(value=url, confidence=min(0.98, 0.95 * it.conf), source_line=it.idx)

    # www も http も無い裸のドメインだけが書かれている名刺がある。
    # 行全体がドメイン 1 個のときに限り採用する（誤検出を避けるため信頼度は下げる）。
    for it in items:
        if "email" in it.used_by:
            continue
        token = to_halfwidth(it.text).strip()
        if BARE_DOMAIN_RE.match(token):
            it.used_by.add("website")
            return Field(value=token, confidence=min(0.80, 0.78 * it.conf), source_line=it.idx)
    return Field()


def _extract_phones(items: list[Item]) -> dict[str, Field]:
    """TEL / 携帯 / FAX を分けて返す。1 行に複数あっても直前のラベルで振り分ける。

    先にラベルの位置で行を区切り、そのあとで区間ごとに数字の取り違えを直す。
    逆順にすると "TEL03-1234-5678FAX..." のようにラベルと番号が地続きの行で、
    ラベルの英字まで数字に化けて種別が分からなくなる。
    """
    found: dict[str, Field] = {}
    for it in items:
        if {"email", "website"} & it.used_by:
            continue
        work = normalize_hyphens(to_halfwidth(it.text))
        for kind_hint, label, body in _phone_segments(work):
            fixed = _fix_number_tokens(body)
            for m in PHONE_RE.finditer(fixed):
                digits = _normalize_phone_digits(m.group(0))
                if digits is None:
                    continue
                kind = kind_hint
                if kind is None:
                    kind = "mobile" if digits[:3] in ("070", "080", "090") else "phone"
                if kind in found:
                    break          # 同じ種別が複数あれば先に書かれているものを採る
                base = 0.95 if label else 0.82
                if fixed != body:
                    base *= 0.85   # 数字の取り違えを補正した分だけ下げる
                found[kind] = Field(value=_format_phone(m.group(0), digits),
                                    confidence=min(0.99, base * it.conf), source_line=it.idx)
                it.used_by.add("phone")
                break              # 1 区間につき 1 番号
    return found


def _phone_segments(text: str) -> list[tuple[str | None, str, str]]:
    """行を「ラベル → その後ろの本文」の区間に割る。

    ラベルが 1 つも無ければ (None, "", 行全体) を 1 区間として返す。
    """
    labels = _find_labels(text)
    if not labels:
        return [(None, "", text)]
    segments: list[tuple[str | None, str, str]] = []
    head = text[: labels[0][2]]
    if head.strip():
        segments.append((None, "", head))
    for i, (kind, word, pos) in enumerate(labels):
        start = pos + len(word)
        end = labels[i + 1][2] if i + 1 < len(labels) else len(text)
        segments.append((kind, word, text[start:end]))
    return segments


def _extract_postal_address(items: list[Item]) -> tuple[Field, Field]:
    prefectures = dicts.prefectures()
    keywords = dicts.address_keywords()
    postal = Field()
    address = Field()

    for it in items:
        if {"email", "website", "phone"} & it.used_by:
            continue
        work = to_halfwidth(it.text)
        m = POSTAL_RE.search(work)
        pref_pos = -1
        pref_hit = ""
        for p in prefectures:
            pos = work.find(p)
            if pos >= 0 and (pref_pos < 0 or pos < pref_pos):
                pref_pos, pref_hit = pos, p

        if m and postal.value is None:
            before = work[max(0, m.start() - 2):m.start()]
            # 〒 は認識モデルの文字セットに無いことがあり別の字に化ける（"テ" や "1" など）。
            # 化けた 1 文字が数字だと郵便番号とくっついて見えるので、
            #   ・〒らしき字が直前にある
            #   ・行頭（または行頭の 1 文字だけを挟む）で、同じ行に都道府県がある
            # のいずれかを満たすときだけ郵便番号とみなす。
            plausible = (
                any(ch in POSTAL_MARK_CONFUSIONS for ch in before)
                or m.start() == 0
                or (m.start() <= 1 and pref_pos >= 0)
                or (pref_pos >= 0 and not work[m.start() - 1].isdigit())
            )
            if plausible:
                postal = Field(value=f"{m.group(1)}-{m.group(2)}",
                               confidence=min(0.97, 0.93 * it.conf), source_line=it.idx)
                it.used_by.add("postal")

        if pref_pos >= 0 and address.value is None:
            value = work[pref_pos:].strip()
            if len(value) >= len(pref_hit) + 2:
                address = Field(value=value, confidence=min(0.95, 0.90 * it.conf),
                                source_line=it.idx)
                it.used_by.add("address")
        elif m and address.value is None:
            rest = work[m.end():].strip(" ,")
            if len(rest) >= 4 and any(k in rest for k in keywords):
                address = Field(value=rest, confidence=min(0.85, 0.75 * it.conf),
                                source_line=it.idx)
                it.used_by.add("address")

    if address.value is None:
        # 英文住所。数字で始まり、カンマを含み、連絡先として使われていない行。
        for it in items:
            if it.used_by or has_cjk(it.text):
                continue
            t = it.text.strip()
            if re.match(r"^\d+\s+\S", t) and "," in t and len(t) >= 10:
                address = Field(value=t, confidence=min(0.75, 0.70 * it.conf),
                                source_line=it.idx)
                it.used_by.add("address")
                break
    return postal, address


# ── 会社名 ────────────────────────────────────────────────────────────────────

_en_suffix_cache: tuple[tuple[str, ...], list[tuple[str, "re.Pattern[str]"]]] | None = None


def _en_suffix_patterns() -> list[tuple[str, "re.Pattern[str]"]]:
    """英文の法人種別を「独立した語として」探すための正規表現を組む。

    単純な部分一致にすると、"Since 1998" や "Province" の中の "inc" に当たってしまい、
    名刺の英字タグラインを会社名として高い信頼度で確定してしまう。前後が英字でない
    ことを条件にする。語中の空白は詰められていることがある（"Co.,Ltd"）ので緩める。
    """
    global _en_suffix_cache
    words = tuple(dicts.company_suffixes_en())
    if _en_suffix_cache is not None and _en_suffix_cache[0] == words:
        return _en_suffix_cache[1]

    patterns: list[tuple[str, re.Pattern[str]]] = []
    for word in words:
        body = r"\s*".join(re.escape(part) for part in word.split())
        patterns.append((word, re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.I)))
    _en_suffix_cache = (words, patterns)
    return patterns


def _email_domain_key(email: str | None) -> str:
    """メールドメインの先頭ラベルを比較用キーにする（example.co.jp → example）。"""
    if not email or "@" not in email:
        return ""
    domain = email.split("@", 1)[1]
    labels = [x for x in domain.split(".") if x]
    if not labels:
        return ""
    # 会社を表すのは普通いちばん左のラベル
    return romaji_key(labels[0])


def _company_conf(raw: float, text: str, domain_key: str) -> float:
    """会社名の確からしさ。**裏付けが無ければ「そのまま入れてよい」帯へ上げない。**

    法人格（株式会社 / Inc.）が一致したという事実は「この行は社名だ」の証拠であって
    「社名の文字が正しく読めた」証拠ではない。実機では社名本体の漢字 1 文字を
    読み違えた「株式会社暖野木工所」が 0.857 で通り、受付フォームへ無警告で
    入った（正しくは磯野木工所）。氏名側は姓辞書・メールとの一致・役職の隣といった
    裏付けが 1 つも無ければ要確認の帯を越えない作りなので、そちらへ揃える。

    裏付けはメール／URL のドメインとの一致で見る。取れる場合は上限を外す。
    """
    ok = float(settings.get("confidence.ok"))
    if raw < ok:
        return raw
    if domain_key:
        key = kana_to_romaji(text) or romaji_key(text)
        if key and prefix_overlap(key, domain_key) >= 4:
            return raw                      # ドメインが社名本体を裏付けた
    # 裏付け無し。値は返すが「ご確認ください」の帯に留める。
    return round(min(raw, ok - 0.01), 3)


def _extract_company_strong(items: list[Item], email: str | None,
                            website: str | None) -> Field:
    """法人格（株式会社 / Inc. など）を手掛かりに会社名を決める。確実な方。"""
    jp = dicts.company_suffixes()
    en = _en_suffix_patterns()
    domain_key = _email_domain_key(email) or _website_domain_key(website)

    for it in items:
        if {"email", "website", "phone", "postal", "address"} & it.used_by:
            continue
        text = it.text
        key = canon(text)
        if any(canon(s) in key for s in jp):
            it.used_by.add("company")
            return Field(value=text, source_line=it.idx,
                         confidence=_company_conf(min(0.98, 0.95 * it.conf), text, domain_key))

    for it in items:
        if {"email", "website", "phone", "postal", "address"} & it.used_by:
            continue
        if any(pattern.search(it.text) for _word, pattern in en):
            it.used_by.add("company")
            return Field(value=it.text, source_line=it.idx,
                         confidence=_company_conf(min(0.95, 0.90 * it.conf), it.text, domain_key))

    return Field()


def _website_domain_key(website: str | None) -> str:
    """URL から比較用のキーを作る（www.example.co.jp/ → example）。

    例に scheme を書かないのは、「card/ に外部 URL を書かない」ことを見張っている
    テスト(test_ソースに外部URLが書かれていない)に引っかかるため。あれは OCR API や
    CDN を呼ぶコードが紛れ込むのを防ぐ見張りで、例示でも通してしまうと意味が薄れる。
    """
    if not website:
        return ""
    s = re.sub(r"^https?://", "", website.strip(), flags=re.I)
    s = s.split("/")[0]
    labels = [x for x in s.split(".") if x and x.lower() != "www"]
    return romaji_key(labels[0]) if labels else ""


def _extract_company_fallback(items: list[Item], email: str | None, max_h: float) -> Field:
    """法人格が省略されている名刺向け。文字サイズ・位置・メールドメインとの一致で選ぶ。

    氏名・部署・役職・連絡先を先に確定させてから呼ぶこと。そうしないと、社名が
    読み取れなかった名刺で氏名の行を会社名として拾ってしまう。
    """
    domain_key = _email_domain_key(email)
    best: tuple[float, Item] | None = None
    for it in items:
        if it.used_by or not it.text:
            continue
        if re.search(r"\d{3,}", it.text):
            continue
        # 氏名らしい行はメールドメインと強く一致しない限り会社名にしない
        name_like = _name_shape_score(it.text) > 0.0
        size = (it.height / max_h) if max_h > 0 else 0.0
        score = 0.35 * size
        if it.idx <= 1:                       # 名刺の先頭付近に会社名がある作りが多い
            score += 0.25
        if domain_key:
            key = kana_to_romaji(it.text) or romaji_key(it.text)
            overlap = prefix_overlap(key, domain_key)
            if overlap >= 4:
                score += min(0.35, 0.07 * overlap)
                name_like = False
        if name_like:
            score -= 0.30
        if best is None or score > best[0]:
            best = (score, it)

    if best is None or best[0] < 0.30:
        return Field()
    score, it = best
    it.used_by.add("company")
    return Field(value=it.text, confidence=min(0.80, score * it.conf), source_line=it.idx)


# ── 部署 / 役職 ───────────────────────────────────────────────────────────────

def _looks_like_department(text: str) -> bool:
    if not text:
        return False
    key = canon(text)
    if any(canon(d) == key for d in dicts.departments()):
        return True
    for suffix in dicts.department_suffixes():
        sk = canon(suffix)
        if sk and key.endswith(sk) and len(key) > len(sk):
            return True
    return False


def _find_dict_term(text: str, terms: list[str]) -> tuple[int, int, str] | None:
    """辞書の語を行中から探す。まず素のまま、見つからなければ canon 同士で探す。

    戻り値は (開始, 終了, 表示に使う語)。canon 経由で見つかった場合は辞書側の表記を
    返す（OCR が "マネージヤー" と読んでも画面には "マネージャー" と出す）。
    canon は空白や記号を落とすので、素の文字列上の位置は近似でしか求められない。
    そのため終了位置は「その語の canon 長ぶん」を素の文字列側で数え直している。
    """
    for term in terms:
        pos = text.find(term)
        if pos >= 0:
            return pos, pos + len(term), text[pos:pos + len(term)]

    key = canon(text)
    for term in terms:
        tk = canon(term)
        if not tk:
            continue
        pos = key.find(tk)
        if pos < 0:
            continue
        start = _canon_index_to_raw(text, pos)
        end = _canon_index_to_raw(text, pos + len(tk))
        return start, end, term
    return None


def _canon_index_to_raw(text: str, canon_index: int) -> int:
    """canon 後の文字位置を、元の文字列上の位置へ戻す。"""
    seen = 0
    for i, ch in enumerate(text):
        if seen >= canon_index:
            return i
        if canon(ch):
            seen += 1
    return len(text)


def _extract_department_title(items: list[Item]) -> tuple[Field, Field]:
    department = Field()
    title = Field()
    titles = dicts.titles()

    for it in items:
        if it.used_by:
            continue
        text = it.text

        hit = _find_dict_term(text, titles)
        if hit is None:
            continue

        start, end, word = hit
        rest = (text[:start] + text[end:]).strip(" ・/|-")
        exact = text[start:end] == word
        if title.value is None:
            title = Field(value=word,
                          confidence=min(0.96, (0.92 if exact else 0.78) * it.conf),
                          source_line=it.idx)
        if rest and department.value is None and _looks_like_department(rest):
            department = Field(value=rest,
                               confidence=min(0.94, (0.90 if exact else 0.80) * it.conf),
                               source_line=it.idx)
        it.used_by.add("title")

    if department.value is None:
        for it in items:
            if it.used_by:
                continue
            if _looks_like_department(it.text):
                department = Field(value=it.text, confidence=min(0.92, 0.88 * it.conf),
                                   source_line=it.idx)
                it.used_by.add("department")
                break
    return department, title


# ── 氏名 ──────────────────────────────────────────────────────────────────────

def _romaji_matches_local(text: str, local_raw: str, local_key: str) -> bool:
    """ローマ字表記の氏名が、メールアドレスのローカル部と符合するか。

    "alex.morgan" ↔ "Alex Morgan" のような全体一致だけでなく、
    "k.sato" ↔ "KENICHI SATO" のように片方が頭文字だけの場合も拾えるよう、
    ローカル部を区切り文字で分けて姓名のトークンと突き合わせる。
    """
    tokens = [t for t in re.split(r"[\s　]+", text.strip()) if t]
    keys = [romaji_key(t) for t in tokens if romaji_key(t)]
    if not keys:
        return False

    joined = "".join(keys)
    if len(joined) >= 6 and local_key and (joined in local_key or local_key in joined):
        return True

    parts = [p for p in re.split(r"[._\-]+", local_raw) if p]
    if len(parts) < 2:
        return False
    # 姓（どれか 1 トークン）が一致していることを必須にし、名は頭文字だけでも可とする
    if not any(len(k) >= 3 and k in parts for k in keys):
        return False
    initials = {k[0] for k in keys if k}
    return any(len(p) == 1 and p in initials for p in parts) or len(parts) >= 2


def _looks_like_furigana(item: Item, items: list[Item]) -> bool:
    """このかなの行が、すぐ隣の漢字の氏名に振られた読みか。

    ふりがなは氏名のすぐ上（まれに下）に、氏名より小さく印字される。逆に言うと、
    隣に「自分より大きい、漢字を含む氏名らしい行」が無ければ、それは読みではなく
    **氏名そのもの**である可能性が高い。カタカナで氏名を書いた名刺（外国籍の方の
    名刺で珍しくない）が、かなだけを理由に候補から外れて氏名が空欄になっていた。
    """
    for other in items:
        if other is item or abs(other.idx - item.idx) > 1:
            continue
        if is_all_kana(other.text) or not has_cjk(other.text):
            continue                  # 漢字を含む行だけが「読みを振られる側」
        if _name_shape_score(other.text) <= 0.0:
            continue
        if other.height > item.height * 1.15:
            return True
    return False


def _name_shape_score(text: str) -> float:
    if JA_PHRASE_RE.search(text.replace(" ", "").replace("　", "")):
        return 0.0                      # 惹句・キャッチコピーの類（氏名ではない）
    if JA_NAME_RE.match(text) and 2 <= len(text.replace(" ", "")) <= 8:
        return 1.0
    if EN_NAME_RE.match(text) or EN_NAME_UPPER_RE.match(text):
        return 0.9
    return 0.0


def _surname_reading(text: str) -> str:
    """行頭が姓辞書にあれば、その読みのローマ字を返す。"""
    table = dicts.surnames()
    head = text.replace(" ", "")
    for length in (3, 2, 1):
        key = head[:length]
        if key in table:
            return kana_to_romaji(table[key])
    return ""


def _extract_name(
    items: list[Item], email: str | None, max_h: float, card_h: float,
    has_contact: bool = False,
) -> Field:
    # ローカル部は「区切りを残した形」と「英字だけの形」の両方を使う。
    # 前者は "k.sato" を ["k", "sato"] に割るのに要る（頭文字＋姓の突き合わせ）。
    local_raw, local = "", ""
    if email and "@" in email:
        local_raw = email.split("@", 1)[0].lower()
        local = romaji_key(local_raw)

    # 会社名・連絡先・役職を先に確定させたあと、残っている行のうちいちばん大きい
    # ものは氏名であることが多い（名刺は会社名の次に氏名を大きく刷る）。姓の辞書に
    # 載らない氏名では、これが大きさに関する唯一の手がかりになる。画面全体の最大
    # （＝たいてい会社名）と比べる size だけでは、ロゴが大きい名刺で氏名が沈む。
    free_max_h = max((i.height for i in items if not i.used_by), default=0.0)

    candidates: list[tuple[float, Item]] = []
    for it in items:
        if it.used_by:
            continue
        text = it.text
        if not text or re.search(r"\d", text):
            continue
        shape = _name_shape_score(text)
        if shape <= 0.0:
            continue
        if is_all_kana(text):
            if _looks_like_furigana(it, items):
                continue                  # 隣の漢字の氏名に振られた読み
            # かなだけの氏名は根拠としては弱いので、漢字・ローマ字の候補に
            # 競り負けるようにしておく（他に候補が無ければこれが採られる）。
            shape = min(shape, 0.8)

        size = (it.height / max_h) if max_h > 0 else 0.0
        # 「大きい文字で、氏名らしい形」だけでは 0.62 までしか行かないように配分する。
        # 姓の辞書・近くのローマ字・メールアドレスとの一致といった裏付けが 1 つも
        # 無ければ、要確認(confidence.warn)に届かず画面上で赤く出る。名刺でない紙を
        # 撮ったときに、たまたま大きい文字を氏名として確定してしまうのを防ぐため。
        score = 0.38 * size + 0.17 * shape

        # 名刺の上端すぐは会社名、下端は連絡先。氏名は中央寄りにあることが多い。
        if card_h > 0:
            rel = it.cy / card_h
            if 0.15 <= rel <= 0.70:
                score += 0.07

        # 同じ文字列が何度も出てくる紙は名刺ではない（帳票・案内文など）。
        if sum(1 for other in items if other.text == text) > 1:
            score -= 0.25

        # 大きさの手がかりは「その紙が名刺らしい」ときだけ使う。連絡先が 1 つも
        # 取れていない紙（A4 の書類・案内文）では、いちばん大きい文字は見出しで
        # あって氏名ではない。ここを無条件に加点すると書類の見出しを氏名として
        # 確定してしまう（実際にテストで落ちた）。
        if has_contact and free_max_h > 0 and it.height >= free_max_h * 0.98:
            score += 0.10

        # 名刺は「役職／部署 → 氏名」の順に並べるのが普通。姓の辞書に載らない氏名
        # （カタカナ書き・外国語表記）では、この並びが数少ない裏付けになる。
        if any(abs(other.idx - it.idx) <= 1
               and ("title" in other.used_by or "department" in other.used_by)
               for other in items):
            score += 0.10

        reading = _surname_reading(text)
        if reading:
            score += 0.12
            if local and reading in local:
                score += 0.18
        elif is_all_kana(text) and local:
            # かな書きの氏名は、それ自体が読み。漢字の姓を辞書で読みに直して
            # メールと突き合わせるのと同じことを、辞書無しでできる。
            # ローカル部は姓だけ・名だけのことが多い（レミンハイ → hai@）ので、
            # どちらが相手を含んでいても一致と見る。2 文字以下の一致は偶然。
            kana_reading = kana_to_romaji(text.replace(" ", ""))
            if len(local) >= 3 and (local in kana_reading or kana_reading in local):
                score += 0.18

        if local:
            # 行そのものがローマ字表記なら、メールのローカル部と直接比べる
            if not has_cjk(text) and _romaji_matches_local(text, local_raw, local):
                score += 0.16
            else:
                # 近くのローマ字表記（"YUKO NAKAMURA" / "KENICHI SATO"）と比べる
                for other in items:
                    if other is it or abs(other.idx - it.idx) > 2:
                        continue
                    if has_cjk(other.text) or other.used_by:
                        continue
                    if _romaji_matches_local(other.text, local_raw, local):
                        score += 0.14
                        break

        candidates.append((score, it))

    if not candidates:
        return Field()

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    top_score, top = candidates[0]
    confidence = min(0.97, top_score * top.conf)
    threshold = float(settings.get("extraction.name_min_conf"))
    others = [it.text for _s, it in candidates[1:4]]

    if confidence < threshold:
        # 確定できないときは空欄にして候補だけ返す（勝手に決めない）
        return Field(value=None, confidence=round(confidence, 3),
                     candidates=[top.text, *others], source_line=top.idx)

    top.used_by.add("name")
    return Field(value=top.text, confidence=confidence, candidates=others,
                 source_line=top.idx)


def _extract_name_kana(items: list[Item], name_line: int | None, max_h: float) -> Field:
    """氏名の近くにある、かなだけの行を読み仮名として拾う。無ければ空のまま。

    ふりがなは氏名より小さく印字されるので、文字の大きさでも絞る。これが無いと
    カタカナ主体の社名や商品名を読み仮名として拾ってしまう。
    """
    if name_line is None:
        return Field()
    name_item = next((i for i in items if i.idx == name_line), None)
    limit = (name_item.height * 0.8) if name_item else (max_h * 0.6)
    best: Item | None = None
    for it in items:
        if it.used_by or not is_all_kana(it.text):
            continue
        if abs(it.idx - name_line) > 2:
            continue
        body = it.text.replace(" ", "")
        if not (2 <= len(body) <= 12):
            continue
        if it.height > limit:
            continue
        if best is None or abs(it.idx - name_line) < abs(best.idx - name_line):
            best = it
    if best is None:
        return Field()
    best.used_by.add("name_kana")
    return Field(value=best.text, confidence=min(0.90, 0.86 * best.conf), source_line=best.idx)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def extract(lines: list[OcrLine], card_size: tuple[int, int] | None = None) -> CardFields:
    """OCR 行から名刺の項目を組み立てる。

    card_size は補正後の名刺画像の (幅, 高さ)。位置による加点に使う。
    未指定なら行の座標から推定する。
    """
    items = _items(lines)
    fields = CardFields()
    if not items:
        return fields

    max_h = max(it.height for it in items)
    card_h = float(card_size[1]) if card_size else max(it.cy for it in items) * 1.1

    fields.email = _extract_email(items)
    fields.website = _extract_website(items)
    phones = _extract_phones(items)
    fields.phone = phones.get("phone", Field())
    fields.mobile = phones.get("mobile", Field())
    fields.fax = phones.get("fax", Field())
    fields.postal_code, fields.address = _extract_postal_address(items)

    # 会社名は「法人格が書いてある行」を先に押さえる（氏名より確実なため）。
    # 法人格が無い名刺向けの推測は、氏名・部署・役職を確定させたあとに回す。
    fields.company_name = _extract_company_strong(
        items, fields.email.value, fields.website.value)
    fields.department, fields.title = _extract_department_title(items)
    # 連絡先が 1 つでも取れていれば「名刺らしい紙」として扱う（氏名の手がかりの強さを変える）
    has_contact = any(f.value for f in
                      (fields.email, fields.phone, fields.mobile, fields.fax))
    fields.person_name = _extract_name(items, fields.email.value, max_h, card_h,
                                       has_contact)
    if not fields.company_name.value:
        fields.company_name = _extract_company_fallback(items, fields.email.value, max_h)
    # 読み仮名は最後。カタカナ主体の社名（「あおぞらクリエイティブ」など）を
    # ふりがなとして先に消費してしまわないよう、会社名を確定させてから拾う。
    fields.person_name_kana = _extract_name_kana(
        items, fields.person_name.source_line, max_h
    )
    # 氏名そのものがかな書きなら、それが読みでもある。受付の「ふりがな」を
    # 利用者に打ち直させる必要はない（違っていれば確認画面で直せる）。
    if (fields.person_name.value and not fields.person_name_kana.value
            and is_all_kana(fields.person_name.value)):
        fields.person_name_kana = Field(
            value=fields.person_name.value,
            confidence=round(fields.person_name.confidence * 0.9, 3),
            source_line=fields.person_name.source_line,
        )

    return fields


def overall_confidence(fields: CardFields) -> float:
    """名刺 1 枚としての読み取り精度 0-1。確認画面に「全体の読み取り精度」として出る。

    「読めた項目の平均」にはしない。それだと連絡先しか読めていない名刺が、
    全項目そろった名刺より高く出てしまう。受付に必要な会社名・氏名は
    欠けていること自体を減点として扱い、その他の項目は取れた分だけ加点する。
    """
    core = {"company_name": 1.0, "person_name": 1.0}
    optional = {
        "email": 1.5, "phone": 1.0, "department": 1.0, "title": 1.0,
        "mobile": 0.5, "address": 0.5, "website": 0.4,
        "fax": 0.3, "postal_code": 0.3, "person_name_kana": 0.3,
    }

    core_total = sum(
        w * fields.get(name).confidence
        for name, w in core.items()
        if fields.get(name).value
    )
    core_score = core_total / sum(core.values())

    opt_weight = sum(w for name, w in optional.items() if fields.get(name).value)
    opt_score = 0.0
    if opt_weight > 0:
        opt_score = sum(
            w * fields.get(name).confidence
            for name, w in optional.items()
            if fields.get(name).value
        ) / opt_weight

    return round(0.70 * core_score + 0.30 * opt_score, 3)
