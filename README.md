# Offline Ubuntu 24 Bundle

Offline-ready deployment bundle for the Telegram bot, web panel, and Xray-based proxy bootstrap flow.

## What is included

- Telegram bot
- Web admin panel
- Setup wizard for first-time installation
- Offline Python wheels
- Xray runtime and helper scripts

## Quick start

```bash
chmod +x setup.sh
SETUP_PORT=18080 ./setup.sh
```

Then open:

```text
http://SERVER_IP:18080
```

## Setup flow

The setup wizard is designed to:

- collect bot and admin settings
- accept Telegram proxy input as raw JSON or `vless://...`
- normalize proxy config automatically
- test proxy reachability
- prepare runtime settings
- start the services

## Important files

- `README_OFFLINE_UBUNTU24.md` - detailed offline installation notes
- `SERVER_RUN_COMMANDS.md` - common service commands
- `RELEASE_CHECKLIST.md` - pre-release and pre-push checklist
- `project/web_panel_settings.example.json` - example settings template

## Notes

- Runtime data, local database files, logs, and real settings are ignored by Git.
- Use the example settings file as the public template, not local production settings.
