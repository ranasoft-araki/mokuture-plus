"""架空名刺のテスト画像を生成する。

実在する個人・法人の名刺は一切使わない。ここで作るのは
`example.jp` / `sample.co.jp` など予約済みドメインと、架空の社名・氏名だけ。

生成物は tests/fixtures/ に置く（.gitignore 済み）。リポジトリには画像そのもの
ではなく「生成するコード」を入れる方針。テストは実行時に必要な分だけ作る。

    python tests/make_fixtures.py            # 全パターンを tests/fixtures/ へ
    python tests/make_fixtures.py --list     # パターン名の一覧
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = TESTS_DIR / "fixtures"

# 名刺の実寸 91x55mm を 12px/mm で描く（= 1092x660px）。
MM = 12
CARD_W, CARD_H = 91 * MM, 55 * MM

# 日本語が出るフォントを順に探す。見つからなければ ASCII だけで描く。
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
]
_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]


def _font_path(bold: bool = False) -> str | None:
    for p in (_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        if Path(p).exists():
            return p
    return None


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    p = _font_path(bold)
    if p is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(p, size)
    except Exception:
        return ImageFont.load_default()


def has_jp_font() -> bool:
    return _font_path() is not None


# ── 架空名刺の中身 ────────────────────────────────────────────────────────────

@dataclass
class CardSpec:
    """1 枚の名刺に載せる内容。値はすべて架空。"""
    name: str = "山田 太郎"
    name_kana: str = ""
    name_roman: str = ""
    company: str = "株式会社サンプル商会"
    department: str = "営業部"
    title: str = "部長"
    postal: str = "〒100-0001"
    address: str = "東京都千代田区千代田1-2-3 サンプルビル5F"
    tel: str = "TEL 03-1234-5678"
    mobile: str = "携帯 090-1234-5678"
    fax: str = "FAX 03-1234-5679"
    email: str = "taro.yamada@example.jp"
    url: str = "https://www.example.jp"
    vertical: bool = False
    bg: tuple[int, int, int] = (255, 255, 255)
    fg: tuple[int, int, int] = (26, 26, 26)
    accent: tuple[int, int, int] = (60, 90, 70)
    name_size: int = 62
    logo: bool = True
    extra: list[str] = field(default_factory=list)


def draw_vertical(d: ImageDraw.ImageDraw, xy, text: str, font, fill, gap: float = 0.10) -> float:
    """縦書きで 1 文字ずつ積む。戻り値は次に書ける y。

    日本語の縦書きは字送りが一定（全角幅）なので、等間隔に積めば実物に近くなる。
    """
    x, y = xy
    size = getattr(font, "size", 20)
    step = size * (1.0 + gap)
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        y += step
    return y


def render_vertical_card(spec: "CardSpec") -> Image.Image:
    """縦書きの縦型名刺。右から左へ、社名・氏名・連絡先の順に並べる。

    伝統的な日本の名刺でよくある組み方。横書きの名刺とは OCR のかかり方が
    まったく違うので、専用のフィクスチャとして用意する。
    """
    w, h = CARD_H, CARD_W          # 縦型
    img = Image.new("RGB", (w, h), spec.bg)
    d = ImageDraw.Draw(img)
    pad = 52

    # 右端: 会社名
    x = w - pad - 30
    draw_vertical(d, (x, pad), spec.company, font(30, bold=True), spec.fg)

    # 中央: 部署・役職 と 氏名（氏名がいちばん大きい）
    x -= 62
    y = draw_vertical(d, (x, pad + 20), spec.department + " " + spec.title, font(22), spec.fg)
    x -= 58
    draw_vertical(d, (x, pad + 30), spec.name.replace(" ", ""), font(46, bold=True), spec.fg)

    # 左側: 住所と連絡先（縦書き）
    x = pad + 150
    draw_vertical(d, (x, pad), spec.postal + spec.address, font(17), spec.fg)
    x -= 34
    draw_vertical(d, (x, pad), spec.tel, font(17), spec.fg)
    x -= 34
    draw_vertical(d, (x, pad), spec.fax, font(17), spec.fg)
    x -= 34
    draw_vertical(d, (x, pad), spec.mobile, font(17), spec.fg)

    # メールと URL は縦書きにしない（実物でも横書きのことが多い）
    d.text((pad, h - pad - 40), spec.email, font=font(16), fill=spec.fg)
    d.text((pad, h - pad - 18), spec.url, font=font(16), fill=spec.fg)
    return img


def render_card(spec: CardSpec) -> Image.Image:
    """名刺そのもの（正対・余白なし）を描く。"""
    w, h = (CARD_H, CARD_W) if spec.vertical else (CARD_W, CARD_H)
    img = Image.new("RGB", (w, h), spec.bg)
    d = ImageDraw.Draw(img)

    if spec.logo:
        # ロゴ代わりの図形。文字ではないので OCR に拾わせたくない対象。
        d.ellipse([w - 150, 40, w - 60, 130], fill=spec.accent)
        d.rectangle([w - 130, 62, w - 80, 108], fill=spec.bg)

    pad = 56
    y = pad

    d.text((pad, y), spec.company, font=font(34, bold=True), fill=spec.fg)
    y += 52
    d.line([pad, y, w - pad, y], fill=spec.accent, width=3)
    y += 26

    line = " ".join(x for x in (spec.department, spec.title) if x)
    if line:
        d.text((pad, y), line, font=font(26), fill=spec.fg)
        y += 40

    if spec.name_kana:
        d.text((pad, y), spec.name_kana, font=font(20), fill=(110, 110, 110))
        y += 28

    d.text((pad, y), spec.name, font=font(spec.name_size, bold=True), fill=spec.fg)
    y += spec.name_size + 12

    if spec.name_roman:
        d.text((pad, y), spec.name_roman, font=font(22), fill=(110, 110, 110))
        y += 34

    y = max(y + 10, h - 190)
    small = font(21)
    for text in [
        f"{spec.postal} {spec.address}".strip(),
        "  ".join(x for x in (spec.tel, spec.fax) if x),
        spec.mobile,
        spec.email,
        spec.url,
        *spec.extra,
    ]:
        if not text.strip():
            continue
        d.text((pad, y), text, font=small, fill=spec.fg)
        y += 29

    return img


# ── 背景・撮影条件のシミュレーション ──────────────────────────────────────────

def wood_background(w: int, h: int, seed: int = 0) -> Image.Image:
    """木目机。縦縞＋ノイズ。名刺の誤検出を誘う背景として使う。"""
    rng = np.random.default_rng(seed)
    base = np.zeros((h, w, 3), dtype=np.float32)
    grain = np.zeros((h, w), dtype=np.float32)
    for _ in range(34):
        x = rng.integers(0, w)
        width = rng.integers(3, 22)
        amp = rng.uniform(0.05, 0.22)
        xs = np.arange(w)
        grain += amp * np.exp(-((xs - x) ** 2) / (2.0 * width ** 2))[None, :]
    grain += rng.normal(0, 0.02, size=(h, w))
    wave = 0.04 * np.sin(np.arange(h)[:, None] / 9.0)
    tone = np.clip(0.52 + grain + wave, 0, 1)
    base[:, :, 0] = tone * 120 + 35   # B
    base[:, :, 1] = tone * 150 + 45   # G
    base[:, :, 2] = tone * 185 + 55   # R
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def plain_background(w: int, h: int, color=(228, 228, 232)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _perspective_coeffs(src, dst):
    """PIL の Image.PERSPECTIVE 用係数（dst→src の射影変換）を解く。"""
    matrix = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    a = np.array(matrix, dtype=np.float64)
    b = np.array(src, dtype=np.float64).reshape(8)
    return np.linalg.solve(a, b)


def place_on_background(
    card: Image.Image,
    bg: Image.Image,
    scale: float = 0.62,
    rotate_deg: float = 0.0,
    tilt: float = 0.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> tuple[Image.Image, list[tuple[float, float]]]:
    """名刺を背景へ合成し、合成後の四隅座標を返す。

    scale  : 背景幅に対する名刺の幅の比
    rotate : 面内回転（度）
    tilt   : 台形の強さ 0-0.35（上辺を縮めて奥に倒す）
    offset : 中心からのずれ（背景サイズに対する比）
    """
    bw, bh = bg.size
    target_w = bw * scale
    ratio = card.height / card.width
    target_h = target_w * ratio
    card = card.resize((int(target_w), int(target_h)), Image.LANCZOS)

    cw, ch = card.size
    pad = int(max(cw, ch) * 0.5)
    canvas = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
    canvas.paste(card.convert("RGBA"), (pad, pad))
    corners = [
        (pad, pad),
        (pad + cw - 1, pad),
        (pad + cw - 1, pad + ch - 1),
        (pad, pad + ch - 1),
    ]

    if tilt > 0:
        shrink = cw * tilt / 2.0
        dst = [
            (pad + shrink, pad),
            (pad + cw - 1 - shrink, pad),
            (pad + cw - 1, pad + ch - 1),
            (pad, pad + ch - 1),
        ]
        coeffs = _perspective_coeffs(corners, dst)
        canvas = canvas.transform(canvas.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
        corners = dst

    if rotate_deg:
        before = canvas.size
        canvas = canvas.rotate(rotate_deg, resample=Image.BICUBIC, expand=True)
        # rotate(expand=True) は中心回転 → 新しい中心へのオフセットで座標を追う
        rad = math.radians(rotate_deg)
        cx0, cy0 = before[0] / 2.0, before[1] / 2.0
        cx1, cy1 = canvas.size[0] / 2.0, canvas.size[1] / 2.0
        rotated = []
        for x, y in corners:
            dx, dy = x - cx0, y - cy0
            rx = dx * math.cos(rad) + dy * math.sin(rad)
            ry = -dx * math.sin(rad) + dy * math.cos(rad)
            rotated.append((rx + cx1, ry + cy1))
        corners = rotated

    ox = int((bw - canvas.size[0]) / 2 + offset[0] * bw)
    oy = int((bh - canvas.size[1]) / 2 + offset[1] * bh)
    out = bg.convert("RGBA")
    out.alpha_composite(canvas, (ox, oy))
    corners = [(x + ox, y + oy) for x, y in corners]
    return out.convert("RGB"), corners


def add_glare(img: Image.Image, strength: float = 0.9, center=(0.45, 0.4), radius=0.22):
    """光の反射（白飛び）を乗せる。"""
    w, h = img.size
    arr = np.asarray(img).astype(np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = center[0] * w, center[1] * h
    r = radius * min(w, h)
    g = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * r * r))) * (255 * strength)
    arr += g[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def add_blur(img: Image.Image, radius: float = 2.5) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def scale_brightness(img: Image.Image, factor: float) -> Image.Image:
    arr = np.asarray(img).astype(np.float32) * factor
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def simulate_camera(img: Image.Image, white: int = 238, sigma: float = 1.5, seed: int = 3) -> Image.Image:
    """実機カメラの応答を粗くまねる。

    合成画像の紙は 255 ちょうどになるが、実際のカメラは自動露出で白い紙を 230-245
    あたりに収める（飽和させない）。255 のままだと「白い紙」と「白飛び」が区別できず、
    glare 判定のテストとして成立しないので、ここで一度階調を詰めて微小ノイズを乗せる。
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32) * (white / 255.0)
    arr += rng.normal(0, sigma, size=arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def add_noise(img: Image.Image, sigma: float = 4.0, seed: int = 1) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.float32)
    arr += rng.normal(0, sigma, size=arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# ── パターン定義 ──────────────────────────────────────────────────────────────

SCENE_W, SCENE_H = 1280, 720


def _scene(card: Image.Image, bg: Image.Image, **kw):
    return place_on_background(card, bg, **kw)


def build(name: str) -> tuple[Image.Image, list[tuple[float, float]] | None, CardSpec | None]:
    """パターン名から (画像, 名刺四隅 or None, 内容 or None) を作る。

    四隅が None のものは「名刺が写っていない/検出できなくてよい」ケース。
    返す画像はすべて simulate_camera() を通してあり、実機に近い階調になっている。
    """
    img, quad, spec = _build_raw(name)
    img = simulate_camera(img)
    if name == "glare":
        # 反射はセンサーで飽和する現象なので、カメラ応答を通したあとに乗せる。
        # 先に乗せると simulate_camera の階調圧縮で飽和が消えてしまう。
        img = add_glare(img, strength=0.95, center=(0.44, 0.46), radius=0.16)
    return img, quad, spec


def _build_raw(name: str):
    plain = plain_background(SCENE_W, SCENE_H)
    wood = wood_background(SCENE_W, SCENE_H, seed=7)

    if name == "landscape_ja":
        spec = CardSpec()
        return (*_scene(render_card(spec), plain), spec)

    if name == "portrait_ja":
        spec = CardSpec(
            vertical=True,
            company="有限会社きらめき工房",
            name="鈴木 花子",
            department="制作課",
            title="主任",
            email="hanako.suzuki@sample.co.jp",
            url="https://sample.co.jp",
            name_size=54,
        )
        return (*_scene(render_card(spec), plain, scale=0.22), spec)

    if name == "mixed_ja_en":
        spec = CardSpec(
            company="合同会社ミライデザイン / Mirai Design LLC",
            name="佐藤 健一",
            name_roman="KENICHI SATO",
            department="開発本部",
            title="マネージャー",
            email="k.sato@example.com",
            url="https://example.com",
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "english_only":
        spec = CardSpec(
            company="Northwind Analytics, Inc.",
            name="Alex Morgan",
            department="Sales Division",
            title="Director",
            postal="",
            address="1200 Example Street, Springfield",
            tel="TEL +81-3-1234-5678",
            mobile="Mobile +81-90-1234-5678",
            fax="FAX +81-3-1234-5679",
            email="alex.morgan@example.com",
            url="https://www.example.com",
            logo=False,
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "white_card":
        spec = CardSpec(bg=(255, 255, 255), fg=(20, 20, 20), logo=False)
        return (*_scene(render_card(spec), plain_background(SCENE_W, SCENE_H, (246, 246, 248))), spec)

    if name == "colored_card":
        spec = CardSpec(
            bg=(28, 48, 40), fg=(238, 238, 232), accent=(196, 164, 96),
            company="株式会社あおば技研", name="高橋 美咲",
            department="総務課", title="課長",
            email="misaki.takahashi@example.jp",
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "wood_background":
        spec = CardSpec()
        return (*_scene(render_card(spec), wood), spec)

    if name == "skewed":
        spec = CardSpec()
        return (*_scene(render_card(spec), plain, rotate_deg=11.0, tilt=0.16), spec)

    if name == "glare":
        # 反射そのものは build() 側でカメラ応答のあとに乗せる。ここでは素の場面を返す。
        spec = CardSpec()
        return (*_scene(render_card(spec), plain), spec)


    if name == "blurry":
        spec = CardSpec()
        img, quad = _scene(render_card(spec), plain)
        return add_blur(img, 3.2), quad, spec

    if name == "dark":
        spec = CardSpec()
        img, quad = _scene(render_card(spec), plain)
        # 実機の暗所は必ずセンサノイズが乗る。ノイズ無しの線形減光だけだと
        # 現実より検出しやすくなってしまうので一緒に乗せる。
        return add_noise(scale_brightness(img, 0.18), sigma=3.0, seed=5), quad, spec

    if name == "too_small":
        spec = CardSpec()
        return (*_scene(render_card(spec), plain, scale=0.20), spec)

    if name == "multi_phone":
        spec = CardSpec(
            tel="TEL 03-1234-5678 / 03-1234-5670",
            mobile="携帯 080-9876-5432",
            fax="FAX 03-1234-5679",
            extra=["直通 03-1234-5671"],
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "no_corporate_suffix":
        spec = CardSpec(
            company="あおぞらクリエイティブ",
            name="伊藤 直樹",
            department="企画部",
            title="リーダー",
            email="naoki.ito@aozora-creative.example.jp",
            url="https://aozora-creative.example.jp",
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "small_name":
        spec = CardSpec(name="渡辺 三郎", name_size=26, email="saburo.watanabe@example.jp")
        return (*_scene(render_card(spec), plain), spec)

    if name == "with_kana":
        spec = CardSpec(
            name="中村 優子", name_kana="なかむら ゆうこ",
            name_roman="YUKO NAKAMURA",
            email="yuko.nakamura@example.jp",
        )
        return (*_scene(render_card(spec), plain), spec)

    if name == "vertical_writing":
        spec = CardSpec(
            company="株式会社松風堂",
            name="小林 誠",
            department="営業部",
            title="部長",
            postal="〒100-0001",
            address="東京都千代田区千代田一ノ二ノ三",
            tel="TEL 03-1234-5678",
            fax="FAX 03-1234-5679",
            mobile="携帯 090-1234-5678",
            email="makoto.kobayashi@example.jp",
            url="https://example.jp",
        )
        return (*place_on_background(render_vertical_card(spec), plain, scale=0.24), spec)

    if name == "not_a_card_paper":
        # 名刺ではない A4 の紙（縦横比が違う）。検出されてはいけない。
        paper = Image.new("RGB", (1240, 1754), (252, 252, 250))
        d = ImageDraw.Draw(paper)
        f = font(40)
        for i in range(18):
            d.text((90, 120 + i * 64), "ご案内　サンプル文書　" * 2, font=f, fill=(40, 40, 40))
        img, _ = place_on_background(paper, plain, scale=0.45)
        return img, None, None

    if name == "not_a_card_phone":
        # スマートフォンの画面（黒縁・縦長）。検出されてはいけない。
        phone = Image.new("RGB", (720, 1480), (12, 12, 14))
        d = ImageDraw.Draw(phone)
        d.rounded_rectangle([28, 90, 692, 1390], radius=16, fill=(250, 250, 252))
        f = font(34)
        for i in range(14):
            d.text((70, 150 + i * 70), "サンプル表示テキスト", font=f, fill=(30, 30, 30))
        # 画面内に収まる大きさで置く。見切れると縦横比が変わり「名刺ではない」判定の
        # テストにならないため、高さが SCENE_H に収まる倍率にしている。
        img, _ = place_on_background(phone, plain, scale=0.22)
        return img, None, None

    if name == "held_in_hand":
        # 手に持って差し出した名刺。実機のキオスクではこれがいちばん多い持ち方で、
        # 実際の録画ではこの状態が検出できない最大の原因だった。
        #
        # 壊れ方はこうなる。名刺の縁は背景との明暗差で出るが、指が縁をまたぐと
        # そこだけ「名刺 → 指 → 背景」になる。指は紙に近い明るさなので
        # 名刺と指の間に強いエッジが立たず、輪郭は指の外側を回って閉じる。
        # つまり輪郭は「名刺 ∪ 手」の形になり、長方形ではなくなる。
        # 肌の色の境目をエッジとして足すと、指は名刺の縁で切れて長方形に戻る。
        spec = CardSpec()
        card = render_card(spec)
        scene, quad = place_on_background(
            card, plain_background(SCENE_W, SCENE_H, (170, 168, 164)))
        d = ImageDraw.Draw(scene)
        x0, y0 = quad[0]
        x1, y1 = quad[2]
        skin = (252, 228, 206)          # 明るい照明下の手。紙との明暗差は小さい
        # 手のひら: 名刺の下辺の裏から出て画面の下へ抜ける
        d.ellipse([x0 + 150, y1 - 30, x1 - 120, y1 + 260], fill=skin)
        # 指先: 下辺をまたいで名刺の内側まで少し入る
        for k in range(4):
            fx = x0 + 210 + k * 150
            d.rounded_rectangle([fx, y1 - 70, fx + 96, y1 + 120], radius=46, fill=skin)
        # 親指: 左下の角を表からつまむ
        d.rounded_rectangle([x0 - 20, y1 - 190, x0 + 92, y1 + 90], radius=54, fill=skin)
        return scene, quad, spec

    if name == "blank_card":
        # 名刺と同じ大きさ・縦横比の無地の紙。四角形の判定だけでは弾けないので、
        # 「内部に文字らしい領域がある」条件が効いているかを確かめるためのケース。
        # 四隅は返す（検出されてはいけないが、テストが「その領域に文字が無い」ことを
        # 直接確かめられるように）。NOT_A_CARD の判定側は四隅を見ていない。
        blank = Image.new("RGB", (CARD_W, CARD_H), (252, 251, 248))
        return (*place_on_background(blank, wood), None)

    if name == "empty_desk":
        return wood, None, None

    raise KeyError(name)


PATTERNS = [
    "landscape_ja", "portrait_ja", "mixed_ja_en", "english_only",
    "white_card", "colored_card", "wood_background", "skewed",
    "glare", "blurry", "dark", "too_small",
    "multi_phone", "no_corporate_suffix", "small_name", "with_kana", "vertical_writing",
    "held_in_hand",
    "not_a_card_paper", "not_a_card_phone", "blank_card", "empty_desk",
]


def write_all(out_dir: Path = FIXTURE_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in PATTERNS:
        img, _quad, _spec = build(name)
        p = out_dir / f"{name}.png"
        img.save(p)
        written.append(p)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="架空名刺のテスト画像を生成する")
    ap.add_argument("--list", action="store_true", help="パターン名を表示して終了")
    ap.add_argument("--out", default=str(FIXTURE_DIR))
    args = ap.parse_args()

    if args.list:
        for p in PATTERNS:
            print(p)
        return 0

    if not has_jp_font():
        print("warning: 日本語フォントが見つかりません。日本語は描画されません。", file=sys.stderr)
    paths = write_all(Path(args.out))
    print(f"{len(paths)} files -> {Path(args.out)}")
    return 0


if __name__ == "__main__":
    random.seed(0)
    raise SystemExit(main())
