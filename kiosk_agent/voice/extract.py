"""一文の名乗りから受付項目を取り出す。

「磯野木工所の荒木と申します。本日、服部様と打ち合わせのお約束で参りました」のような
**一続きの発話**から、会社名・氏名・訪問先・用件・約束の有無を取り出す。

**ここに LLM は使わない。** 小型 LLM(Qwen3-1.7B)と比べて測ったところ、規則のほうが
良かった(肉声10件・担当者の照合 8/10 → 9/10、誤照合 1 → 0、6秒 → 0秒)。理由は単純で、
LLM にやらせていた「発話中のどの語が担当者か」という判断は、**担当者が名簿にいる人
しかありえない**以上、発話全体を名簿と突き合わせれば済むため。語の位置も使えるので、
「山田運送の田中です」の田中を担当者にしてしまう類の誤りを構造的に避けられる
(LLM 版はこれを通していた = 別の人へ通知が飛ぶ)。

文字起こしは固有名詞を毎回違う字で返す(服部 → はっとりさま / ハットリ様 / ハッドリ /
アットリ様)。**照合は文字列ではなく読みで行う。**

会社名と氏名は文字起こしの精度がそのまま出るので(肉声で 3〜4割)、**画面で直せることが
前提**。ここで返すのは下書きであって、確定値ではない(§4「音声だけで受付を確定しない」)。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import settings, textnorm

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Staff:
    """照合に使う担当者1人ぶん。reading が無い人は読みでの照合ができない。

    aliases は社内での呼ばれ方・旧姓・通称。読みと同じ扱いで照合に使う。
    """
    name: str
    reading: str = ""
    department: str = ""
    aliases: tuple[str, ...] = ()

    def readings(self) -> tuple[str, ...]:
        """照合に使える読みを全部。登録が無ければ空(漢字一致でしか当たらない)。"""
        return tuple(r for r in (self.reading, *self.aliases) if r)


@dataclass
class Extraction:
    """一文から取り出した受付項目。**確定値ではなく画面に出す下書き。**"""
    visitor_company: str | None = None
    visitor_name: str | None = None
    host_name_spoken: str | None = None
    host_candidates: list[str] = field(default_factory=list)
    purpose: str | None = None
    has_appointment: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "visitor_company": self.visitor_company,
            "visitor_name": self.visitor_name,
            "host_name_spoken": self.host_name_spoken,
            "host_candidates": list(self.host_candidates),
            "purpose": self.purpose,
            "has_appointment": self.has_appointment,
        }


# ── 用件と約束の有無 ──────────────────────────────────────────────────────────
#
# 言い回しが限られるので規則で取る。文字起こしが崩れても効くのが利点で、実測でも
# 用件 7/10・約束 10/10 と、固有名詞(3〜4/10)よりはるかに安定していた。

PURPOSE_RULES: dict[str, list[str]] = {
    "打ち合わせ": ["打ち合わせ", "打合せ", "打ち合せ", "うち合わせ", "うちあわせ", "ミーティング"],
    "商談": ["商談", "見積", "提案", "営業で"],
    "納品": ["納品", "荷物", "届け", "配達", "配送", "お届け", "宅配"],
    "面接": ["面接", "面談"],
    "採用": ["採用", "面接", "面談"],
    "点検": ["点検", "工事", "修理", "メンテ", "保守"],
    "工事": ["工事", "点検", "修理"],
    "見学": ["見学", "視察"],
    "予約": ["予約", "約束", "アポ"],
}
APPOINTMENT_WORDS = ["約束", "アポ", "予約", "お時間をいただ", "伺う予定"]
# 「アポは無いんですけど」を約束ありにしてはいけない。語の直後を見て打ち消す。
NEGATIONS = ["無い", "ない", "ありません", "無く", "なく", "取ってない", "取っていない", "してない"]


def keywords_for(purpose: str) -> list[str]:
    """設定された用件名から、発話で使われる言い回しを起こす。

    用件名はテナントが自由に決めるので、発話の語と字面が揃わない
    (「お打ち合わせ」と言う人はいない、「採用面接」は「面接」としか言わない)。
    名前そのもの・頭の「お」「ご」を取ったもの・**名前に含まれる既知の語**の
    言い換えを全部見る。
    """
    name = purpose.strip()
    stem = re.sub(r"^[おご]", "", name)
    words = {name, stem}
    for key, variants in PURPOSE_RULES.items():
        if key in stem:
            words.update(variants)
    return [w for w in words if w]


def purpose_of(text: str, purposes: list[str]) -> str | None:
    """用件を決める。当てはまらなければ null(「その他」に寄せない)。

    purposes はテナントごとに設定された選択肢。そこに無い用件は返さない。

    複数当たることがある(「打ち合わせのお約束で参りました」は打ち合わせと予約の
    両方に当たる)。**当たった語が長い方**を採る。長い語のほうが具体的で、
    「ご予約のあるお客様」より「お打ち合わせ」の方が受付として役に立つ。
    """
    best: tuple[int, int, str] | None = None     # (語の長さ, 設定の並び順の逆, 用件名)
    for order, name in enumerate(purposes):
        if not str(name).strip():
            continue
        for word in keywords_for(str(name)):
            if word in text:
                score = (len(word), -order, str(name))
                if best is None or score > best:
                    best = score
    return best[2] if best else None


def appointment_of(text: str) -> bool | None:
    """約束の有無。言っていなければ **false ではなく null**(画面で確認させる)。

    打ち消しを見落とすと逆の意味になる。「アポは無いんですけど服部さんいますか」は
    飛び込みの来訪で、約束ありとして通してはいけない。
    """
    for w in APPOINTMENT_WORDS:
        i = text.find(w)
        if i < 0:
            continue
        if any(neg in text[i + len(w): i + len(w) + 12] for neg in NEGATIONS):
            return False
        return True
    return None


# ── 担当者の照合(読みで行う) ─────────────────────────────────────────────────

def reading_key(text: str) -> str:
    """読み比べ用のキー。敬称を外し、ひらがなへ寄せ、長音・促音の揺れを畳む。

    漢字は読みが分からないので落とす。「張っとり」の「張」のように、文字起こしが
    当てずっぽうで漢字を当てた分を残すと照合の邪魔になる。
    """
    key = textnorm.normalize_reading(textnorm.strip_honorific(str(text).strip()))
    return "".join(ch for ch in key if "ぁ" <= ch <= "ゟ")


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[len(b)]


def match_one(spoken: str, staff: list[Staff], tolerance: int = 1) -> list[Staff]:
    """語ひとつを名簿と突き合わせる。

    文字起こしは同じ人を毎回違う字で返すが、読みに直すと はとり / はどり / あとり と
    なり 1 文字の違いに収まる。**姓だけ言う**のが普通なので名簿の読みの先頭と比べる。

    複数当たるのは正常(同姓が複数いる)。1 人に絞れなくても構わない。絞れないことを
    画面に出して選ばせるのが正しい動きで、ここで勝手に寄せる方が危ない(§4)。
    """
    bare = textnorm.strip_honorific(str(spoken).strip())
    key = reading_key(spoken)
    hit: list[Staff] = []
    for s in staff:
        # 文字起こしが漢字を正しく当てた場合(「田中です」)は、そのまま名簿と突き合う。
        if len(bare) >= 2 and bare in s.name:
            hit.append(s)
            continue
        if len(key) < 2:
            continue
        # 2 文字だけの一致で 1 文字の違いを許すと誰にでも当たってしまう
        # (「はとり」の先頭2文字「はと」が「さとう」に 1 違いで当たる)。
        # 2 文字は完全一致、3 文字以上で 1 文字の違いまで許す。
        for candidate in s.readings():
            full = reading_key(candidate)
            if not full:
                continue
            if any(_distance(key[:n], full[:n]) <= (0 if n < 3 else tolerance)
                   for n in range(2, min(len(key), len(full)) + 1)):
                hit.append(s)
                break
    return hit


def scan_staff(text: str, staff: list[Staff]) -> list[Staff]:
    """発話全体を名簿と突き合わせる。**「どの語が担当者か」を先に決めなくてよい。**

    担当者は名簿にいる人しかありえないので、発話のどこかに名簿の誰かの読みが出て
    いれば、それが訪問先である可能性が高い。語の切り出しを別途行う必要がない。
    """
    found: dict[str, Staff] = {}
    for s in staff:
        for n in range(2, len(s.name) + 1):
            if s.name[:n] in text:
                found[s.name] = s
    reading = reading_key(textnorm.normalize_common(text))
    for i in range(len(reading)):
        for n in (4, 3, 2):
            if i + n > len(reading):
                continue
            for s in match_one(reading[i:i + n], staff):
                found[s.name] = s
    return [s for s in staff if s.name in found]


# ── 名乗り ────────────────────────────────────────────────────────────────────

# 名乗りの締め。ここより前が「会社の氏名」にあたる。
_ANCHORS = ("と申します", "でございます", "と言います", "といいます", "です")
# 「○○から来ました」— 会社だけ名乗る言い方
_FROM_PATTERN = re.compile(r"(?P<company>.{2,20}?)から(?:来ました|参りました|まいりました|伺いました)")
# 名乗りの頭に付く語。文字起こしは句読点を落とすので、ここで外さないと
# 「私磯野木工所」が会社名になる。
_LEAD = re.compile(r"^(?:私|わたくし|わたし|あの|あのー|えー|えーと|あー|すみません|ごめんください)+")
# 締めの後ろにこれが続くなら文の途中。名乗りの区切りとして使わない。
_CONTINUES = re.compile(r"^(?:けど|けれど|が|ので|から|し|よ|ね|か)")
# 直前の文の終わり。文字起こしは句点を出さないので、これで前の文と切り分ける。
# 「服部様との打ち合わせで参りました磯野木工所の荒木です」の名乗りは「ました」より後ろ。
_CLAUSE_ENDS = ("ました", "ます", "でした", "ください", "おります", "ですが")

# 氏名の欄に入ってはいけない語。「採用担当の方にお会いしたいのですが」が
# 「(会社)の(氏名)です」に当たり、氏名が「方にお会いしたいの」になっていた。
_NOT_NAME = re.compile(r"(方|人|者|担当|部署|くださ|したい|します|ください|いたし|おり|ござい|"
                       r"合わせ|約束|荷物|面接|点検|工事|商談|納品)")


def _plausible_name(candidate: str) -> bool:
    """氏名らしいか。姓だけ・姓名で 2〜6 文字に収まるのが普通。"""
    c = candidate.strip()
    return 2 <= len(c) <= 6 and not _NOT_NAME.search(c)


def scan_visitor(text: str) -> tuple[str | None, str | None, tuple[int, int] | None]:
    """名乗りの言い回しから会社名と氏名を切り出し、その範囲も返す。

    範囲を返すのは、担当者を探すときに名乗りの部分を除くため。**名乗りの位置は強い
    証拠**で、そこに出た名前は名簿に同姓がいても来訪者(「山田運送の田中です」)。

    区切り記号には頼らない。文字起こしは読点を出したり出さなかったりするうえ、
    整形で落ちる。代わりに「と申します」「です」という**締めの言い回しを先に見つけ、
    その手前を最後の「の」で会社と氏名に割る**。
    """
    # 締めを手前から順に試す。1 つ目で割れなくても、後ろに本物があることがある。
    spots = sorted((m.start(), m.group()) for a in _ANCHORS
                   for m in re.finditer(re.escape(a), text))
    for at, anchor in spots:
        # 「アポは無いんですけど服部さんいますか」の「です」は名乗りの締めではない。
        # 後ろに接続の助詞が続くものは文の途中なので除く。
        if _CONTINUES.match(text[at + len(anchor):]):
            continue
        head = text[:at]
        # 名乗りは短い。前の文まで遡ると発話全体を名乗りと見なしてしまい、
        # 担当者を探す範囲が無くなる。直前の文の終わりで切る。
        tail_at = max((head.rfind(e) + len(e) for e in _CLAUSE_ENDS if e in head), default=0)
        head = _LEAD.sub("", head[tail_at:])
        start = at - len(head)
        cut = head.rfind("の")
        # 「○○の××」と割ってみて、駄目なら全体を氏名として見る。
        for company, name in ([(head[:cut], head[cut + 1:])] if cut > 0 else []) + [(None, head)]:
            if not _plausible_name(name):
                continue
            if company is not None and not (2 <= len(company.strip()) <= 20):
                company = None
            return (company or None), name.strip(), (start, at + len(anchor))

    m = _FROM_PATTERN.search(text)
    if m:
        company = _LEAD.sub("", m.group("company")).strip()
        if 2 <= len(company) <= 20:
            return company, None, m.span()
    return None, None, None


# ── 名簿の読み ────────────────────────────────────────────────────────────────

def _compact(name: str) -> str:
    """氏名の表記ゆれを潰す。管理画面は「服部 太郎」、読みの登録は「服部太郎」になりがち。"""
    return str(name or "").replace(" ", "").replace("　", "").strip()


def load_readings() -> dict[str, Staff]:
    """端末ローカルの staff_readings.yaml から読み仮名を読む。

    社員マスター(tenants.staff_list)には**読み仮名の欄が無い**ので、読みはここから
    補う。読みを推測してはいけない(§8)ので、ここに無い人は漢字一致でしか当たらない。
    ファイルは実在の社員情報なので git には入れない。

    鍵は氏名から空白を抜いたもの。管理画面側の表記と揃わないことが多いため。
    """
    raw = str(settings.get("staff.readings_path") or "").strip()
    if not raw:
        return {}
    path = settings.resolve_path(raw)
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("[voice] 担当者の読みを読めません: %s", type(e).__name__)
        return {}

    entries = data.get("staff", data) if isinstance(data, dict) else data
    out: dict[str, Staff] = {}
    if isinstance(entries, dict):
        # 「氏名: よみ」だけの簡単な書き方も受ける。
        for name, reading in entries.items():
            if isinstance(reading, str) and _compact(name):
                out[_compact(name)] = Staff(name=str(name).strip(), reading=reading.strip())
    elif isinstance(entries, list):
        for row in entries:
            if not isinstance(row, dict) or not _compact(row.get("name", "")):
                continue
            aliases = row.get("aliases") or []
            out[_compact(row["name"])] = Staff(
                name=str(row["name"]).strip(),
                reading=str(row.get("kana") or row.get("reading") or "").strip(),
                department=str(row.get("department") or "").strip(),
                aliases=tuple(str(a).strip() for a in aliases if str(a).strip()),
            )
    return out


def build_staff(names: list[str]) -> list[Staff]:
    """画面から渡された担当者名に、端末ローカルの読みを合わせる。

    **誰がいるか**の出どころは管理画面の社員マスター(画面が持っている)。読みだけを
    端末側で補う。返す name は**画面から渡された表記のまま**にする。そうしないと
    選んだ担当者がフォームの候補と一致しない。
    """
    book = load_readings()
    out: list[Staff] = []
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        known = book.get(_compact(name))
        out.append(Staff(
            name=name,
            reading=known.reading if known else "",
            department=known.department if known else "",
            aliases=known.aliases if known else (),
        ))
    return out


def readings_count(names: list[str]) -> int:
    """渡された担当者のうち、読みが登録されていて音声で指名できる人数。"""
    return sum(1 for s in build_staff(names) if s.readings())


# ── まとめ ────────────────────────────────────────────────────────────────────

def _outside_visitor(text: str) -> str:
    """名乗りの範囲を除いた部分。担当者はここから探す。"""
    company, name, span = scan_visitor(text)
    return (text[:span[0]] + " " + text[span[1]:]) if span else text


def extract(text: str, staff: list[Staff], purposes: list[str],
            grammar_text: str = "", host_tokens: list[str] | None = None) -> Extraction:
    """一文から受付項目を取り出す。

    順番に意味がある。**先に名乗りを取り、その範囲を除いてから担当者を探す。**
    逆にすると「山田運送の田中です」の田中が担当者として当たってしまう。
    田中・佐藤のような姓では実運用で必ず起きる。

    grammar_text は担当者の語彙だけで decode し直した 2 パス目の文字起こし、
    host_tokens はそのうち信頼できた語(vosk_engine.transcribe_vocabulary)。
    **担当者の候補を足すためだけに使い、会社名・氏名には使わない。** 絞った語彙は
    来訪者の会社名を知らないので、そちらは 1 パス目の方が当たる。
    2 パス目にも同じ「名乗りを除く」処理をかける。除かないと「山田運送の田中です」の
    田中が、今度は信頼度 1.0 付きで担当者に化ける。
    """
    body = textnorm.normalize_common(text or "")
    company, name, span = scan_visitor(body)
    rest = (body[:span[0]] + " " + body[span[1]:]) if span else body
    candidates = scan_staff(rest, staff)

    if grammar_text and host_tokens:
        found = {s.name for s in candidates}
        for s in scan_staff(_outside_visitor(textnorm.normalize_common(grammar_text)), staff):
            if s.name not in found and any(t and t in s.name for t in host_tokens):
                candidates.append(s)
                found.add(s.name)
    return Extraction(
        visitor_company=company or None,
        visitor_name=name or None,
        host_name_spoken=candidates[0].name if len(candidates) == 1 else None,
        host_candidates=[s.name for s in candidates],
        purpose=purpose_of(body, purposes),
        has_appointment=appointment_of(body),
    )
