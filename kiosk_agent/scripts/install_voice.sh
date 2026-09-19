#!/bin/bash
# mokuture+ 音声入力(実験導入) — Raspberry Pi セットアップ
#
#   bash scripts/install_voice.sh            # 一式(依存 → ビルド → systemd → 起動)
#   bash scripts/install_voice.sh --build    # whisper.cpp のビルドだけやり直す
#   bash scripts/install_voice.sh --no-apt   # apt を触らない(オフライン端末)
#
# ネットワークを使うのは apt とモデルの取り直しだけ。モデルの実体はリポジトリに
# Git LFS で入っているので、`git lfs pull` 済みなら取得は走らない。
# 導入が終われば音声認識は完全にオフラインで動く。
set -e

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$AGENT_DIR/.venv"
SERVICE_NAME="mokuture-voice"
WHISPER_VERSION="1.9.3"
WHISPER_SRC="$AGENT_DIR/vendor/whisper.cpp-${WHISPER_VERSION}.tar.gz"
WHISPER_DIR="$AGENT_DIR/vendor/whisper.cpp"
BUILD_ONLY=0
USE_APT=1

for arg in "$@"; do
    case "$arg" in
        --build)  BUILD_ONLY=1 ;;
        --no-apt) USE_APT=0 ;;
        *) echo "不明な引数: $arg"; exit 2 ;;
    esac
done

echo "=== mokuture+ 音声入力 セットアップ ==="
echo "ディレクトリ: $AGENT_DIR"

# ── 1. モデルの確認 ───────────────────────────────────────────────────────────
# LFS のポインタのままだと whisper がモデルを読めないので、先に気づけるようにする。
echo ""
echo "--- モデルの確認 ---"
if ! "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_voice_models.py" --check; then
    echo ""
    echo "モデルが揃っていません。まず次を試してください:"
    echo "    cd $(dirname "$AGENT_DIR") && git lfs pull"
    echo "それでも駄目なら取得し直します:"
    echo "    $VENV/bin/python $AGENT_DIR/scripts/fetch_voice_models.py"
    exit 1
fi

# ── 2. 依存パッケージ ─────────────────────────────────────────────────────────
if [ "$USE_APT" = "1" ] && [ "$BUILD_ONLY" = "0" ]; then
    echo ""
    echo "--- 依存パッケージ ---"
    MISSING=""
    command -v arecord >/dev/null 2>&1 || MISSING="$MISSING alsa-utils"
    command -v cmake   >/dev/null 2>&1 || MISSING="$MISSING cmake"
    command -v g++     >/dev/null 2>&1 || MISSING="$MISSING build-essential"
    if [ -n "$MISSING" ]; then
        echo "導入します:$MISSING"
        sudo apt-get update -qq
        sudo apt-get install -y $MISSING
    else
        echo "すべて導入済み"
    fi
fi

# ── 3. whisper.cpp のビルド ───────────────────────────────────────────────────
# バイナリは aarch64 専用になるためリポジトリには入れない。固定版のソース tarball
# (Git LFS 管理)から、この端末でビルドする。
echo ""
echo "--- whisper.cpp v$WHISPER_VERSION ---"
if [ -x "$WHISPER_DIR/build/bin/whisper-cli" ] && [ "$BUILD_ONLY" = "0" ]; then
    echo "ビルド済み: $WHISPER_DIR/build/bin/whisper-cli"
else
    if [ ! -d "$WHISPER_DIR" ] || [ "$BUILD_ONLY" = "1" ]; then
        echo "展開中..."
        rm -rf "$WHISPER_DIR" "$AGENT_DIR/vendor/whisper.cpp-$WHISPER_VERSION"
        tar xzf "$WHISPER_SRC" -C "$AGENT_DIR/vendor"
        mv "$AGENT_DIR/vendor/whisper.cpp-$WHISPER_VERSION" "$WHISPER_DIR"
    fi
    echo "ビルド中(Pi 5 で 3〜6 分かかります)..."
    # 静的リンクにして、サービスからどこで実行しても動くようにする。
    cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF \
        -DWHISPER_BUILD_TESTS=OFF \
        -DWHISPER_BUILD_SERVER=OFF \
        -DGGML_NATIVE=ON > /dev/null
    cmake --build "$WHISPER_DIR/build" -j "$(nproc)" --target whisper-cli
fi

