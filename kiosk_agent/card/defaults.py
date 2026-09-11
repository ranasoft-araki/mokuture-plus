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
        "canny_low": 60,
        "canny_high": 180,
        # 低コントラスト用のエッジ戦略（正規化＋モルフォロジー勾配）のパラメータ。
        # 輝度をこの百分位で 0-255 に引き伸ばしてから勾配を取り、gradient_thresh 以上を
        # エッジとする。上げると木目などの誤検出が減り、白名刺が取りにくくなる。
        "normalize_lo_pct": 1.0,
        "normalize_hi_pct": 99.0,
        "gradient_thresh": 5,
        "approx_epsilon": 0.02,       # 多角形近似の許容誤差（輪郭長に対する比）
        # 「候補として拾う」下限。小さすぎ/大きすぎの案内は quality.capture_area_* が出す
        # ので、ここは拾えなくなる限界だけを決める（拾えないと案内自体が出せない）。
        "min_area_ratio": 0.02,
        "max_area_ratio": 0.95,
        # 長辺/短辺。日本の標準 91x55mm = 1.65。縦型名刺も同じ比になる。
        # 上限を 1.92 にしているのはスマートフォン画面(約 2.0)を弾くため。
        "aspect_min": 1.45,
        "aspect_max": 1.92,
        "margin_px": 4,               # 画面端からこの内側に四隅があること
        "min_text_regions": 3,        # 内部に文字らしい領域がこれ以上あること
        "max_candidates": 6,          # 輪郭の検査本数（上位いくつまで見るか）
        "min_corner_angle_deg": 60,   # 四隅の角度がこの範囲なら長方形とみなす
        "max_corner_angle_deg": 120,
    },

    "quality": {
        # 自動撮影に進んでよい名刺の大きさ（画面に占める面積比）。
        # 下回れば「もう少しカメラに近づけてください」、超えれば「少し離してください」。
        "capture_area_min": 0.12,
        "capture_area_max": 0.88,
        "focus_min": 60.0,            # Laplacian 分散の下限（下回る＝ピンぼけ）
        # 明るさは名刺領域の「上位 5% 点」で測る（平均だと濃色の名刺が暗所扱いになる）。
        "brightness_min": 90.0,       # 下回る＝その場が暗すぎる
        "brightness_max": 253.0,      # 上回る＝画面全体が飛んでいる（主判定は glare_max）
        "glare_max": 0.06,            # 名刺領域のうち飽和(>=250)している画素の割合の上限
        "motion_max": 0.012,          # 四隅の移動量（画面短辺比）の上限
        # 条件を満たす連続フレーム数。読み取りに失敗したら自動で撮り直すので、
        # ここで慎重にしすぎず「名刺を認識したらすぐ読み取りに入る」ほうを優先する。
        # 検出間隔 120ms × 3 ＝ およそ 0.4 秒で撮影に進む。
        "stable_frames": 3,
        "capture_cooldown_sec": 1.5,  # 撮影後、次に自動撮影可能になるまで
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
            "drop_score": 0.5,        # これ未満の行は捨てる
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
