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


class EngineUnavailable(RuntimeError):
    """モデルか vosk パッケージが無い。"""


class EngineFailed(RuntimeError):
    """認識そのものに失敗した。"""


# モデルの読み込みは数秒かかるうえメモリを持つので、一度だけ読んで使い回す。
_model = None
_model_lock = threading.Lock()

# 認識器も使い回す。**毎回作り直すと 3 倍以上遅くなる**(実測: 中央値 4.45秒 → 1.28秒)。
# デコード用のグラフを組み直すのがそれだけ重い。Kaldi の認識器はスレッド安全では
# ないので、ここで直列化する(認識自体も session 側で 1 件ずつに絞っている)。
_rec_lock = threading.Lock()
# 語彙を絞らない認識器(番号の聞き直し用)。
_free_rec = None
_free_rate = 0
# 語彙ごとの認識器。画面を行き来するたびに作り直さない。
_cmd_recs: "OrderedDict[tuple[int, str], object]" = OrderedDict()
# 言い回し → 発音辞書の語の並び(辞書に無ければ None)。語彙は画面ごとにほぼ固定なので、
# 20 万語の辞書を読むのは初めて見た言い回しのときだけで済む。
_seg_cache: dict[str, tuple[str, ...] | None] = {}
_seg_warned: set[str] = set()
_PHRASE_MAX = 16

# 数字の語(上の 5)。合格ラインを command.number_min_conf まで下げる。
_NUMERAL_WORDS = frozenset("一二三四五六七八九十") | {"一番"}
# 選択肢の語と同じ音の言い添え。並べると信頼度が割れる(上の 2)ので、その語が選択肢に
# あるときは言い添えから外す(ロッカーの「二 番」と言い添えの「に」)。
_SAME_SOUND = {"に": "二"}


def model_path() -> Path:
    return settings.resolve_path(str(settings.get("vosk.model_path")))


def model_name() -> str:
    return str(settings.get("vosk.model_name"))


def _probe_package() -> tuple[bool, str]:
    try:
        import vosk  # noqa: F401
    except Exception:
        return False, "vosk が入っていません (uv pip install vosk)"
    return True, ""


def available() -> tuple[bool, str]:
    ok, detail = _probe_package()
    if not ok:
        return False, detail
    path = model_path()
    if not path.is_dir():
        return False, (f"Vosk のモデルがありません: {path}"
                       " (python3 scripts/fetch_voice_models.py --extract)")
    return True, f"{model_name()} ({path.name})"


def grammar_supported() -> bool:
    """語彙を絞れるモデルか。1GB 版(vosk-model-ja-0.22)は HCLG.fst しか無く絞れない。"""
    graph = model_path() / "graph"
    return (graph / "Gr.fst").is_file() and (graph / "HCLr.fst").is_file()


def describe() -> dict:
    ok, detail = available()
    return {
        "engine": ENGINE_NAME,
        "available": ok,
        "detail": detail,
        "model": model_name(),
        "model_file": model_path().name,
        "loaded": _model is not None,
        "grammar": grammar_supported() if ok else False,
    }


def load(force: bool = False) -> object:
    """モデルを読む。**読み込みは数秒かかる**ので、起動時に済ませておくとよい。"""
    global _model
    with _model_lock:
        if _model is not None and not force:
            return _model
        ok, detail = available()
        if not ok:
            raise EngineUnavailable(detail)
        import vosk
        vosk.SetLogLevel(-1)          # Kaldi の大量のログを止める
        started = time.monotonic()
        _model = vosk.Model(str(model_path()))
        log.info("[voice] vosk loaded in %dms (model=%s)",
                 int((time.monotonic() - started) * 1000), model_name())
        return _model


def unload() -> None:
    """モデルと認識器を手放す。設定を変えて読み直すときだけ使う。"""
    global _model, _free_rec, _free_rate
    with _rec_lock:
        _free_rec, _free_rate = None, 0
        _cmd_recs.clear()
        _seg_cache.clear()
    with _model_lock:
        _model = None


def _free_recognizer(rate: int):
    """語彙を絞らない認識器。呼ぶ側は _rec_lock を持っていること。"""
    global _free_rec, _free_rate
    import vosk

    if _free_rec is None or _free_rate != rate:
        _free_rec = vosk.KaldiRecognizer(load(), float(rate))
        _free_rec.SetWords(True)
        _free_rate = rate
    else:
        _free_rec.Reset()
    return _free_rec


# ── 語彙 ──────────────────────────────────────────────────────────────────────