if [ ! -x "$WHISPER_DIR/build/bin/whisper-cli" ]; then
    echo "whisper-cli ができていません。ビルドログを確認してください。"
    exit 1
fi
echo "OK: $("$WHISPER_DIR/build/bin/whisper-cli" --version 2>&1 | head -1 || echo whisper-cli)"

if [ "$BUILD_ONLY" = "1" ]; then
    echo ""
    echo "ビルドのみ実行しました。反映するには: sudo systemctl restart $SERVICE_NAME"
    exit 0
fi

# ── 4. Python 依存(任意) ────────────────────────────────────────────────────
# PyYAML は voice_input.yaml を読むのに使う。無ければ既定値のまま動く。
echo ""
echo "--- Python 依存 ---"
if "$VENV/bin/pip" install --quiet -e "$AGENT_DIR[voice]" 2>/dev/null; then
    echo "OK (voice extra)"
else
    echo "  -> 任意依存を入れられませんでした。既定値のまま動きます"
fi

# ── 4-2. Vosk のモデル ────────────────────────────────────────────────────────
# 一文の名乗り(受付の既定の入口)で使う。zip はリポジトリにあるので展開するだけ。
# 展開後は 48MB 程度。無くても whisper へ落ちるが、固有名詞の読みの精度が下がる。
echo ""
echo "--- Vosk のモデル ---"
if [ -d "$AGENT_DIR/voice_models/vosk-model-small-ja-0.22" ]; then
    echo "展開済み"
elif "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_voice_models.py" --extract; then
    echo "展開しました"
else
    echo "  -> 展開できませんでした。一文の名乗りは whisper で動きます(精度は下がります)"
fi

# ── 5. 設定ファイルとマイク ───────────────────────────────────────────────────
echo ""
echo "--- 設定 ---"
if [ ! -f "$AGENT_DIR/voice_input.yaml" ]; then
    cp "$AGENT_DIR/voice_input.yaml.example" "$AGENT_DIR/voice_input.yaml"
    echo "作成しました: $AGENT_DIR/voice_input.yaml"
fi

# 担当者の読み仮名。社員マスターに読みの欄が無いので端末側で補う。
# ここに載っていない担当者は音声では指名できない(読みの推測は禁止)。
if [ ! -f "$AGENT_DIR/staff_readings.yaml" ]; then
    cp "$AGENT_DIR/staff_readings.yaml.example" "$AGENT_DIR/staff_readings.yaml"
    echo "作成しました: $AGENT_DIR/staff_readings.yaml"
    echo "  ※ 中身は例のままです。管理画面の担当者名と読み仮名へ書き換えてください。"
fi
mkdir -p "$HOME/.mokuture-voice"

# ALSA を使うには audio グループが要る
if ! id -nG "$USER" | grep -qw audio; then
    echo "$USER を audio グループへ追加します(反映には再ログインが要ります)"
    sudo usermod -aG audio "$USER"
fi

echo ""
echo "接続されている録音デバイス:"
arecord -l 2>/dev/null | grep -E "^card" || echo "  見つかりません。USB マイクの接続を確認してください"

# ── 6. systemd ────────────────────────────────────────────────────────────────
echo ""
echo "--- systemd ---"
sed "s|AGENT_DIR|$AGENT_DIR|g; s|VENV|$VENV|g; s|HOME_DIR|$HOME|g; s|USER|$USER|g" \
    "$AGENT_DIR/mokuture-voice.service" \
    | sudo tee /etc/systemd/system/"$SERVICE_NAME".service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

echo ""
echo "=== 完了 ==="
echo "状態     : sudo systemctl status $SERVICE_NAME"
echo "ログ     : journalctl -u $SERVICE_NAME -f"
echo "利用可否 : curl -s http://127.0.0.1:8181/voice/status"
echo "マイク   : curl -s http://127.0.0.1:8181/voice/devices"
echo "速さの計測: $VENV/bin/python $AGENT_DIR/scripts/voice_bench.py --mic"
echo ""
curl -s -m 5 http://127.0.0.1:8181/voice/status 2>/dev/null | head -c 400 || \
    echo "まだ応答がありません。数秒おいて status を確認してください。"
echo ""
echo ""
echo "available:true になれば、受付フォームに「音声で入力」が出ます。"
echo "false のときは detail に理由が入っています(マイク未接続・モデル未取得など)。"
