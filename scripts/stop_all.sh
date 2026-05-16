#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/project/logs"

if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/nr-vpn-bot.service ]; then
    systemctl stop nr-vpn-bot.service nr-vpn-web-panel.service nr-vpn-cronjob.service nr-vpn-xray.service || true
fi

for name in bot web_panel cronjob xray; do
    pid_file="$LOG_DIR/$name.pid"
    if [ -f "$pid_file" ]; then
        pid="$(cat "$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "$name stopped: $pid"
        fi
        rm -f "$pid_file"
    fi
done
