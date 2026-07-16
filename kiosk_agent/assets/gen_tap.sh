#!/usr/bin/env bash
# キオスクのタップ操作音を生成するスクリプト（要 ffmpeg）。
#
# Business22-3(High).mp3 を参考にしつつ、コピーではなく additive 合成で新規生成した
# 「ほわんとした淡い」音色。微ビブラートの揺らぎ・ゆっくりした立ち上がり・高域を大きく
# 丸めた暖かい低〜中域・淡いリバーブの広がりが特徴。
#
# 使い方: このディレクトリで  bash gen_tap.sh
#   → assets/tap_source.mp3 (ソース) と ../static/tap.mp3 (配信用) を更新する。
#   静的ファイル static/tap.mp3 が実際にキオスクへ OTA 配信される（BUNDLE_FILES 登録済み）。
set -e
cd "$(dirname "$0")"

TONE="0.22*sin(2*PI*325*t)*exp(-2.6*t)\
+0.42*sin(2*PI*650*t+0.12*sin(2*PI*5.0*t))*exp(-3.2*t)\
+0.40*sin(2*PI*975*t+0.14*sin(2*PI*5.3*t))*exp(-3.8*t)\
+0.30*sin(2*PI*976.5*t)*exp(-3.8*t)\
+0.10*sin(2*PI*1300*t)*exp(-5.0*t)"

ffmpeg -hide_banner -loglevel error \
  -f lavfi -i "aevalsrc=${TONE}:s=44100:d=1.5" \
  -af "\
afade=t=in:st=0:d=0.10:curve=ipar,\
afade=t=out:st=0.70:d=0.60,\
lowpass=f=2200,\
aecho=0.8:0.60:80|150|230|280:0.20|0.13|0.08|0.05,\
volume=-2dB,alimiter=limit=0.72" \
  -ar 44100 -b:a 128k -y "tap_source.mp3"

cp "tap_source.mp3" "../static/tap.mp3"
echo "generated assets/tap_source.mp3 and copied to ../static/tap.mp3"
