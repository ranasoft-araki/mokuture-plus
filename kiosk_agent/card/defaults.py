"""名刺認識の既定設定。

ここは「既定値の唯一の定義」。しきい値をコード中に直書きせず、必ずこの辞書を
経由して参照する（card.settings.cfg() が読む）。運用側は kiosk_agent 直下の
`card_reader.yaml` に同じ構造で書けば項目単位で上書きできる（PyYAML が必要）。
環境変数 `CARD_<SECTION>__<KEY>`（例: CARD_OCR__ENGINE=tesseract）でも上書き可。

`card_reader.yaml.example` は本辞書と同じ内容を持つ。ズレると tests/test_config.py
が落ちるので、片方だけ直すことはできない。
"""
from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    # 機能全体のスイッチ。false ならルーターは登録されるが status.available=False。
    "enabled": True,
    # /card/* をループバック(127.0.0.1/::1)からのみ受け付ける。キオスクのブラウザは
    # 同一端末なので既定 true のままで動く。LAN 経由で使いたい場合のみ false。
    "bind_loopback_only": True,

    "camera": {
        # ブラウザが検出ループで送ってくるフレームの想定最大幅(px)。
        # これを超えるものは受信後に縮小してから検出する（Pi での処理時間を一定に保つ）。
        "detect_frame_max_width": 640,
        # 撮影(OCR用)フレームの上限幅(px)。超えたら縮小する。
        "capture_max_width": 2048,
        # 検出ループの推奨送信間隔(ms)。ブラウザへ status で伝える。
        "detect_interval_ms": 120,
    },

    "detection": {
        # 検出は必ずこの幅に縮小してから行う（入力解像度で挙動が変わらないように）。
        "work_width": 640,
        "blur_kernel": 5,             # ノイズ除去(ガウシアン)のカーネル幅。奇数。
        # エッジの途切れを閉じるクロージングのカーネル幅。奇数。
        # 実機では名刺の 1 辺が背景と同系色になって途切れる。上げるとつながりやすく
        # なるが、近くにある別の輪郭ともつながりやすくなる。
        "close_kernel": 13,
        "canny_low": 60,
        "canny_high": 180,
        # 低コントラスト用のエッジ戦略（正規化＋モルフォロジー勾配）のパラメータ。
        # 輝度をこの百分位で 0-255 に引き伸ばしてから勾配を取り、gradient_thresh 以上を
        # エッジとする。上げると木目などの誤検出が減り、白名刺が取りにくくなる。
        "normalize_lo_pct": 1.0,
        "normalize_hi_pct": 99.0,
        # しきい値は max(gradient_thresh, この画像の勾配の gradient_noise_pct 百分位
        # × gradient_noise_mult)。画面の大半は平坦なので高めの百分位がノイズ床の
        # 推定になる。固定値だけでは、白い名刺（境界の勾配が弱い）と暗所やノイズの
        # 多い映像（ノイズ床が高い）を同時に扱えない。
        "gradient_thresh": 5,
        "gradient_noise_pct": 90.0,
        "gradient_noise_mult": 1.6,
        # 画面の白飛び画素がこの割合を超えたら、固定しきい値のエッジ抽出も試す。
        # 強い反射があると勾配の分布全体が持ち上がり、適応しきい値が名刺の境界まで
        # 切り落とすことがあるため。常時走らせると検出ループが重くなるので絞る。
        "glare_fallback_ratio": 0.02,
        "approx_epsilon": 0.02,       # 多角形近似の許容誤差（輪郭長に対する比）
        # 多角形近似で得た四隅を、辺ごとの直線当てはめで取り直す。
        # 名刺が画面内で小さいとき（縦型を横長のカメラで写した場合など）に効く。
        "refine_corners": True,
        # 「候補として拾う」下限。小さすぎ/大きすぎの案内は quality.capture_fill_* が出す
        # ので、ここは拾えなくなる限界だけを決める（拾えないと案内自体が出せない）。
        "min_area_ratio": 0.02,
        "max_area_ratio": 0.95,
        # 長辺/短辺。日本の標準 91x55mm = 1.65。縦型名刺も同じ比になる。
        # 上限を 1.92 にしているのはスマートフォン画面(約 2.0)を弾くため。
        "aspect_min": 1.45,
        "aspect_max": 1.92,
        "margin_px": 4,               # 画面端からこの内側に四隅があること
        # 四隅を結ぶ辺のうち、実際に輝度の段差がある割合の下限。背景のエッジを
        # つないだだけの四角形を落とす。指で隠れる辺があるので 1.0 は要求しない。
        "min_edge_support": 0.55,
        "edge_support_mult": 1.4,
        # 段差を探す幅(px)。エッジの途切れを埋めるクロージングで輪郭が外へ膨らむぶん、
        # 当てはめた辺は真の縁から数 px ずれる。その許容。
        "edge_support_window": 4,
        # 直前フレームとほぼ同じ位置にある候補は、辺の裏付けの条件をこの倍率に緩める
        # （追跡中の点滅を防ぐ）。track_motion_max は「同じ位置」とみなす移動量。
        "track_motion_max": 0.05,
        "track_support_relax": 0.7,
        # 内側がこの割合を超えて肌の色なら名刺ではない（顔・手のひらを落とす）。
        # キオスクでは名刺を顔の前に持つので、顔が候補として上がってくる。
        "max_skin_ratio": 0.15,
        # 肌と肌でないものの境目もエッジとして使う。名刺を手に持つと、手に重なった
        # 辺は明暗の差が出ずに輪郭が閉じない。色の境目なら確実に線になる。
        "use_skin_boundary": True,
        # 肌色の範囲（YCrCb）。照明で肌の明るさは大きく変わるので、しきい値は
        # ここで調整できるようにしてある。skin_luma_max は「紙を肌と間違えない」
        # ための上限で、実機の映像では 225 を超えると生成りの紙が肌側へ入る。
        "skin_cr_min": 133,
        "skin_cr_max": 173,
        "skin_cb_min": 77,
        "skin_cb_max": 127,
        "skin_cr_cb_min": 15,
        "skin_luma_max": 225,
        # 候補を「肌なので名刺ではない」と落とすときの明るさの上限（厳しい側）。
        # 暖色の紙は色域では肌と分けられない。分かれるのは明るさで、生成り・
        # クラフト紙の名刺は Y=170-225、実機の録画での肌は中央値 53・95% 点 110。
        # 上げると生成りの名刺が読めなくなるので、下げる方向で調整すること。
        "skin_reject_luma_max": 165,
        "min_text_regions": 3,        # 内部に文字らしい領域がこれ以上あること
        # 紙の縁で四角形が組めなかったときに、文字の並びから名刺の位置を決める。
        # 手に持った名刺は縁が指・逆光・同系色の背景で消えることが多く、実機の
        # 失敗画面ではエッジ側の候補が 1 つも通らなかった。文字は紙との差が
        # 大きいので確実に出る。詳しくは card/text_detect.py を参照。
        "text_fallback": True,
        "text_block_size": 25,        # 二値化の窓(奇数)
        "text_c": 10,                 # 二値化の下駄
        "text_min_height_px": 3,      # これより低い成分はノイズ
        "text_min_width_px": 2,       # これより細い成分はノイズ
        "text_row_gap": 0.8,          # 行の切れ目とみなす縦の空き(字高の倍数)
        "text_max_height_ratio": 0.12,   # 画面高のこの割合を超える成分は文字でない
        "text_max_width_ratio": 0.30,
        "text_max_aspect": 10.0,      # 極端に細長い成分(罫線)は文字でない
        "text_min_fill": 0.12,        # 外接矩形に対する塗りつぶし率の下限(中空を除く)
        # かたまりに含まれる文字数の下限。実機の録画では、文字 17 個で撮影に進んで
        # 何も読めなかった例があった。合成の名刺は 30-67 個なので 20 にしてある。
        "text_min_boxes": 20,
        "text_min_rows": 2,           # 1 行しかないものは名刺ではない
        "text_link_x": 3.0,           # 行方向につなぐ距離(字高の倍数)
        "text_link_y": 5.0,           # 行間をつなぐ距離(字高の倍数)
        "text_pad_ratio": 2.5,        # かたまりの外側へ広げる量(字高の倍数)
        # 文字が入る範囲の縦横比の上限。レシートのような細長い印刷物を落とす。
        # 名刺は正方形に近いことも横長なこともあるが、帯にはならない。
        "text_max_region_aspect": 2.4,
        # 密なかたまりを作ったあと、その矩形のすぐ外にある文字を取り込む距離
        # (字高の倍数)と回数。名刺は「社名・氏名」と「連絡先」の間が字高の 10 倍
        # ほど空くことがあり、つなぐ距離だけで届かせようとすると背景の文字まで拾う。
        "text_absorb_ratio_x": 2.0,
        "text_absorb_ratio_y": 16.0,
        "text_absorb_passes": 3,
        # 文字ベース検出の抑止。「名刺の形ではないが外形ははっきりしている」物体が
        # 写っていたら、その上の文字を名刺と見ない（A4 の書類・スマートフォンの画面）。
        # 実測: 書類 裏付け0.78 / スマホ 1.00 に対し、本当に困っている実機の画面は
        # 0.56-0.62（名刺の縁が指や逆光で壊れているので外形が測れない）。
        "text_veto_min_area": 0.10,
        "text_veto_support": 0.70,
        # 拾った文字のこの割合以上がその物体の上にあるときだけ止める。無条件に
        # 止めると、縁が壊れているだけの本物の名刺まで落ちる（実際に落ちた）。
        "text_veto_overlap": 0.60,
        "text_veto_max": 4,           # 覚えておく物体の数（速度のため）
        # この面積比以上で見つかったら、残りのエッジ抽出戦略は試さない。
        # 小さな四角形で打ち切ると名刺本体を見つけ損ねる。
        "strategy_stop_area": 0.12,
        # この点数の候補が出たら、同じエッジ画像の残りの候補は調べない（速度のため）。
        "candidate_stop_score": 0.80,
        # 輪郭の検査本数（凸包の面積で上位いくつまで見るか）。実機の映像は背景が
        # 雑然としていて名刺以外の輪郭も多いので、合成画像より多めに見る。
        "max_candidates": 12,
        "min_corner_angle_deg": 60,   # 四隅の角度がこの範囲なら長方形とみなす
        "max_corner_angle_deg": 120,
    },

    "quality": {
        # 自動撮影に進んでよい名刺の大きさ。「その向きで写せる最大の何割か」で測る
        # （面積比だと、横長のカメラでは縦型の名刺が最大でも画面の 34% にしかならず、
        #  横型の 93% と同じしきい値では縦型だけ不利になる。detect.fill_ratio 参照）。
        # 下回れば「もう少しカメラに近づけてください」、超えれば「少し離してください」。
        "capture_fill_min": 0.50,
        "capture_fill_max": 0.99,
        "focus_min": 60.0,            # Laplacian 分散の下限（下回る＝ピンぼけ）
        # 明るさは名刺領域の「上位 5% 点」で測る（平均だと濃色の名刺が暗所扱いになる）。
        "brightness_min": 90.0,       # 下回る＝その場が暗すぎる
        "brightness_max": 253.0,      # 上回る＝画面全体が飛んでいる（主判定は glare_max）
        "glare_max": 0.06,            # 名刺領域のうち飽和(>=250)している画素の割合の上限
        # 四隅の移動量（画面短辺比）の上限。手に持った名刺は必ず揺れるので、
        # 机に置く前提の厳しさにすると「動かさずに」が出続けて撮影に進まない。
        # 実測（実機の録画）では連続検出時の移動量の中央値が 0.010 だった。
        "motion_max": 0.030,
        # 条件を満たす連続フレーム数。読み取りに失敗したら自動で撮り直すので、
        # ここで慎重にしすぎず「名刺を認識したらすぐ読み取りに入る」ほうを優先する。
        # 検出間隔 120ms × 3 ＝ およそ 0.4 秒で撮影に進む。
        "stable_frames": 3,
        # 撮影後、次に自動撮影可能になるまで
        "capture_cooldown_sec": 1.5,
        # 文字ベースで見つけたときの「近づいてください」の判定。四隅が名刺の縁で
        # はないので占有率では測れない。代わりに「字が読める大きさか」を見る。
        # 検出フレーム(640px 幅)での字の高さ。実機の失敗画面では 8-9px あった。
        "text_height_min": 5.5,
    },

    "preprocess": {
        "output_width": 1024,         # 台形補正後の名刺画像の幅(px)
        # OCR にかける前処理バリアント。上から順に試し、早期採用条件を満たしたら打ち切る。
        "variants": ["color", "gray", "binary"],
        "early_accept_score": 0.86,   # このスコアを超えたら残りのバリアントを省略
        "min_text_height_px": 18,     # 推定文字高がこれ未満なら拡大する
        "upscale_max": 2.0,           # 拡大倍率の上限
        "clahe_clip": 2.0,            # コントラスト補正(CLAHE)の clipLimit
        "clahe_grid": 8,
        "denoise": True,
        "sharpen": True,
        "binary_block": 31,           # 適応的二値化のブロックサイズ。奇数。
        "binary_c": 10,
    },

    "ocr": {
        "engine": "paddle_onnx",      # paddle_onnx | tesseract
        "timeout_sec": 20.0,
        "threads": 3,                 # ONNX Runtime の intra_op スレッド数
        "paddle_onnx": {
            "det_model": "models/det.onnx",
            "rec_model": "models/rec_japan.onnx",
            "rec_dict": "models/japan_dict.txt",
            # 任意。置くと行ごとに 180 度の上下逆を直す（PP-OCR の方向分類モデル）。
            # 空文字なら使わない。
            "cls_model": "models/cls.onnx",
            # 任意。英数字専用の認識モデル。日本語モデルの文字セットには "@" と "_" が
            # 含まれず、メールアドレスを原理的に出力できないため、CJK を含まない行だけ
            # こちらで読み直す。空文字なら使わない（その場合は extract 側の補正に委ねる）。
            "rec_model_en": "models/rec_en.onnx",
            "rec_dict_en": "models/en_dict.txt",
            "det_limit_side_len": 960,
            "det_db_thresh": 0.3,
            "det_db_box_thresh": 0.5,
            "det_db_unclip_ratio": 1.7,
            "det_min_box_side": 4,
            "rec_image_height": 48,
            "rec_batch": 6,
            "use_space_char": True,
            "drop_score": 0.5,
            # 縦書き対応。縦長の枠を「1 文字ずつのマスに切って読む」解釈も試し、
            # 倒れた横書きとして読むより確からしければそちらを採る。
            "vertical_text": True,
            # 枠の縦横比がこれ以上なら縦長とみなす（縦書きの列の候補）。
            "vertical_ratio": 1.5,
            # 縦書きとして採用するのに必要な確信度の上乗せ。同点なら横書きを残す。
            "vertical_margin": 0.05,
            # 起こして読んだ確信度がこれ未満の列だけ、1 文字ずつの読みも試す。
            "vertical_try_below": 0.75,
            # 英数字モデルで読み直す行数の上限（メール・URL を優先して選ぶ）。
            "en_pass_max_lines": 4,
            # 縦書きのマスはどれも小さいので、まとめて推論したほうがずっと速い。
            "vertical_batch": 32,        # これ未満の行は捨てる
        },
        "tesseract": {
            "cmd": "tesseract",
            "lang": "jpn+eng",
            "psm": 6,
            "oem": 3,
            "drop_score": 0.4,
        },
    },

    "extraction": {
        "dictionaries_dir": "card/dictionaries",
        # 氏名がこの確信度に届かないときは確定せず候補として返す。
        "name_min_conf": 0.45,
        # 会社名候補を文字サイズで評価するときの、最大行高に対する比。
        "large_text_ratio": 0.72,
    },

    # 撮影して OCR した結果を「読み取れた」と見なす条件。
    # 満たしていれば確認画面へ進み、満たしていなければ黙って撮り直す。
    # 利用者に「撮れたのに何も入っていない確認画面」を見せないための関門。
    "accept": {
        # このうち少なくとも 1 つは値が取れていること（受付フォームに入る項目）。
        # 空リストにすると項目の種類は問わなくなる。
        "require_any": ["person_name", "company_name"],
        # 埋まった項目の数の下限。
        "min_fields": 2,
        # 全体の読み取り精度（extract.overall_confidence）の下限。
        "min_confidence": 0.35,
        # 自動での撮り直しの上限。これを超えたら、取れた分だけで確認画面へ進む
        # （利用者が手で入力できるようにする。無限に撮り直さない）。
        "max_attempts": 5,
        # 撮り直しまでの間隔（秒）。短すぎると同じ失敗を繰り返すだけになる。
        "retry_cooldown_sec": 0.8,
    },

    "confidence": {
        # 確認画面の色分け閾値。ok 以上=通常 / warn 以上=要確認(黄) / 未満=要入力(赤)
        "ok": 0.85,
        "warn": 0.60,
    },

    "session": {
        "ttl_sec": 180,               # 無操作でセッション（＝画像・抽出結果）を破棄
        "max_sessions": 4,
        "max_frame_bytes": 4_000_000, # 1 リクエストで受け取る画像の上限
    },
}
