#!/bin/bash
# mokuture+ Kiosk Agent - Raspberry Pi setup script
set -e

AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="mokuture-kiosk"
VENV="$AGENT_DIR/.venv"

echo "=== mokuture+ Kiosk Agent Install ==="
echo "Directory: $AGENT_DIR"

cd "$AGENT_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip

# 依存の導入。名刺読み取り(card)は任意。入らなくてもキオスク本体は動くので、
# 段階的に諦めながら進める: rpi+card → card → rpi → 最小。
# 各試行の出力はログに残す。捨てると「4回とも黙って失敗し、最後の1回だけ素の
# エラーを吐いて set -e で止まる」状態になり、本当の原因が読めなくなる。
CARD_DEPS_OK=0
PIP_LOG="$AGENT_DIR/.install-pip.log"
: > "$PIP_LOG"

try_pip() {   # try_pip <extras表記> ; 成否を終了コードで返す
    echo "--- pip install -e \"$1\" ---" >> "$PIP_LOG"
    "$VENV/bin/pip" install -e "$1" >> "$PIP_LOG" 2>&1
}

if try_pip ".[rpi,card]"; then
    CARD_DEPS_OK=1
elif try_pip ".[card]"; then
    CARD_DEPS_OK=1
    echo "  -> GPIO ライブラリが入らなかった(Pi 以外の環境か)。ハードはモックで動く"
elif try_pip ".[rpi]"; then
    echo "  -> 名刺読み取りの依存(opencv/onnxruntime)が入らなかった"
elif try_pip "."; then
    echo "  -> 名刺読み取りの依存が入らなかった"
else
    echo ""
    echo "依存パッケージを導入できなかった。最後の試行の出力(末尾40行):"
    echo "---------------------------------------------------------------"
    tail -40 "$PIP_LOG"
    echo "---------------------------------------------------------------"
    echo "全文: $PIP_LOG"
    exit 1
fi

# 名刺 OCR のモデル取得。導入時のみネットワークを使う(以後は完全オフライン)。
if [ "$CARD_DEPS_OK" = "1" ]; then
    echo "Fetching OCR models for business card reading..."
    if "$VENV/bin/python" "$AGENT_DIR/scripts/fetch_ocr_models.py"; then
        echo "  -> OCR models ready"
    else
        echo "  -> モデルを取得できなかった。名刺読み取りは無効のまま起動する"
        echo "     あとで再実行: $VENV/bin/python $AGENT_DIR/scripts/fetch_ocr_models.py"
        echo "     代替(Tesseract): sudo apt install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-eng"
        echo "                      card_reader.yaml に ocr.engine: tesseract を書く"
    fi
else
    echo "名刺読み取りは無効(依存パッケージ未導入)。キオスク本体はこのまま動く。"
    echo "  あとで有効化するには README.md の「名刺読み取り」を参照"
fi

# かな漢字変換の全面辞書(SKK-JISYO.L)を取得。無くても同梱 kana_dict.tsv で動くが、
# 姓名・一般語を網羅するには推奨(実験: 漢字変換入力。IME-EXPERIMENT.md 参照)。
if [ ! -f "$AGENT_DIR/SKK-JISYO.L" ]; then
    echo "Fetching SKK-JISYO.L (kana→kanji dictionary)..."
    if curl -fsSL -o "$AGENT_DIR/SKK-JISYO.L.gz" https://skk-dev.github.io/dict/SKK-JISYO.L.gz; then
        gunzip -f "$AGENT_DIR/SKK-JISYO.L.gz" && echo "  -> SKK-JISYO.L ready" \
            || echo "  -> gunzip failed (falling back to bundled kana_dict.tsv)"
    else
        echo "  -> download failed (falling back to bundled kana_dict.tsv)"
        rm -f "$AGENT_DIR/SKK-JISYO.L.gz"
    fi
fi

if [ ! -f "$AGENT_DIR/.env" ]; then
    cat > "$AGENT_DIR/.env" <<EOF
REMOTE_API_URL=https://mokuture-plus-api.onrender.com/api
MEDIA_DIR=$HOME/kiosk-media
PORT=8080
SYNC_INTERVAL_SEC=60
MOCK_GPIO=false
PIR_PIN=4
DOOR_PINS_JSON={"1": 12, "2": 16, "3": 26}
LOCKER_PINS_JSON={"1": 14, "2": 15, "3": 18}
LOCKER_PULSE_SEC=1.0
CAMERA_DEVICE=/dev/video0
EOF
    echo "Created $AGENT_DIR/.env"
fi

sed "s|AGENT_DIR|$AGENT_DIR|g; s|VENV|$VENV|g; s|USER|$USER|g" \
    "$AGENT_DIR/mokuture-kiosk.service" \
    | sudo tee /etc/systemd/system/"$SERVICE_NAME".service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "=== Install Complete ==="
echo "Status : sudo systemctl status $SERVICE_NAME"
echo "Logs   : journalctl -u $SERVICE_NAME -f"
echo ""
echo "Voice input (experimental — QR無し来訪者の受付フォームを声で埋める):"
echo "  Setup  : bash $AGENT_DIR/scripts/install_voice.sh"
echo "           (USB マイクを挿してから。whisper.cpp のビルドに 3〜6 分)"
echo "  Status : curl -s http://127.0.0.1:8181/voice/status"
echo "  未セットアップなら画面に「音声で入力」は出ず、受付は従来どおり動く。"
echo ""
echo "Business card reading:"
echo "  Status : curl -s http://localhost:8080/card/status"
echo "  Models : $VENV/bin/python $AGENT_DIR/scripts/fetch_ocr_models.py --check"
echo "  Tuning : cp card_reader.yaml.example card_reader.yaml  (編集後に systemctl restart)"
echo "  Bench  : $VENV/bin/python $AGENT_DIR/scripts/bench.py --image <撮影した名刺>.jpg"
echo ""
echo "Next steps:"
echo "  1. Open Chromium in kiosk mode (the kiosk self-registers on load):"
echo "       chromium-browser --kiosk http://localhost:8080"
echo "  2. The screen will show '承認待ちです'. In the admin panel,"
echo "     go to キオスク端末 and click 承認する to activate this device (no PIN needed)."
echo "  3. (Optional) trigger registration manually:"
echo "       curl -X POST http://localhost:8080/register"
