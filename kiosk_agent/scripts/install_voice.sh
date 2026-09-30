#!/bin/bash
# mokuture+ 声で操作する(実験導入) — Raspberry Pi セットアップ
#
#   bash scripts/install_voice.sh              # 一式(依存 → モデル → systemd → 起動)
#   bash scripts/install_voice.sh --no-apt     # apt を触らない
#   bash scripts/install_voice.sh --no-net     # 通信しない(モデルも取りに行かない)
#
# **モデルが揃っていなければ自分で取りに行く。** 取得元と SHA-256 はスクリプトに
# 固定してあるので git-lfs は要らない(リポジトリに Git LFS でも入っているが、
# `git lfs pull` 済みならそちらが使われ、取得は走らない)。
# 導入が終われば音声認識は完全にオフラインで動く。
set -e

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$AGENT_DIR/.venv"
SERVICE_NAME="mokuture-voice"
USE_APT=1
NO_NET=0

for arg in "$@"; do
    case "$arg" in
        --no-apt)    USE_APT=0 ;;
        --no-net)    NO_NET=1; USE_APT=0 ;;
        # 以前の手順書に残っている指定。いまは Vosk だけなので同じ動きになる。
        --vosk-only) ;;
        *) echo "不明な引数: $arg"; exit 2 ;;
    esac
done

echo "=== mokuture+ 声で操作する セットアップ ==="
echo "ディレクトリ: $AGENT_DIR"

# ── 1. モデルの確認 ───────────────────────────────────────────────────────────
echo ""
echo "--- モデルの確認 ---"
if ! "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_voice_models.py" --check; then
    # **揃っていなければ自分で取りに行く。**
    # モデルは取得元と SHA-256 が固定してあるので git-lfs は要らない。
    if [ "$NO_NET" = "1" ]; then
        echo ""
        echo "モデルが揃っていませんが、--no-net なので取得しません。"
        echo "  取得する: $VENV/bin/python $AGENT_DIR/scripts/fetch_voice_models.py"
        exit 1
    fi
    echo ""
    echo "揃っていないものを取得します(取得元と SHA-256 は固定。git-lfs は不要)..."
    if ! "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_voice_models.py"; then
        echo ""
        echo "モデルを取得できませんでした。ネットワークを確認してください。"
        exit 1
    fi
fi

# ── 2. 依存パッケージ ─────────────────────────────────────────────────────────
if [ "$USE_APT" = "1" ]; then
    echo ""
    echo "--- 依存パッケージ ---"
    if command -v arecord >/dev/null 2>&1; then
        echo "すべて導入済み"
    else
        echo "導入します: alsa-utils"
        sudo apt-get update -qq
        sudo apt-get install -y alsa-utils
    fi
fi

# ── 3. Python 依存 ────────────────────────────────────────────────────────────
# vosk(認識)と PyYAML(voice_input.yaml を読む)。
echo ""
echo "--- Python 依存 ---"
if "$VENV/bin/pip" install --quiet -e "$AGENT_DIR[voice]" 2>/dev/null; then
    echo "OK (voice extra)"
else
    echo "  -> 依存を入れられませんでした。$VENV/bin/pip install vosk を試してください"
fi

# ── 4. Vosk のモデル ──────────────────────────────────────────────────────────
# zip を展開するだけ。展開後は 48MB 程度。
echo ""
echo "--- Vosk のモデル ---"
if [ -d "$AGENT_DIR/voice_models/vosk-model-small-ja-0.22" ]; then
    echo "展開済み"
elif "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_voice_models.py" --extract; then
    echo "展開しました"
else
    echo "  -> 展開できませんでした。声で操作するは使えません(画面に出ないだけ)"
fi

# ── 5. 設定ファイルとマイク ───────────────────────────────────────────────────
echo ""
echo "--- 設定 ---"
if [ ! -f "$AGENT_DIR/voice_input.yaml" ]; then
    cp "$AGENT_DIR/voice_input.yaml.example" "$AGENT_DIR/voice_input.yaml"
    echo "作成しました: $AGENT_DIR/voice_input.yaml"
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
echo "話して試す: $VENV/bin/python $AGENT_DIR/scripts/voice_selftest.py --mic --screen top"
echo ""
curl -s -m 5 http://127.0.0.1:8181/voice/status 2>/dev/null | head -c 400 || \
    echo "まだ応答がありません。数秒おいて status を確認してください。"
echo ""
echo ""
echo "available:true になれば、画面下部の帯に「声で操作する」が出ます。"
echo "false のときは detail に理由が入っています(マイク未接続・モデル未取得など)。"
