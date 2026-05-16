#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        exec sudo -E bash "$0" "$@"
    fi
    echo "Setup needs root permissions for systemd and ufw changes." >&2
    exit 1
fi

chmod +x install_offline.sh bootstrap_offline.sh scripts/*.sh 2>/dev/null || true

HOST="${SETUP_HOST:-0.0.0.0}"
PORT="${SETUP_PORT:-8000}"

echo "Starting setup wizard..."
echo "Open: http://SERVER_IP:${PORT}"
echo "Local: http://127.0.0.1:${PORT}"

if command -v ufw >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    ufw allow "${PORT}/tcp" || true
fi

python3 "$ROOT_DIR/setup_wizard.py" --host "$HOST" --port "$PORT"
