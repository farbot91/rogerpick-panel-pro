#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/project"
WHEEL_DIR="$ROOT_DIR/wheels"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$APP_DIR/.venv"

echo "[1/5] Checking Python..."
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"Python 3.12 is required. Current: {sys.version}")
print(sys.version)
PY

echo "[2/5] Creating virtual environment..."
if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    rm -rf "$VENV_DIR"
    WHEEL_PATHS="$(printf ":%s" "$WHEEL_DIR"/*.whl)"
    PYTHONPATH="${WHEEL_PATHS#:}" "$PYTHON_BIN" -m virtualenv "$VENV_DIR" --no-download --extra-search-dir "$WHEEL_DIR"
fi

echo "[3/5] Installing Python packages from local wheels only..."
"$VENV_DIR/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" -r "$APP_DIR/requirements.txt"

echo "[4/5] Preparing runtime folders..."
mkdir -p "$APP_DIR/runtime" "$APP_DIR/logs"
chmod +x "$ROOT_DIR"/scripts/*.sh

echo "[5/5] Verifying imports and syntax..."
cd "$APP_DIR"
"$VENV_DIR/bin/python" -m py_compile app_settings.py database.py networking.py config.py bot.py web_panel.py cronjob.py

echo
echo "Offline install completed."
echo "Start services with: ./scripts/start_all.sh"
