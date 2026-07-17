#!/usr/bin/env bash
# キオスクのタップ操作音を生成するスクリプト（要 ffmpeg / curl）。
#
# 音源: VSQ plus+ のフリー効果音「木琴 ５」(VSQSE_1128_xylophone_05.mp3) の
#   フレーズ最後の 1 音（後続音のない綺麗な単音）を抽出したもの。
#     一覧  : https://vsq.co.jp/plus/sound/category_sub/xylophone/
#     規約  : https://vsq.co.jp/plus/tos/
#             商用・非商用ともに無料で利用可・加工可・クレジット任意。
#             ただし「オリジナルのままの再配布・販売」は禁止のため、本リポジトリには
#             加工済み（単音を切り出し・整音した）tap_source.mp3 のみを収録する。
#   磯野木工所の和モダン（木工所）ブランドに合わせ、木の打楽器＝木琴の単音（C6, 約1050Hz）を
#   0.5 秒に切り出した乾いた「コツッ」というタップ音。
#
# 使い方: このディレクトリで  bash gen_tap.sh
#   → assets/tap_source.mp3 (ソース) と ../static/tap.mp3 (配信用) を更新する。
#   静的ファイル static/tap.mp3 が実際にキオスクへ OTA 配信される（BUNDLE_FILES 登録済み）。
set -e
cd "$(dirname "$0")"

SRC_URL="https://vsq.co.jp/plus/wordpress/wp-content/uploads/2021/07/VSQSE_1128_xylophone_05.mp3"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -sL -A "Mozilla/5.0" "$SRC_URL" -o "$TMP/xylophone_05.mp3"

# フレーズ最後の単音（onset≈0.833s）を 0.5 秒だけ切り出し、頭 3ms / 尻 100ms をフェード。
ffmpeg -hide_banner -loglevel error -i "$TMP/xylophone_05.mp3" \
  -af "atrim=0.8215:1.3215,asetpts=PTS-STARTPTS,\
afade=t=in:st=0:d=0.003,afade=t=out:st=0.40:d=0.10" \
  -ar 44100 -ac 2 -b:a 160k -y "$TMP/cut.mp3"

# ピークを -4.5dB へ正規化（打楽器としての存在感。音量はキオスク側スライダーで別途調整可）。
max=$(ffmpeg -hide_banner -i "$TMP/cut.mp3" -af volumedetect -f null - 2>&1 \
      | grep max_volume | grep -oE '\-?[0-9.]+ dB' | grep -oE '\-?[0-9.]+')
gain=$(awk "BEGIN{printf \"%.1f\", -4.5-($max)}")
ffmpeg -hide_banner -loglevel error -i "$TMP/cut.mp3" -af "volume=${gain}dB" \
  -ar 44100 -ac 2 -b:a 160k -y "tap_source.mp3"

cp "tap_source.mp3" "../static/tap.mp3"
echo "generated assets/tap_source.mp3 and copied to ../static/tap.mp3"
