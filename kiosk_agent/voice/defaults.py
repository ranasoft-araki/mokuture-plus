"""音声入力の既定値。

ここが唯一の「設定の形」の定義で、`voice_input.yaml` と環境変数 `VOICE_*` は
**ここに在るキーだけ**を上書きできる（打ち間違いは無視され、既定値のまま動く）。
値の型も既定値に合わせて変換される（`settings.py`）。

しきい値の初期値は要件 §8 の指定に合わせてある:
    発話開始待ち 5 秒 / 発話終了と判断する無音 0.7 秒 / 1 項目の最大録音 10 秒 /
    認識のタイムアウト 10 秒
"""
from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    # 機能ごと止めるスイッチ。false なら /voice/status が available=false を返し、
    # キオスク画面は「音声で入力」を描画しない（受付は従来どおり動く）。
    "enabled": True,

    # ── 待ち受け ──────────────────────────────────────────────────────────
    # 外部ネットワークから触れないこと(§10)をソケットの時点で保証する。
    # bind_host を 127.0.0.1 以外にするのは「セキュリティ設定を無効化して動かす」
    # ことに当たる(§13)ので、server.py が起動時に警告を出す。
    "server": {
        "bind_host": "127.0.0.1",
        "port": 8181,
        # CORS を許すオリジン。キオスク画面は agent(8080)から配信されるので、その
        # ループバック表記だけを許可する。ワイルドカードにはしない。
        "allowed_origins": [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        # OTA でソースが差し替わったら自分で終了して systemd に再起動させる。
        "watch_sources_sec": 60,
    },

    # ── マイク ────────────────────────────────────────────────────────────
    "audio": {
        # arecord の -D に渡す値。`arecord -l` / `arecord -L` で確認する。
        # 例: "default" / "plughw:1,0" / "sysdefault:CARD=USB"
        # ここで開けなければ、挿さっている録音デバイスへ自動で移る
        # (capture.resolve_device)。USB マイクのカード番号は固定できないため。
        "device": "default",
        # whisper.cpp も Vosk も 16kHz モノラル 16bit PCM を前提にしている。
        "sample_rate": 16000,
        "channels": 1,
        # auto = arecord → sounddevice → 無し の順に試す。
        # file = 下の file_path の WAV をマイクの代わりに流す(動作試験用)。
        "backend": "auto",
        # backend: file のときに読む WAV。**ここに載っていない設定キーは
        # 設定ファイルでも環境変数でも無視される**ので、使うキーは必ず既定に置く。
        "file_path": "",
        # 録音開始の頭を捨てる長さ。受付開始音やスピーカーの余韻がマイクに
        # 回り込むのを防ぐ(§9)。
        "start_guard_ms": 250,
        # 取り込んだ PCM に掛ける利得。小さすぎるマイクの救済用。1.0 = そのまま。
        "input_gain": 1.0,
        # arecord のプロセス起動が失敗したときに再試行する回数。
        "open_retries": 1,
    },

    # ── VAD(発話区間の検出) ───────────────────────────────────────────────
    # 前後の無音を認識処理へ渡さない(§8)。既定は依存パッケージ不要の
    # エネルギーベース。webrtcvad が入っていれば engine: webrtc も選べる。
    "vad": {
        "engine": "auto",
        "frame_ms": 20,
        # ボタンを押してから、話し始めるのを待つ時間。
        "start_timeout_sec": 5.0,
        # 話し終わったと判断する無音の長さ(要件は 0.5〜0.8 秒)。
        "silence_sec": 0.7,
        # 1 項目の最大録音時間。これを超えたらそこまでを認識に回す。
        "max_record_sec": 10.0,
        # これより短い発話は「短すぎる」として再入力を促す(§7)。
        "min_speech_sec": 0.35,
        # 発話の前後に少しだけ無音を残す。子音の頭やお尻が切れるのを防ぐ。
        "pre_roll_ms": 250,
        "post_roll_ms": 250,
        # エネルギーVAD: 暗騒音の推定値(dBFS)の初期値と、発話と見なす上乗せ幅。
        # ロビーの空調音などに合わせて起動後に自動追従する。
        "noise_floor_init_db": -55.0,
        "noise_floor_adapt": 0.05,
        "speech_margin_db": 9.0,
        # 無音と見なす上乗せ幅。speech_margin_db より小さくしてバタつきを防ぐ。
        "silence_margin_db": 5.0,
        # webrtcvad の攻撃性(0=緩い 〜 3=厳しい)。
        "webrtc_aggressiveness": 2,
    },

    # ── whisper.cpp(会社名・訪問者名) ─────────────────────────────────────
    # 事前登録されていない社名・氏名を拾う必要があるので、語彙を限定しない
    # whisper.cpp を使う(§3-1)。
    "whisper": {
        # kiosk_agent 直下からの相対パス(絶対パスも可)。
        # Linux/Pi は install_voice.sh が vendor/whisper.cpp/ にビルドしたもの。
        "binary": "vendor/whisper.cpp/build/bin/whisper-cli",
        # Windows での動作試験用。上流の配布バイナリ(同じ v1.9.3)を
        # scripts/install_voice_windows.ps1 がここへ展開する。
        # Windows ではこちらが優先される(空にすると binary を見る)。
        "binary_windows": "vendor/whisper.cpp-win-x64/Release/whisper-cli.exe",
        "model_path": "voice_models/ggml-base-q5_1.bin",
        # メトリクスに出す識別子。モデルを変えたらここも変える(個人情報ではない)。
        "model_name": "whisper-base-q5",
        "language": "ja",
        # Pi 5 は 4 コア。他の処理と食い合わないよう既定は 4。
        "threads": 4,
        "timeout_sec": 10.0,
        # 音 1 秒あたりに許す認識時間。一文(最長15秒)は固定値では足りないので、
        # 長い音では timeout_sec とこちらの大きい方を使う。Pi は Windows より
        # 遅いので、実機に合わせて上げること。
        "timeout_per_audio_sec": 2.0,

        # 1 = greedy。キオスクの短い発話ではビーム幅を広げても効果が薄く、遅くなる。
        "beam_size": 1,
        # 音声・中間 JSON の置き場。tmpfs(RAM)に置き、finally で必ず消す。
        # 存在しない環境(開発機)では tempfile の既定ディレクトリに落ちる。
        "tmp_dir": "/dev/shm",
        # 無音に対して whisper が幻聴を出すのを抑える(whisper.cpp のしきい値)。
        "no_speech_thold": 0.6,
        "entropy_thold": 2.4,
        # 「(拍手)」「♪」などの非発話トークンを抑制する。
        "suppress_non_speech": True,
        # 上で足りないときに素の引数を足す逃げ道。例: ["--best-of", "2"]
        "extra_args": [],
    },

    # ── Vosk(画面操作・担当者名) ──────────────────────────────────────────
    # 語彙が決まっている短い命令と、登録済み担当者の照合に使う(§3-2)。
    # 第3・4段階。モデルが無ければ whisper へ自動フォールバックする。
    "vosk": {
        # 担当者の語彙だけで decode し直す 2 パス目(voice/vosk_engine.py に実測)。
        # false にすると 1 パス目だけになる。
        "grammar": True,
        # 2 パス目の候補を採るしきい値。実測で正解は 1.000、誤って埋めた語は
        # 0.657〜0.871 だったので、その間に置く。上げるほど「候補なし」に倒れる
        # (＝画面で選んでもらう従来の動きに戻るだけで、間違った人は呼ばない)。
        "grammar_min_conf": 0.9,
        # 2 パス目の語彙に混ぜる受付の定型句。名前だけの語彙にすると周りが全部
        # [unk] に寄って、名前の切り出しまで崩れる。辞書に無い並びは自動で落ちる。
        "grammar_phrases": [
            "と 申し ます", "です", "の", "様", "さん", "打ち合わせ", "お 約束", "で",
            "まいり まし た", "本日", "から 来 まし た", "お 願い し ます",
            "荷物", "お 届け", "に 来 まし た", "会い に 来 まし た", "アポ", "面接",
        ],
        "model_path": "voice_models/vosk-model-small-ja-0.22",
        "model_name": "vosk-small-ja-0.22",
        "timeout_sec": 6.0,
        # 認識できる語を絞り込む(Vosk のグラマー機能)。モデルの語彙に無い語が
        # 混ざると構築に失敗するので、失敗したら自由認識へ落とす。
        "use_grammar": True,
    },

    # ── 項目ごとの割り当て ────────────────────────────────────────────────
    # engine: whisper | vosk | auto(auto = 使えるほうを自動選択)
    "fields": {
        "company": {
            "engine": "whisper",
            "prompt_ja": "会社名をお話しください",
            "prompt_en": "Please say your company name",
            "example_ja": "「株式会社ラナソフト」",
            "max_record_sec": 10.0,
        },
        "person_name": {
            "engine": "whisper",
            "prompt_ja": "お名前をお話しください",
            "prompt_en": "Please say your name",
            "example_ja": "「荒木秀人です」",
            "max_record_sec": 8.0,
        },
        "staff": {
            "engine": "auto",
            "prompt_ja": "訪問先の担当者名をお話しください",
            "prompt_en": "Please say who you are visiting",
            "example_ja": "「営業部の田中さん」",
            "max_record_sec": 8.0,
        },
        # 一文の名乗りをまとめて受ける。項目ごとに区切って言わせると受付として
        # 不自然なので、こちらを既定の入口にする。文の途中で間が空くので、
        # 無音とみなすまでの長さを他より長く取る。
        "reception": {
            # 一文の名乗りは Vosk の方が固有名詞の読みを当てる(voice/engines.py に
            # 比較表)。auto = Vosk が使えれば Vosk、駄目なら whisper。
            "engine": "auto",
            "prompt_ja": "ご用件をお話しください",
            "prompt_en": "Please tell us who you are and who you are visiting",
            "example_ja": "「磯野木工所の荒木と申します。服部様と打ち合わせのお約束で参りました」",
            "max_record_sec": 15.0,
            "silence_sec": 1.2,
        },
        "command": {
            "engine": "auto",
            "prompt_ja": "お話しください",
            "prompt_en": "Please speak",
            "example_ja": "「はい」「次へ」",
            "max_record_sec": 4.0,
        },
    },

    # ── 認識結果を採用してよいかの判定(§7) ───────────────────────────────
    # whisper.cpp から確信度が十分に取れないことがあるので、単一の数値では決めず
    # 複数の手がかりを組み合わせる。どれかに引っかかったら自動確定せず再入力を促す。
    "quality": {
        # 認識文字数の下限。これ未満は空と同じ扱い。
        "min_chars": 1,
        # 発話時間に対する文字数の上限。1 秒で 12 文字を超えるのは幻聴の疑い。
        "max_chars_per_sec": 12.0,
        # 録音全体に占める発話区間の割合の下限。
        "min_speech_ratio": 0.20,
        # 平均トークン確率の下限(whisper.cpp が返したときだけ見る)。
        "avg_token_prob_min": 0.45,
        # no-speech 確率の上限(同上)。
        "no_speech_max": 0.60,
        # 同じ文字・同じ並びの繰り返しが占める割合の上限。
        "repeat_ratio_max": 0.55,
        # 「要確認」として色を変えて出す下限。これ以上 ok 未満は表示だけ変える。
        "warn_token_prob": 0.65,
    },

    # ── セッション ────────────────────────────────────────────────────────
    "session": {
        # 触られないまま放置されたセッションを捨てるまでの秒数。
        # 破棄 = 音声と認識結果の破棄(§11)。
        "ttl_sec": 180.0,
        "max_sessions": 4,
        # 同時に走らせる認識の数。Pi 5 の CPU を食い合わせない。
        "max_concurrent_recognition": 1,
    },

    # ── 実証実験用の匿名メトリクス(§11・§12) ─────────────────────────────
    # 個人を特定できる値は書かない。認識結果・氏名・会社名は一切入れない。
    "metrics": {
        "enabled": True,
        "path": "~/.mokuture-voice/metrics.jsonl",
        "max_bytes": 2000000,
        "keep_files": 3,
    },

    # ── 担当者の読み仮名(§3-2) ───────────────────────────────────────────
    # 社員マスター(tenants.staff_list)は表示氏名のカンマ区切りだけで、読み仮名・
    # 部署・別称を持たない。読みを推測して確定するのは禁止(§3-2)なので、
    # 端末ローカルのこのファイルに読みがある担当者だけを音声照合の対象にする。
    "staff": {
        "readings_path": "staff_readings.yaml",
        # 照合に通す最低スコア(0〜1)。これ未満の候補は出さない。
        "match_min_score": 0.55,
        # 画面に出す候補の最大数(§4「最大3名程度」)。
        "max_candidates": 3,
        # 1 位と 2 位がこの差より近ければ「絞れていない」として候補選択にする。
        "ambiguous_margin": 0.08,
    },
}
