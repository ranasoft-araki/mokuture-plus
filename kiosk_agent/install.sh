#!/bin/bash
# mokuture+ Kiosk Agent — Raspberry Pi セットアップスクリプト
set -e

AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="mokuture-kiosk"
VENV="$AGENT_DIR/.venv"

echo "=== mokuture+ Kiosk Agent インストール ==="
echo "対象ディレクトリ: $AGENT_DIR"

# Python 仮想環境と依存パッケージ
cd "$AGENT_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# Raspberry Pi なら gpiozero 込みでインストール
"$VENV/bin/pip" install --quiet -e ".[rpi]" 2>/dev/null \
  || "$VENV/bin/pip" install --quiet -e .

# .env 雛形（未作成の場合のみ）
if [ ! -f "$AGENT_DIR/.env" ]; then
    cat > "$AGENT_DIR/.env" <<EOF
REMOTE_API_URL=https://mokuture-plus-api.onrender.com/api
DEVICE_TOKEN=
MEDIA_DIR=$HOME/kiosk-media
PORT=8080
SYNC_INTERVAL_SEC=60
MOCK_GPIO=false
PIR_PIN=4
LOCKER_PINS_JSON={}
EOF
    echo "→ .env を作成しました。DEVICE_TOKEN を設定してください。"
fi

# systemd サービス登録
sed "s|AGENT_DIR|$AGENT_DIR|g; s|VENV|$VENV|g; s|USER|$USER|g" \
    "$AGENT_DIR/mokuture-kiosk.service" \
    | sudo tee /etc/systemd/system/"$SERVICE_NAME".service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "=== インストール完了 ==="
echo "ステータス: sudo systemctl status $SERVICE_NAME"
echo "ログ確認 : journalctl -u $SERVICE_NAME -f"
echo ""
echo "次のステップ:"
echo "  1. $AGENT_DIR/.env の DEVICE_TOKEN を設定"
echo "  2. ロッカー GPIO ピン: LOCKER_PINS_JSON='{\"1\": 17, \"2\": 18}'"
echo "  3. Chromium 自動起動: chromium-browser --kiosk http://localhost:8080"
