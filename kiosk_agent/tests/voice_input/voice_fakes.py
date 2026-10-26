"""テスト用の Vosk のふり。

実モデル(48MB)を読まずに、語彙の組み立て・照合・後始末・API の流れを確かめるため。
語彙を絞った認識器(grammar あり)と、番号の聞き直しに使う通常の認識器(grammar なし)で
返す語を別々に決められる。

conftest.py ではなくここに置いているのは、`from voice_fakes import FakeRecognizer` のように
はっきり取り込めるようにするため(voice_audio.py と同じ作法)。
"""
from __future__ import annotations

import json

# 発音辞書(graph/words.txt)に載せる語。グラマーに入れられるのはここにある語だけ。
LEXICON = ["<eps>", "[unk]", "受付", "ご", "訪問", "一番", "二", "番", "三", "配達", "ロッカー",
           "戻る", "やめる", "待って", "続ける", "最初", "から", "はい", "いいえ", "違い", "違",
           "ます", "います", "お", "願い", "します", "し", "えー", "えっと", "あの", "で", "です",
           "を", "に", "の", "線", "電車"]

# 英語版(vosk_en のふり)。英語モデルの辞書は小文字。
LEXICON_EN = ["<eps>", "[unk]", "visit", "delivery", "package", "locker", "one", "two", "three",
              "back", "cancel", "wait", "continue", "start", "over", "yes", "no", "open",
              "um", "uh", "please", "check", "in", "submit"]


class FakeRecognizer:
    """語ごとの信頼度と時刻を返す Vosk の認識器のふり。"""

    #: 語彙を絞った認識器が返す語 [(語, 信頼度) or (語, 信頼度, 開始, 終了)]
    words: list[tuple] = []
    #: 語彙を絞らない認識器(番号の聞き直し)が返す語
    free_words: list[tuple] = []

    def __init__(self, model, rate, grammar=None):
        self.rate = rate
        self.grammar = json.loads(grammar) if grammar else None
        self.fed = b""
        self.resets = 0

    def SetWords(self, on):
        pass

    def Reset(self):
        self.resets += 1
        self.fed = b""

    def AcceptWaveform(self, pcm):
        self.fed += pcm
        return True

    def FinalResult(self):
        src = FakeRecognizer.words if self.grammar is not None else FakeRecognizer.free_words
        result = []
        for w in src:
            row = {"word": w[0], "conf": w[1]}
            if len(w) >= 4:
                row["start"], row["end"] = w[2], w[3]
            result.append(row)
        return json.dumps({"text": " ".join(w[0] for w in src), "result": result}, ensure_ascii=False)