def lexicon_words(candidates: set[str]) -> set[str]:
    """モデルの発音辞書にある語だけを返す。

    辞書に無い表記をグラマーに渡すと Vosk がその語を黙って落とすので、ここで確かめる。
    辞書は 20 万語あるので、常駐させずに必要な語だけ拾って捨てる。
    """
    path = model_path() / "graph" / "words.txt"
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
    辞書にあっても読みが怪しい)。
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


def phrase_tokens(phrases: list[str]) -> dict[str, tuple[str, ...] | None]:
    """言い回しを発音辞書の語の並びに直す。

    空白で区切ってあればその区切りのまま(「お 願い し ます」)、無ければ辞書の語で
    いちばん少ない数に切る(「ご訪問」→「ご 訪問」)。**辞書の語で書けない言い回しは
    None** — グラマーに渡すと Vosk がその語を黙って落とし、残りの語だけで当たって
    しまう(「二 番」の「二」が落ちて「番」単独が当たりになる)。
    """
    wanted = [p for p in phrases if p not in _seg_cache]
    if wanted:
        pieces: set[str] = set()
        for p in wanted:
            if " " in p:
                pieces.update(w for w in p.split(" ") if w)
            else:
                pieces.update(p[i:j] for i in range(len(p))
                              for j in range(i + 1, min(len(p), i + _PHRASE_MAX) + 1))
        known = lexicon_words(pieces)
        for p in wanted:
            if " " in p:
                words = tuple(w for w in p.split(" ") if w)
                _seg_cache[p] = words if words and all(w in known for w in words) else None
            else:
                _seg_cache[p] = _segment(p, known) if p else None
    return {p: _seg_cache.get(p) for p in phrases}


def command_table(choices: list[tuple[str, list[str]]]) -> tuple[list[tuple[str, tuple[str, ...]]], list[str]]:
    """(選択肢 id, 語の並び) の一覧と、使えなかった言い回し。"""
    phrases = [p for _, ps in choices for p in ps]
    tokens = phrase_tokens(phrases)
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


def _filler_seqs() -> list[tuple[str, ...]]:
    return [t for t in phrase_tokens([str(f) for f in (settings.get("command.fillers") or [])]).values() if t]


def _command_grammar(table: list[tuple[str, tuple[str, ...]]]) -> str:
    """語彙。選択肢の言い回しに、言い添え(「お願いします」「えっと」)を混ぜる。

    言い添えを入れないと、それが [unk] か選択肢の語に寄せられる。実測で
    「いちどもどってください」が「戻る」0.78 で誤爆していたのが、入れると消えた。
    選択肢と同じ言葉の言い添えは入れない。切り方が違うだけの同じ言葉(「お 願い します」と
    「お 願い し ます」)を両方入れると信頼度が割れて、選択肢として当たらなくなる(実測 0.79)。
    """
    choice_seqs = {t for _, t in table}
    choice_text = {"".join(t) for t in choice_seqs}
    choice_words = {w for t in choice_seqs for w in t}
    extra = [t for t in _filler_seqs() if "".join(t) not in choice_text
             and not (len(t) == 1 and _SAME_SOUND.get(t[0]) in choice_words)]
    seqs = sorted({" ".join(t) for t in choice_seqs} | {" ".join(t) for t in extra})
    return json.dumps(seqs + ["[unk]"], ensure_ascii=False)


def _command_recognizer(rate: int, grammar: str):
    """画面ごとの語彙の認識器。呼ぶ側は _rec_lock を持っていること。

    画面を行き来するたびに語彙が変わるので、いくつかを持ち回す(古いものから捨てる)。
    """
    import vosk

    key = (rate, grammar)
    rec = _cmd_recs.get(key)
    if rec is None:
        rec = vosk.KaldiRecognizer(load(), float(rate), grammar)
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
                  min_conf: float, number_min_conf: float | None = None) -> list[tuple[int, int, str, float]]:
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
        return w[1] >= (num_floor if w[0] in _NUMERAL_WORDS else min_conf)

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
                  number_min_conf: float | None = None) -> tuple[str | None, float | None, str | None]:
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
    kept = _find_phrases(words, table, min_conf, number_min_conf)
    ids = {cid for _, _, cid, _ in kept}
    if len(ids) > 1:
        # 言い添えと同じ言葉の選択肢(ようこそ画面の「お願いします」)は、ほかの言葉と
        # 一緒に言われたら譲る(「やめるでお願いします」は「やめる」)。
        weak = {"".join(t) for t in _filler_seqs()}
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


def _as_unknown(words: list[tuple], table: list[tuple[str, tuple[str, ...]]]) -> list[tuple]:
    """通常の認識の結果のうち、選択肢にも言い添えにも無い語を [unk] に置き換える。

    語彙を絞った認識と同じ物差し(「文の一部なら捨てる」)で照合するため。
    """
    allowed = {w for _, t in table for w in t} | {w for t in _filler_seqs() for w in t}
    return [w if w[0] in allowed else ("[unk]",) + tuple(w[1:]) for w in words]


