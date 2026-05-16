#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XRAY_DIR="$ROOT_DIR/xray/runtime"
LOG_DIR="$ROOT_DIR/project/logs"
mkdir -p "$LOG_DIR"

if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/nr-vpn-xray.service ]; then
    systemctl start nr-vpn-xray.service
    echo "xray started with systemd: nr-vpn-xray.service"
    echo "SOCKS proxy should be: socks5h://127.0.0.1:9050"
    exit 0
fi

if [ ! -x "$XRAY_DIR/xray" ]; then
    echo "Xray is not installed. Run ./scripts/install_xray_offline.sh first." >&2
    exit 1
fi

if [ -f "$LOG_DIR/xray.pid" ] && kill -0 "$(cat "$LOG_DIR/xray.pid")" 2>/dev/null; then
    echo "xray already running: $(cat "$LOG_DIR/xray.pid")"
    exit 0
fi

nohup "$XRAY_DIR/xray" run -config "$XRAY_DIR/config.json" > "$LOG_DIR/xray.out.log" 2> "$LOG_DIR/xray.err.log" &
echo $! > "$LOG_DIR/xray.pid"
echo "xray started: $(cat "$LOG_DIR/xray.pid")"
echo "SOCKS proxy should be: socks5h://127.0.0.1:9050"
