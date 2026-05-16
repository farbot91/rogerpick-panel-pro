#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

chmod +x install_offline.sh scripts/*.sh
./install_offline.sh
if [ "${TELEGRAM_PROXY_URL:-}" != "" ]; then
    ./scripts/set_telegram_proxy.sh "$TELEGRAM_PROXY_URL"
fi
./scripts/start_all.sh
./scripts/status.sh
