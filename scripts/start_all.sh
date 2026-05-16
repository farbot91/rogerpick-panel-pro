#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/project"
VENV_DIR="$APP_DIR/.venv"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR" "$APP_DIR/runtime"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Virtualenv not found. Run ./install_offline.sh first." >&2
    exit 1
fi

if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/nr-vpn-bot.service ]; then
    systemctl start nr-vpn-bot.service nr-vpn-web-panel.service nr-vpn-cronjob.service
    echo "app services started with systemd:"
    echo "  nr-vpn-bot.service"
    echo "  nr-vpn-web-panel.service"
    echo "  nr-vpn-cronjob.service"
    echo "Panel default port: 5050"
    exit 0
fi

cd "$APP_DIR"

start_one() {
    local name="$1"
    local file="$2"
    if [ -f "$LOG_DIR/$name.pid" ] && kill -0 "$(cat "$LOG_DIR/$name.pid")" 2>/dev/null; then
        echo "$name already running: $(cat "$LOG_DIR/$name.pid")"
        return
    fi
    nohup "$VENV_DIR/bin/python" "$file" > "$LOG_DIR/$name.out.log" 2> "$LOG_DIR/$name.err.log" &
    echo $! > "$LOG_DIR/$name.pid"
    echo "$name started: $(cat "$LOG_DIR/$name.pid")"
}

start_one bot bot.py
start_one web_panel web_panel.py
start_one cronjob cronjob.py

echo "Panel default port: 5050"
