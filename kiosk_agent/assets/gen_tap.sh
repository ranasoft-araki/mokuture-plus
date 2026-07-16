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

TONE="0.30*sin(2*PI*1200*t)*exp(-2.8*t)\
+0.35*sin(2*PI*2400*t+0.10*sin(2*PI*6.0*t))*exp(-3.2*t)\
+0.25*sin(2*PI*3600*t+0.12*sin(2*PI*6.5*t))*exp(-3.5*t)\
+0.15*sin(2*PI*4800*t)*exp(-4.0*t)\
+0.08*sin(2*PI*600*t)*exp(-3.0*t)"

ffmpeg -hide_banner -loglevel error \
  -f lavfi -i "aevalsrc=${TONE}:s=44100:d=1.5" \
  -af "\
afade=t=in:st=0:d=0.02:curve=ipar,\
afade=t=out:st=0.45:d=0.40,\
highpass=f=400,\
lowpass=f=5000,\
aecho=0.3:0.25:60:0.08,\
volume=-2dB,alimiter=limit=0.75" \
  -ar 44100 -b:a 128k -y "tap_source.mp3"

cp "tap_source.mp3" "../static/tap.mp3"
echo "generated assets/tap_source.mp3 and copied to ../static/tap.mp3"
