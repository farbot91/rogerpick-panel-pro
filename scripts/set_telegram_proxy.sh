#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
    echo "Usage: ./scripts/set_telegram_proxy.sh socks5h://127.0.0.1:9050" >&2
    echo "Use an empty string only by editing project/web_panel_settings.json manually." >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/project"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

"$PYTHON_BIN" - "$1" <<'PY'
import json
import sys
from pathlib import Path

proxy_url = sys.argv[1].strip()
settings_path = Path("project/web_panel_settings.json")
settings = json.loads(settings_path.read_text(encoding="utf-8"))
settings["telegram_proxy_url"] = proxy_url
settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"telegram_proxy_url set to: {proxy_url}")
PY