def _leveled(pcm: bytes) -> bytes:
    """声の大きさをそろえる(小さいときだけ持ち上げる)。

    **Vosk は小さすぎる声を言葉として聞き取れない。** 実機の USB マイクは声の山でも
    -52〜-65 dBFS しか無く、語彙を絞っても何の語も返らなかった(46 回中 1 回)。録った声に
    +18〜30dB 掛けると 29〜32 回になった。音量で区切る VAD は暗騒音との差で見るので影響しない。
    声の大きい所(上位 5%)が command.level_target_db になるように、最大 level_max_gain_db まで
    持ち上げる。下げはしない。
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
                      min_conf: float | None = None, *, fallback: bool = False) -> CommandMatch:
    """画面の選択肢の語彙だけで 1 発話を decode し、どの選択肢かを返す。

    fallback=True の画面(番号で選ぶロッカー)は、語彙を絞って外れたときだけ通常の認識で
    聞き直す(上の 3)。聞き直しの結果も同じ照合(続けて現れたか・文の一部でないか)に通す。

    認識した語そのもの(words)は調整用のスクリプトのためだけに持たせる。画面へも
    ログへも出さない(来訪者が何を話したかは残さない)。
    """
    load()
    started = time.monotonic()
    table, unusable = command_table(choices)
    fresh = [p for p in unusable if p not in _seg_warned]
    if fresh:
        _seg_warned.update(fresh)
        # 画面に書いた言葉が辞書に無い = その言葉では選べない。運用者が気づけるように。
        log.warning("[voice] 発音辞書の語で書けないため受け付けられない言い回し: %s", "、".join(fresh))
    if not table:
        return CommandMatch(matched=None, confidence=None, reason="no_vocabulary",
                            recognition_ms=0)
    floor = float(min_conf if min_conf is not None else settings.get("command.min_conf"))
    grammar = _command_grammar(table)
    audio = _leveled(seg.pcm)            # 認識器の鍵を持つ前に済ませる(ほかの窓を待たせない)
    with _rec_lock:
        rec = None
        try:
            rec = _command_recognizer(seg.sample_rate, grammar)
            words = _decode(rec, audio)
        except Exception as e:
            _cmd_recs.pop((seg.sample_rate, grammar), None)
            raise EngineFailed(f"{type(e).__name__}") from e
        finally:
            try:
                if rec is not None:
                    rec.Reset()
            except Exception:
                pass
    matched, conf, reason = match_command(words, table, floor)

    if matched is None and reason != "ambiguous" and fallback:
        with _rec_lock:
            try:
                free = _free_recognizer(seg.sample_rate)
                free_words = _as_unknown(_decode(free, audio), table)
            except Exception as e:
                globals()["_free_rec"], globals()["_free_rate"] = None, 0
                raise EngineFailed(f"{type(e).__name__}") from e
            finally:
                try:
                    if _free_rec is not None:
                        _free_rec.Reset()
                except Exception:
                    pass
        m2, c2, r2 = match_command(free_words, table, float(settings.get("command.fallback_min_conf")))
        if m2 is not None or r2 in ("ambiguous", "embedded"):
            matched, conf, reason, words = m2, c2, r2, free_words

    return CommandMatch(matched=matched, confidence=conf, reason=reason,
                        recognition_ms=int((time.monotonic() - started) * 1000), words=words)


def warmup() -> None:
    """起動時にモデルと認識器を作っておく。

    **最初の1件だけ大きく遅い。** Windows の実測で 1 回目 4.7秒 → 2 回目以降 0.7秒。
    モデルの読み込みでも認識器の生成でもなく、Kaldi が**最初に実際のデコードを
    行うとき**に払う費用で、モデルファイルを先読みしても消えなかった。雑音を流して
    おくと一部を肩代わりできる。運用上は、起動後に最初に話しかけた 1 人だけが余分に待つ。
    """
    import random

    try:
        load()
        rate = int(settings.get("audio.sample_rate") or 16000)
        random.seed(0)
        noise = b"".join(
            int(max(-32000, min(32000, random.gauss(0, 900)))).to_bytes(2, "little", signed=True)
            for _ in range(rate * 2))
        with _rec_lock:
            rec = _free_recognizer(rate)
            rec.AcceptWaveform(noise)
            rec.FinalResult()
            rec.Reset()
    except EngineUnavailable as e:
        log.info("[voice] vosk: %s", e)
    except Exception as e:                              # 起動は止めない
        log.warning("[voice] vosk のウォームアップに失敗: %s", type(e).__name__)
