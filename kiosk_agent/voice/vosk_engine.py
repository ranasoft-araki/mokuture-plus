"""Vosk で画面操作のキーワードを聞き分ける(声で操作する)。

画面ごとに「いま受け付ける言葉」だけの語彙で decode する(Doc/kiosk-voice-touchless.html
段階2)。Vosk は語彙を絞れる(`Gr.fst` を持つモデルに限る)うえ、48MB と小さく
Raspberry Pi のような機械を想定している。

Windows の合成音声で測って分かった性質:

1. **句ではなく語で絞られる。** グラマーに「三 番」と書いても「三」だけが単独で返る
   (無関係な「たなかさんいますか」→「三 いいえ ます」)。句として成立したかは
   こちらで確かめる(_find_phrases)。
2. **同じ読み・近い音の表記を並べると信頼度が割れる。** 「戻る」と「もどる」を両方入れると
   どちらも 0.5 になり、しきい値を越えない。「受け取る」と「受け取り」も割れた。
3. **短い数字は発話頭の雑音([unk])に吸われる。** 語彙を絞ると「にばん」「さんばん」は
   「番」だけが残る(辞書に 1 語である「一番」だけは当たる)。語彙を絞らない通常の認識では
   「二 番」と出るので、番号で選ぶ画面(ロッカー)だけ通常の認識で聞き直す(fallback)。
   ロッカー 7 口の番号で 11/21 → 25/28(聞き直しのしきい値 0.4)。
4. **雑談に紛れたキーワードは信頼度 1.0 で当たる**(「ロッカーの鍵どこだっけ」)。
   しきい値では切れないので、キーワードの後ろに語彙外の発話が続いたら捨てる(embedded)。
5. **数字の語は信頼度が低めに出る。** 実機で「にばん」だけ反応しなかった。合成音声でも
   静かな所で「二」だけ 0.85 にわずかに届かないことが多い(0.80〜0.84。「番」は 1.0)。「に」は 1 拍で
   鼻音から始まる、いちばん弱い数字。数字の語だけ合格ラインを下げる(command.number_min_conf)。
   下げるほど別の数字との取り違えが増えうるので、増え方を測って決めた(defaults.py)。

実測(scripts/voice_command_eval.py・7 画面の語彙・しきい値 0.85):
  画面への操作 222 発話(札のひらがな・「えーと、〜」「〜でお願いします」込み)
    当たり 218・取り違え 0(外れた 4 件はすべて「二番」「三番」)
  無関係な雑談 28 本 × 7 画面   誤爆 31 → 「文の一部」を捨てて 7
    残りは「ちょっと待って」→ 待って(待機を延ばすだけ)と、結果画面の
    「わかりました、完了です」→ 完了 で、どちらも意味どおり

── 英語対応(lang="en") ──────────────────────────────────────────────────────
表示言語をタッチで英語に切り替えた来訪者向け。発話で言語を自動判定する機構は無い
(表示言語に追従するだけ)。モデル・語彙・数字語・同音語は言語ごとに分ける
(settings の `vosk.*` が日本語、`vosk_en.*` が英語。既存の `vosk.*` は変えない
=現場の voice_input.yaml / 環境変数がそのまま効く)。

**小型の英語モデル(vosk-model-small-en-us-0.15 / -zamia-0.5)は不採用**。
`graph/words.txt` に語彙外(OOV)を表す `[unk]` が無く、語彙を絞ると周りの雑談まで
高い信頼度(1.0)で選択肢に化けた(実測:「where did I put the locker key」→
「locker delivery locker cancel」が全語 conf 1.0)。`[unk]` を持つ
vosk-model-en-us-0.22-lgraph(130MB)だけが、埋め込まれた雑談を正しく
「[unk] locker [unk]」のように返した。日本語のモデルはこの `[unk]` を元々持っている。
英語の閾値(min_conf 等)はひとまず日本語と同じ既定値を流用する。実機・実際の声での
実測が済んでいないため(VOICE_COMMAND.md)。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path

from voice import settings
from voice.types import AudioSegment, CommandMatch

log = logging.getLogger(__name__)

ENGINE_NAME = "vosk"
LANGS = ("ja", "en")


class EngineUnavailable(RuntimeError):
    """モデルか vosk パッケージが無い。"""


class EngineFailed(RuntimeError):
    """認識そのものに失敗した。"""


# モデルの読み込みは数秒かかるうえメモリを持つので、一度だけ読んで使い回す(言語ごとに1つ)。
# 言語ごとに別の Lock にしてある。1つの Lock だと、起動時に日英を並行して温める
# (server.py)つもりでも、片方の読み込み(数秒)がもう片方を完全にブロックしてしまう。
_models: dict[str, object] = {}
_model_locks: dict[str, threading.Lock] = {lang: threading.Lock() for lang in LANGS}

# 認識器も使い回す。**毎回作り直すと 3 倍以上遅くなる**(実測: 中央値 4.45秒 → 1.28秒)。
# デコード用のグラフを組み直すのがそれだけ重い。Kaldi の認識器はスレッド安全では
# ないので、ここで直列化する(認識自体も session 側で 1 件ずつに絞っている)。
_rec_lock = threading.Lock()
# 語彙を絞らない認識器(番号の聞き直し用)。言語ごとに1つ。
_free_recs: dict[str, object] = {}
_free_rates: dict[str, int] = {}
# 語彙ごとの認識器。画面を行き来するたびに作り直さない。キーに言語を含める。
_cmd_recs: "OrderedDict[tuple[str, int, str], object]" = OrderedDict()
# 言い回し → 発音辞書の語の並び(辞書に無ければ None)。語彙は画面ごとにほぼ固定なので、
# 20 万語の辞書を読むのは初めて見た言い回しのときだけで済む。キーに言語を含める。
_seg_cache: dict[tuple[str, str], tuple[str, ...] | None] = {}
_seg_warned: set[tuple[str, str]] = set()
_PHRASE_MAX = 16

# 数字の語(上の 5)。合格ラインを command.number_min_conf まで下げる。言語ごと。
_NUMERAL_WORDS: dict[str, frozenset[str]] = {
    "ja": frozenset("一二三四五六七八九十") | {"一番"},
    "en": frozenset({"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}),
}
# 選択肢の語と同じ音の言い添え。並べると信頼度が割れる(上の 2)ので、その語が選択肢に
# あるときは言い添えから外す(ロッカーの「二 番」と言い添えの「に」)。言語ごと。
# 英語は未実測(空) — 試験で割れが見つかれば足す。
_SAME_SOUND: dict[str, dict[str, str]] = {
    "ja": {"に": "二"},
    "en": {},
}


def _settings_section(lang: str) -> str:
    """設定の節名。日本語は既存の `vosk`、他言語は `vosk_<lang>`(ネストしない)。"""
    return "vosk" if lang == "ja" else f"vosk_{lang}"


def model_path(lang: str = "ja") -> Path:
    return settings.resolve_path(str(settings.get(f"{_settings_section(lang)}.model_path")))


def _ensure_extracted(lang: str) -> None:
    """OTA は英語モデルを zip のまま配る(130MB・backend/app/api/kiosk.py の BUNDLE_FILES)。
    展開先(model_path)が無く、同じ場所に zip があれば初回だけ展開する。呼ぶ側
    (voice/server.py)が起動時と定期チェックの両方から呼ぶので、OTA で zip が届いた
    タイミングに関わらずいずれ拾われる。展開したあとは model_path が存在するだけなので、
    available()/load() はここを経由しなくても結果を正しく見る。
    """
    path = model_path(lang)
    if path.is_dir():
        return
    zip_path = path.parent / f"{path.name}.zip"
    if not zip_path.is_file():
        return
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.startswith("/") or ".." in Path(name).parts:
                    log.warning("[voice] %s: 危険なパスを含む zip のため展開しません(%s)", zip_path.name, name)
                    return
            z.extractall(path.parent)
        log.info("[voice] %s を展開しました(OTA配信・初回のみ)", zip_path.name)
    except Exception as e:
        log.warning("[voice] %s の展開に失敗しました: %s", zip_path.name, type(e).__name__)


def ensure_models_extracted() -> None:
    """全言語ぶん _ensure_extracted を試す。voice/server.py の起動時・定期チェックから呼ぶ。"""
    for lang in LANGS:
        try:
            _ensure_extracted(lang)
        except Exception:
            log.exception("[voice] モデル展開チェックに失敗(lang=%s)", lang)


def model_name(lang: str = "ja") -> str:
    return str(settings.get(f"{_settings_section(lang)}.model_name"))


def _probe_package() -> tuple[bool, str]:
    try:
        import vosk  # noqa: F401
    except Exception:
        return False, "vosk が入っていません (uv pip install vosk)"
    return True, ""


def available(lang: str = "ja") -> tuple[bool, str]:
    ok, detail = _probe_package()
    if not ok:
        return False, detail
    path = model_path(lang)
    if not path.is_dir():
        return False, (f"Vosk のモデルがありません: {path}"
                       " (python3 scripts/fetch_voice_models.py --extract)")
    return True, f"{model_name(lang)} ({path.name})"


def grammar_supported(lang: str = "ja") -> bool:
    """語彙を絞れるモデルか。1GB 版(vosk-model-ja-0.22)は HCLG.fst しか無く絞れない。"""
    graph = model_path(lang) / "graph"
    return (graph / "Gr.fst").is_file() and (graph / "HCLr.fst").is_file()


def describe(lang: str = "ja") -> dict:
    ok, detail = available(lang)
    return {
        "engine": ENGINE_NAME,
        "lang": lang,
        "available": ok,
        "detail": detail,
        "model": model_name(lang),
        "model_file": model_path(lang).name,
        "loaded": _models.get(lang) is not None,
        "grammar": grammar_supported(lang) if ok else False,
    }


def describe_all() -> dict:
    """言語ごとの可否一覧(`/voice/status` 用)。英語モデル未導入の端末でも落ちない。"""
    return {lang: describe(lang) for lang in LANGS}


def load(lang: str = "ja", force: bool = False) -> object:
    """モデルを読む。**読み込みは数秒かかる**ので、起動時に済ませておくとよい。"""
    with _model_locks[lang]:
        if _models.get(lang) is not None and not force:
            return _models[lang]
        ok, detail = available(lang)
        if not ok:
            raise EngineUnavailable(detail)
        import vosk
        vosk.SetLogLevel(-1)          # Kaldi の大量のログを止める
        started = time.monotonic()
        m = vosk.Model(str(model_path(lang)))
        _models[lang] = m
        log.info("[voice] vosk loaded in %dms (lang=%s model=%s)",
                 int((time.monotonic() - started) * 1000), lang, model_name(lang))
        return m


def unload(lang: str | None = None) -> None:
    """モデルと認識器を手放す。設定を変えて読み直すときだけ使う。lang=None で全言語。"""
    targets = LANGS if lang is None else (lang,)
    with _rec_lock:
        for t in targets:
            _free_recs.pop(t, None)
            _free_rates.pop(t, None)
        for key in [k for k in _cmd_recs if k[0] in targets]:
            _cmd_recs.pop(key, None)
        for key in [k for k in _seg_cache if k[0] in targets]:
            _seg_cache.pop(key, None)
        for key in [k for k in _seg_warned if k[0] in targets]:
            _seg_warned.discard(key)
    for t in targets:
        with _model_locks[t]:
            _models.pop(t, None)


def _free_recognizer(lang: str, rate: int):
    """語彙を絞らない認識器。呼ぶ側は _rec_lock を持っていること。"""
    import vosk

    if _free_recs.get(lang) is None or _free_rates.get(lang) != rate:
        rec = vosk.KaldiRecognizer(load(lang), float(rate))
        rec.SetWords(True)
        _free_recs[lang] = rec
        _free_rates[lang] = rate
    else:
        _free_recs[lang].Reset()
    return _free_recs[lang]


# ── 語彙 ──────────────────────────────────────────────────────────────────────

def lexicon_words(lang: str, candidates: set[str]) -> set[str]:
    """モデルの発音辞書にある語だけを返す。

    辞書に無い表記をグラマーに渡すと Vosk がその語を黙って落とすので、ここで確かめる。
    辞書は(日本語は)20 万語あるので、常駐させずに必要な語だけ拾って捨てる。
    英語モデルの辞書は小文字なので、呼ぶ側も小文字で渡すこと(VOICE_VOCAB の英語 say は
    最初から小文字で書く)。
    """
    path = model_path(lang) / "graph" / "words.txt"
    if not candidates or not path.is_file():
        return set()
    found: set[str] = set()
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            word = line.split(" ", 1)[0]
            if word in candidates:
                found.add(word)
    return found


def _segment(text: str, known: set[str]) -> tuple[str, ...] | None:
    """辞書の語でいちばん少ない数に切る。切れなければ None。

    同じ数なら前の語が長いほうを採る(「違います」→「違い ます」。「違 います」は
    辞書にあっても読みが怪しい)。英語は呼ぶ側がスペース区切りで書くのでここを通らない
    (phrase_tokens 参照)が、アルゴリズム自体は言語に依存しない。
    """
    def rank(t: tuple[str, ...]) -> tuple[int, list[int]]:
        return len(t), [-len(w) for w in t]

    n = len(text)
    best: list[tuple[str, ...] | None] = [None] * (n + 1)
    best[0] = ()
    for end in range(1, n + 1):
        for start in range(max(0, end - _PHRASE_MAX), end):
            head = best[start]
            piece = text[start:end]
            if head is None or piece not in known:
                continue
            cand = head + (piece,)
            if best[end] is None or rank(cand) < rank(best[end]):
                best[end] = cand
    return best[n]


def phrase_tokens(phrases: list[str], lang: str = "ja") -> dict[str, tuple[str, ...] | None]:
    """言い回しを発音辞書の語の並びに直す。

    空白で区切ってあればその区切りのまま(「お 願い し ます」。英語の言い回しは
    常にこの形で書く=「call staff」)、無ければ辞書の語でいちばん少ない数に切る
    (「ご訪問」→「ご 訪問」。日本語専用)。**辞書の語で書けない言い回しは
    None** — グラマーに渡すと Vosk がその語を黙って落とし、残りの語だけで当たって
    しまう(「二 番」の「二」が落ちて「番」単独が当たりになる)。
    """
    cache_keys = [(lang, p) for p in phrases]
    wanted = [p for p, k in zip(phrases, cache_keys) if k not in _seg_cache]
    if wanted:
        pieces: set[str] = set()
        for p in wanted:
            if " " in p:
                pieces.update(w for w in p.split(" ") if w)
            else:
                pieces.update(p[i:j] for i in range(len(p))
                              for j in range(i + 1, min(len(p), i + _PHRASE_MAX) + 1))
        known = lexicon_words(lang, pieces)
        for p in wanted:
            if " " in p:
                words = tuple(w for w in p.split(" ") if w)
                _seg_cache[(lang, p)] = words if words and all(w in known for w in words) else None
            else:
                _seg_cache[(lang, p)] = _segment(p, known) if p else None
    return {p: _seg_cache.get((lang, p)) for p in phrases}


def command_table(choices: list[tuple[str, list[str]]], lang: str = "ja") -> tuple[list[tuple[str, tuple[str, ...]]], list[str]]:
    """(選択肢 id, 語の並び) の一覧と、使えなかった言い回し。"""
    phrases = [p for _, ps in choices for p in ps]
    tokens = phrase_tokens(phrases, lang)
    table: list[tuple[str, tuple[str, ...]]] = []
    unusable: list[str] = []
    for cid, ps in choices:
        for p in ps:
            t = tokens.get(p)
            if t:
                if (cid, t) not in table:
                    table.append((cid, t))
            else:
                unusable.append(p)
    return table, unusable


def _filler_seqs(lang: str) -> list[tuple[str, ...]]:
    key = "command.fillers" if lang == "ja" else f"command.fillers_{lang}"
    return [t for t in phrase_tokens([str(f) for f in (settings.get(key) or [])], lang).values() if t]


def _command_grammar(lang: str, table: list[tuple[str, tuple[str, ...]]]) -> str:
    """語彙。選択肢の言い回しに、言い添え(「お願いします」「えっと」)を混ぜる。

    言い添えを入れないと、それが [unk] か選択肢の語に寄せられる。実測で
    「いちどもどってください」が「戻る」0.78 で誤爆していたのが、入れると消えた。
    選択肢と同じ言葉の言い添えは入れない。切り方が違うだけの同じ言葉(「お 願い します」と
    「お 願い し ます」)を両方入れると信頼度が割れて、選択肢として当たらなくなる(実測 0.79)。
    """
    choice_seqs = {t for _, t in table}
    choice_text = {"".join(t) for t in choice_seqs}
    choice_words = {w for t in choice_seqs for w in t}
    same_sound = _SAME_SOUND.get(lang, {})
    extra = [t for t in _filler_seqs(lang) if "".join(t) not in choice_text
             and not (len(t) == 1 and same_sound.get(t[0]) in choice_words)]
    seqs = sorted({" ".join(t) for t in choice_seqs} | {" ".join(t) for t in extra})
    return json.dumps(seqs + ["[unk]"], ensure_ascii=False)


def _command_recognizer(lang: str, rate: int, grammar: str):
    """画面ごとの語彙の認識器。呼ぶ側は _rec_lock を持っていること。

    画面を行き来するたびに語彙が変わるので、いくつかを持ち回す(古いものから捨てる)。
    """
    import vosk

    key = (lang, rate, grammar)
    rec = _cmd_recs.get(key)
    if rec is None:
        rec = vosk.KaldiRecognizer(load(lang), float(rate), grammar)
        rec.SetWords(True)
        _cmd_recs[key] = rec
        limit = max(1, int(settings.get("command.cache_size") or 1))
        while len(_cmd_recs) > limit:
            _cmd_recs.popitem(last=False)
    else:
        _cmd_recs.move_to_end(key)
        rec.Reset()
    return rec


# ── 照合 ──────────────────────────────────────────────────────────────────────

def _find_phrases(words: list[tuple], table: list[tuple[str, tuple[str, ...]]],
                  min_conf: float, number_min_conf: float | None = None,
                  numeral_words: frozenset[str] = frozenset()) -> list[tuple[int, int, str, float]]:
    """認識した語の列から、選択肢の言い回しが**続けて**現れた所を拾う。

    語で絞られるので、句の一部の語だけが返ることがある(上の 1)。句のすべての語が
    並び順どおりに続き、どの語もしきい値を越えたときだけ当たりにする。数字の語の
    しきい値は number_min_conf まで下げる(上の 5。min_conf より高くはしない)。
    重なった当たりは長いほうを残す(「ご 訪問」と「訪問」なら「ご 訪問」)。
    words は (語, 信頼度) か (語, 信頼度, 開始秒, 終了秒)。
    """
    # 語の切れ目ではなく**続けた文字列**で比べる。同じ言葉でも辞書の切り方が 2 通りある
    # (「お 願い します」と「お 願い し ます」)ので、切れ目で比べると取りこぼす。
    toks = [w[0] for w in words]
    num_floor = min_conf if number_min_conf is None else min(min_conf, number_min_conf)

    def passes(w: tuple) -> bool:
        return w[1] >= (num_floor if w[0] in numeral_words else min_conf)

    hits: list[tuple[int, int, str, float]] = []
    for cid, seq in table:
        target = "".join(seq)
        for i in range(len(toks)):
            joined = ""
            for j in range(i, len(toks)):
                joined += toks[j]
                if not target.startswith(joined):
                    break
                if joined == target:
                    if all(passes(w) for w in words[i:j + 1]):
                        hits.append((i, j + 1, cid, min(w[1] for w in words[i:j + 1])))
                    break
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
    kept: list[tuple[int, int, str, float]] = []
    for h in hits:
        if all(h[1] <= k[0] or h[0] >= k[1] for k in kept):
            kept.append(h)
    return kept


def _unknown_sec(words: list[tuple], lo: int, hi: int) -> float:
    """[unk](語彙に無い発話)が占める長さ。時刻の無い語は 0 として数える。"""
    return sum(max(0.0, w[3] - w[2]) for w in words[lo:hi] if w[0] == "[unk]" and len(w) >= 4)


def match_command(words: list[tuple], table: list[tuple[str, tuple[str, ...]]], min_conf: float, *,
                  trailing_unk_sec: float | None = None,
                  leading_unk_sec: float | None = None,
                  number_min_conf: float | None = None,
                  lang: str = "ja") -> tuple[str | None, float | None, str | None]:
    """(当たった選択肢, 信頼度, 外れた理由)。

    **2 つの選択肢が同時に当たったら何もしない**(ambiguous)。どちらか分からないまま
    画面を動かすより、言い直してもらうほうが害が小さい。

    **文の一部として言われたキーワードでは動かさない**(embedded)。合成音声の実測で、
    雑談に紛れたキーワード(「ロッカーの鍵どこだっけ」「やめるって言ってたよ」)は
    信頼度 1.0 で当たり、しきい値では切れなかった。違いは後ろに続く語で、画面へ向けた
    操作では言い添え(「で」「お願いします」)しか続かないのに、雑談では語彙に無い発話が
    0.29〜0.93 秒続いた。前に付く「えーと」「ちょっと」は 0.4 秒ほどなので、前は緩く見る。
    """
    if trailing_unk_sec is None:
        trailing_unk_sec = float(settings.get("command.trailing_unk_sec"))
    if leading_unk_sec is None:
        leading_unk_sec = float(settings.get("command.leading_unk_sec"))
    if number_min_conf is None:
        number_min_conf = float(settings.get("command.number_min_conf"))
    numeral_words = _NUMERAL_WORDS.get(lang, frozenset())
    kept = _find_phrases(words, table, min_conf, number_min_conf, numeral_words)
    ids = {cid for _, _, cid, _ in kept}
    if len(ids) > 1:
        # 言い添えと同じ言葉の選択肢(ようこそ画面の「お願いします」)は、ほかの言葉と
        # 一緒に言われたら譲る(「やめるでお願いします」は「やめる」)。
        weak = {"".join(t) for t in _filler_seqs(lang)}
        strong = [k for k in kept if "".join(w[0] for w in words[k[0]:k[1]]) not in weak]
        if strong and len({k[2] for k in strong}) == 1:
            kept = strong
            ids = {kept[0][2]}
    if len(ids) > 1:
        return None, None, "ambiguous"
    if not ids:
        return None, None, "unmatched"
    first = min(k[0] for k in kept)
    last = max(k[1] for k in kept)
    if (_unknown_sec(words, last, len(words)) >= trailing_unk_sec
            or _unknown_sec(words, 0, first) >= leading_unk_sec):
        return None, None, "embedded"
    cid = next(iter(ids))
    return cid, round(max(c for _, _, i, c in kept if i == cid), 3), None


def _as_unknown(lang: str, words: list[tuple], table: list[tuple[str, tuple[str, ...]]]) -> list[tuple]:
    """通常の認識の結果のうち、選択肢にも言い添えにも無い語を [unk] に置き換える。

    語彙を絞った認識と同じ物差し(「文の一部なら捨てる」)で照合するため。
    """
    allowed = {w for _, t in table for w in t} | {w for t in _filler_seqs(lang) for w in t}
    return [w if w[0] in allowed else ("[unk]",) + tuple(w[1:]) for w in words]


def _leveled(pcm: bytes) -> bytes:
    """声の大きさをそろえる(小さいときだけ持ち上げる)。

    **Vosk は小さすぎる声を言葉として聞き取れない。** 実機の USB マイクは声の山でも
    -52〜-65 dBFS しか無く、語彙を絞っても何の語も返らなかった(46 回中 1 回)。録った声に
    +18〜30dB 掛けると 29〜32 回になった。音量で区切る VAD は暗騒音との差で見るので影響しない。
    声の大きい所(上位 5%)が command.level_target_db になるように、最大 level_max_gain_db まで
    持ち上げる。下げはしない。言語に依存しない処理。
    """
    from voice.vad import dbfs
    from voice import capture

    step = 320 * 2
    dbs = sorted(dbfs(pcm[i:i + step]) for i in range(0, len(pcm) - step + 1, step) if pcm[i:i + step].strip(b"\x00"))
    if not dbs:
        return pcm
    level = dbs[min(len(dbs) - 1, int(len(dbs) * 0.95))]
    gain_db = float(settings.get("command.level_target_db")) - level
    gain_db = max(0.0, min(float(settings.get("command.level_max_gain_db")), gain_db))
    if gain_db < 1.0:
        return pcm
    return capture.apply_gain(pcm, 10 ** (gain_db / 20))


def _decode(rec, pcm: bytes) -> list[tuple]:
    rec.AcceptWaveform(pcm)
    payload = json.loads(rec.FinalResult() or "{}")
    return [(str(w.get("word", "")), float(w.get("conf", 0.0)),
             float(w.get("start", 0.0)), float(w.get("end", 0.0)))
            for w in payload.get("result") or [] if w.get("word")]


def recognize_command(seg: AudioSegment, choices: list[tuple[str, list[str]]],
                      min_conf: float | None = None, *, lang: str = "ja",
                      fallback: bool = False) -> CommandMatch:
    """画面の選択肢の語彙だけで 1 発話を decode し、どの選択肢かを返す。

    lang は表示言語(LANG)に追従するだけで、発話から自動判定はしない。
    fallback=True の画面(番号で選ぶロッカー)は、語彙を絞って外れたときだけ通常の認識で
    聞き直す(上の 3)。聞き直しの結果も同じ照合(続けて現れたか・文の一部でないか)に通す。

    認識した語そのもの(words)は調整用のスクリプトのためだけに持たせる。画面へも
    ログへも出さない(来訪者が何を話したかは残さない)。
    """
    load(lang)
    started = time.monotonic()
    table, unusable = command_table(choices, lang)
    warn_keys = [(lang, p) for p in unusable]
    fresh = [p for p, k in zip(unusable, warn_keys) if k not in _seg_warned]
    if fresh:
        _seg_warned.update((lang, p) for p in fresh)
        # 画面に書いた言葉が辞書に無い = その言葉では選べない。運用者が気づけるように。
        log.warning("[voice] 発音辞書の語で書けないため受け付けられない言い回し(lang=%s): %s",
                    lang, "、".join(fresh))
    if not table:
        return CommandMatch(matched=None, confidence=None, reason="no_vocabulary",
                            recognition_ms=0)
    floor = float(min_conf if min_conf is not None else settings.get("command.min_conf"))
    grammar = _command_grammar(lang, table)
    audio = _leveled(seg.pcm)            # 認識器の鍵を持つ前に済ませる(ほかの窓を待たせない)
    with _rec_lock:
        rec = None
        try:
            rec = _command_recognizer(lang, seg.sample_rate, grammar)
            words = _decode(rec, audio)
        except Exception as e:
            _cmd_recs.pop((lang, seg.sample_rate, grammar), None)
            raise EngineFailed(f"{type(e).__name__}") from e
        finally:
            try:
                if rec is not None:
                    rec.Reset()
            except Exception:
                pass
    matched, conf, reason = match_command(words, table, floor, lang=lang)

    if matched is None and reason != "ambiguous" and fallback:
        with _rec_lock:
            try:
                free = _free_recognizer(lang, seg.sample_rate)
                free_words = _as_unknown(lang, _decode(free, audio), table)
            except Exception as e:
                _free_recs.pop(lang, None)
                _free_rates.pop(lang, None)
                raise EngineFailed(f"{type(e).__name__}") from e
            finally:
                try:
                    rec2 = _free_recs.get(lang)
                    if rec2 is not None:
                        rec2.Reset()
                except Exception:
                    pass
        m2, c2, r2 = match_command(free_words, table, float(settings.get("command.fallback_min_conf")), lang=lang)
        if m2 is not None or r2 in ("ambiguous", "embedded"):
            matched, conf, reason, words = m2, c2, r2, free_words

    return CommandMatch(matched=matched, confidence=conf, reason=reason,
                        recognition_ms=int((time.monotonic() - started) * 1000), words=words)


def warmup(lang: str = "ja") -> None:
    """起動時にモデルと認識器を作っておく。

    **最初の1件だけ大きく遅い。** Windows の実測で 1 回目 4.7秒 → 2 回目以降 0.7秒。
    モデルの読み込みでも認識器の生成でもなく、Kaldi が**最初に実際のデコードを
    行うとき**に払う費用で、モデルファイルを先読みしても消えなかった。雑音を流して
    おくと一部を肩代わりできる。運用上は、起動後に最初に話しかけた 1 人だけが余分に待つ。
    呼ぶ側(server.py)が日英それぞれ呼ぶ。英語モデルが未導入の端末では
    EngineUnavailable を無視するだけで起動は止めない。
    """
    import random

    try:
        load(lang)
        rate = int(settings.get("audio.sample_rate") or 16000)
        random.seed(0)
        noise = b"".join(
            int(max(-32000, min(32000, random.gauss(0, 900)))).to_bytes(2, "little", signed=True)
            for _ in range(rate * 2))
        with _rec_lock:
            rec = _free_recognizer(lang, rate)
            rec.AcceptWaveform(noise)
            rec.FinalResult()
            rec.Reset()
    except EngineUnavailable as e:
        log.info("[voice] vosk(lang=%s): %s", lang, e)
    except Exception as e:                              # 起動は止めない
        log.warning("[voice] vosk(lang=%s) のウォームアップに失敗: %s", lang, type(e).__name__)
