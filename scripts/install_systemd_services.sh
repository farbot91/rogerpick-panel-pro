#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/project"
VENV_DIR="$APP_DIR/.venv"
XRAY_DIR="$ROOT_DIR/xray/runtime"
LOG_DIR="$APP_DIR/logs"
UNIT_DIR="/etc/systemd/system"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl not found; this host does not look like a systemd system." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root so it can write systemd units and update ufw." >&2
    echo "Example: sudo ./scripts/install_systemd_services.sh" >&2
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Virtualenv not found. Run ./install_offline.sh first." >&2
    exit 1
fi

if [ ! -x "$XRAY_DIR/xray" ]; then
    echo "Xray is not installed. Run ./scripts/install_xray_offline.sh first." >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$APP_DIR/runtime"

write_python_unit() {
    local unit_name="$1"
    local description="$2"
    local script_name="$3"
    cat > "$UNIT_DIR/$unit_name.service" <<UNIT
[Unit]
Description=$description
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=WEB_PANEL_SETTINGS=$APP_DIR/web_panel_settings.json
Environment=BOT_RUNTIME_DIR=$APP_DIR/runtime
ExecStart=$VENV_DIR/bin/python $script_name
Restart=always
RestartSec=5
StandardOutput=append:$LOG_DIR/$unit_name.out.log
StandardError=append:$LOG_DIR/$unit_name.err.log

[Install]
WantedBy=multi-user.target
UNIT
}

cat > "$UNIT_DIR/nr-vpn-xray.service" <<UNIT
[Unit]
Description=NR VPN local Xray Telegram proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$XRAY_DIR
ExecStart=$XRAY_DIR/xray run -config $XRAY_DIR/config.json
Restart=always
RestartSec=5
StandardOutput=append:$LOG_DIR/nr-vpn-xray.out.log
StandardError=append:$LOG_DIR/nr-vpn-xray.err.log

[Install]
WantedBy=multi-user.target
UNIT

write_python_unit "nr-vpn-bot" "NR VPN Telegram bot" "bot.py"
write_python_unit "nr-vpn-web-panel" "NR VPN web panel" "web_panel.py"
write_python_unit "nr-vpn-cronjob" "NR VPN cronjob" "cronjob.py"

systemctl daemon-reload
systemctl enable nr-vpn-xray.service nr-vpn-bot.service nr-vpn-web-panel.service nr-vpn-cronjob.service

if command -v ufw >/dev/null 2>&1; then
    ufw allow 5050/tcp || true
    ufw allow 8000/tcp || true
    echo "ufw rules added for tcp/5050 and tcp/8000."
else
    echo "ufw not found; firewall ports were not changed."
fi

echo "systemd services installed and enabled:"
echo "  nr-vpn-xray.service"
echo "  nr-vpn-bot.service"
echo "  nr-vpn-web-panel.service"
echo "  nr-vpn-cronjob.service"
