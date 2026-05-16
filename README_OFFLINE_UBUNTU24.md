# Offline Ubuntu 24 Deployment

This bundle is prepared for Ubuntu 24 with Python 3.12 on x86_64.

On the server:

```bash
cd offline_ubuntu24_bundle
chmod +x install_offline.sh scripts/*.sh
./scripts/install_xray_offline.sh
./install_offline.sh
sudo ./scripts/install_systemd_services.sh
./scripts/set_telegram_proxy.sh socks5h://127.0.0.1:9050
./scripts/start_xray.sh
./scripts/start_all.sh
```

Useful commands:

```bash
./scripts/status.sh
./scripts/stop_all.sh
tail -f project/logs/web_panel.err.log
tail -f project/logs/bot.err.log
```

The installer uses only local files from `wheels/` and never contacts the internet.

Systemd/autostart note:

- `install_systemd_services.sh` creates and enables `nr-vpn-bot`, `nr-vpn-web-panel`, `nr-vpn-cronjob`, and `nr-vpn-xray`.
- Services use `Restart=always`, so they restart after crashes and after server reboot.
- If `ufw` is installed, the script allows TCP ports `5050` for the web panel and `8000` for the setup wizard.
- `start_all.sh`, `stop_all.sh`, `status.sh`, and `start_xray.sh` use systemd when those services are installed, otherwise they fall back to the old `nohup` mode.

Telegram proxy note:

- Do not run the whole project with `proxychains`, because that would proxy 3x-ui/server API calls too.
- Put the same SOCKS proxy endpoint used by your proxychains config into `telegram_proxy_url` with `set_telegram_proxy.sh`.
- Telegram calls from `pyTelegramBotAPI` will use that proxy.
- Other HTTP calls use direct sessions and bypass environment proxies.

Xray/V2Ray client note:

If you already have a V2Ray config, run it as a local SOCKS proxy:

```bash
./scripts/install_xray_offline.sh
# edit xray/runtime/config.json and put your real outbound config there
./scripts/start_xray.sh
./scripts/set_telegram_proxy.sh socks5h://127.0.0.1:9050
./scripts/start_all.sh
```

`xray/runtime/config.json` must include a SOCKS inbound on `127.0.0.1:9050`.

Important: Ubuntu must already have `python3` version 3.12 available. If the server image does not include Python/venv support, install that on a connected machine or provide an OS-level offline package set separately.
