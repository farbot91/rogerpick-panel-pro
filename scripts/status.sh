#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/project/logs"

if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/nr-vpn-bot.service ]; then
    for unit in nr-vpn-bot nr-vpn-web-panel nr-vpn-cronjob nr-vpn-xray; do
        state="$(systemctl is-active "$unit.service" 2>/dev/null || true)"
        echo "$unit: ${state:-unknown}"
    done
    exit 0
fi

for name in bot web_panel cronjob xray; do
    pid_file="$LOG_DIR/$name.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "$name: running ($(cat "$pid_file"))"
    else
        echo "$name: stopped"
    fi
done
