#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XRAY_ZIP="$ROOT_DIR/xray/Xray-linux-64.zip"
XRAY_DIR="$ROOT_DIR/xray/runtime"
CONFIG_PATH="$XRAY_DIR/config.json"
PRESET_CONFIG="$ROOT_DIR/xray/config.json"

if [ ! -f "$XRAY_ZIP" ]; then
    echo "Missing $XRAY_ZIP" >&2
    echo "Download the official Xray-linux-64.zip on a connected machine and put it there." >&2
    exit 1
fi

mkdir -p "$XRAY_DIR"
python3 - "$XRAY_ZIP" "$XRAY_DIR" <<'PY'
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
target = Path(sys.argv[2])
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(target)
PY

chmod +x "$XRAY_DIR/xray"

if [ -f "$PRESET_CONFIG" ]; then
    cp "$PRESET_CONFIG" "$CONFIG_PATH"
    echo "Installed preset config from: $PRESET_CONFIG"
elif [ ! -f "$CONFIG_PATH" ]; then
    cat > "$CONFIG_PATH" <<'JSON'
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "listen": "127.0.0.1",
      "port": 9050,
      "protocol": "socks",
      "settings": {
        "udp": true
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom",
      "settings": {}
    }
  ]
}
JSON
    echo "Created placeholder config: $CONFIG_PATH"
    echo "Replace outbounds with your real V2Ray/Xray config before starting Xray."
fi

echo "Xray installed at: $XRAY_DIR/xray"
echo "Config path: $CONFIG_PATH"
