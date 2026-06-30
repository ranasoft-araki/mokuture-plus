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
"$VENV/bin/pip" install --quiet -e ".[rpi]" 2>/dev/null \
  || "$VENV/bin/pip" install --quiet -e .

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
echo "Next steps:"
echo "  1. Open the device setup flow and register the kiosk with a PIN."
echo "  2. Or register directly:"
echo "       curl -X POST http://localhost:8080/setup \\"
echo "            -H 'Content-Type: application/json' \\"
echo "            -d '{\"pin_code\":\"your-pin\"}'"
echo "  3. Open Chromium in kiosk mode:"
echo "       chromium-browser --kiosk http://localhost:8080"
