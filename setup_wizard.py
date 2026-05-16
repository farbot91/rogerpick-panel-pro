#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR / "project"
SETTINGS_PATH = PROJECT_DIR / "web_panel_settings.json"
XRAY_CONFIG_PATH = ROOT_DIR / "xray" / "config.json"
SETUP_LOG_PATH = ROOT_DIR / "setup_wizard.log"
DEFAULT_PROXY_URL = "socks5h://127.0.0.1:9050"
TELEGRAM_API_IP_CANDIDATES = [
    "149.154.167.220",
    "149.154.167.99",
    "149.154.167.91",
    "149.154.167.92",
    "149.154.167.50",
    "149.154.167.51",
]

INSTALL_RUNNING = False
INSTALL_DONE = False
INSTALL_OK = False
INSTALL_LINES: list[str] = []
INSTALL_LOCK = threading.Lock()


def append_log(line: str) -> None:
    with INSTALL_LOCK:
        INSTALL_LINES.append(line.rstrip())
        INSTALL_LINES[:] = INSTALL_LINES[-600:]
    with SETUP_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line.rstrip() + "\n")


def read_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    example = PROJECT_DIR / "web_panel_settings.example.json"
    if example.exists():
        return json.loads(example.read_text(encoding="utf-8"))
    return {}


def write_settings(settings: dict) -> None:
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def telegram_socks_inbound() -> dict:
    return {
        "tag": "telegram-socks",
        "listen": "127.0.0.1",
        "port": 9050,
        "protocol": "socks",
        "settings": {"auth": "noauth", "udp": True},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
    }


def outbound_server_host(outbound: dict) -> str:
    stream = outbound.get("streamSettings", {}) if isinstance(outbound, dict) else {}
    tls_settings = stream.get("tlsSettings", {}) if isinstance(stream, dict) else {}
    reality_settings = stream.get("realitySettings", {}) if isinstance(stream, dict) else {}
    candidate = tls_settings.get("serverName") or reality_settings.get("serverName")
    if candidate:
        return str(candidate)

    settings_block = outbound.get("settings", {}) if isinstance(outbound, dict) else {}
    vnext = settings_block.get("vnext")
    if isinstance(vnext, list) and vnext:
        address = vnext[0].get("address")
        if address:
            return str(address)
    servers = settings_block.get("servers")
    if isinstance(servers, list) and servers:
        address = servers[0].get("address")
        if address:
            return str(address)
    return ""


def normalize_ws_transport(outbound: dict) -> None:
    stream = outbound.get("streamSettings")
    if not isinstance(stream, dict):
        return
    if str(stream.get("network") or "").lower() != "ws":
        return

    host = outbound_server_host(outbound)
    tls_settings = stream.setdefault("tlsSettings", {})
    if host and not tls_settings.get("serverName"):
        tls_settings["serverName"] = host

    ws_settings = stream.setdefault("wsSettings", {})
    ws_settings["path"] = ws_settings.get("path") or "/"
    headers = ws_settings.setdefault("headers", {})
    existing_host = ws_settings.get("host") or headers.get("Host")
    if host and not existing_host:
        headers["Host"] = host


def parse_vless_uri(raw_text: str) -> dict:
    raw_text = str(raw_text or "").strip()
    parsed = urlparse(raw_text)
    if parsed.scheme.lower() != "vless":
        raise ValueError("لینک واردشده از نوع VLESS نیست.")

    client_id = unquote(parsed.username or "").strip()
    address = (parsed.hostname or "").strip()
    port = parsed.port or 443
    if not client_id or not address:
        raise ValueError("لینک VLESS باید شناسه کاربر و آدرس سرور داشته باشد.")

    params = parse_qs(parsed.query, keep_blank_values=True)
    network = (params.get("type", ["tcp"])[0] or "tcp").strip().lower()
    security = (params.get("security", ["none"])[0] or "none").strip().lower()
    encryption = (params.get("encryption", ["none"])[0] or "none").strip()
    flow = (params.get("flow", [""])[0] or "").strip()
    sni = (
        (params.get("sni", [""])[0] or "").strip()
        or (params.get("serverName", [""])[0] or "").strip()
        or address
    )
    fingerprint = (params.get("fp", [""])[0] or "").strip()
    alpn_raw = (params.get("alpn", [""])[0] or "").strip()
    path = unquote((params.get("path", ["/"])[0] or "/").strip() or "/")
    host_header = (
        (params.get("host", [""])[0] or "").strip()
        or (params.get("headerHost", [""])[0] or "").strip()
        or sni
        or address
    )

    outbound = {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [{
                    "id": client_id,
                    "encryption": encryption,
                }],
            }],
        },
        "streamSettings": {
            "network": network,
            "security": security,
        },
    }
    user_block = outbound["settings"]["vnext"][0]["users"][0]
    if flow:
        user_block["flow"] = flow

    stream = outbound["streamSettings"]
    if security == "tls":
        tls_settings = {
            "serverName": sni or address,
            "allowInsecure": False,
        }
        if fingerprint:
            tls_settings["fingerprint"] = fingerprint
        if alpn_raw:
            tls_settings["alpn"] = [item.strip() for item in alpn_raw.split(",") if item.strip()]
        stream["tlsSettings"] = tls_settings

    if network == "ws":
        stream["wsSettings"] = {
            "path": path or "/",
            "headers": {"Host": host_header},
        }

    normalize_ws_transport(outbound)
    return outbound


def parse_telegram_proxy_input(raw_text: str) -> dict:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        raise ValueError("کانفیگ پروکسی خالی است.")
    if raw_text.lower().startswith("vless://"):
        return parse_vless_uri(raw_text)
    return json.loads(raw_text)


def normalize_telegram_xray_config(raw_config: dict) -> dict:
    if not isinstance(raw_config, dict):
        raise ValueError("کانفیگ باید یک JSON object باشد.")
    if isinstance(raw_config.get("outbounds"), list):
        outbounds = raw_config["outbounds"]
    elif raw_config.get("protocol"):
        outbounds = [raw_config]
    else:
        raise ValueError("کانفیگ باید outbounds داشته باشد یا خودش یک outbound معتبر باشد.")

    normalized_outbounds = []
    proxy_tags = []
    used_tags = set()
    for index, outbound in enumerate(outbounds, start=1):
        if not isinstance(outbound, dict) or not outbound.get("protocol"):
            continue
        item = json.loads(json.dumps(outbound, ensure_ascii=False))
        normalize_ws_transport(item)
        protocol = item.get("protocol")
        tag = item.get("tag")
        if not tag:
            if protocol == "freedom":
                tag = "direct"
            elif protocol == "blackhole":
                tag = "block"
            else:
                tag = f"proxy-{index}"
            item["tag"] = tag
        if tag in used_tags:
            item["tag"] = f"{tag}-{index}"
            tag = item["tag"]
        used_tags.add(tag)
        normalized_outbounds.append(item)
        if protocol not in {"freedom", "blackhole", "dns"}:
            proxy_tags.append(tag)

    if not proxy_tags:
        raise ValueError("هیچ outbound پروکسی معتبری برای تلگرام پیدا نشد.")
    if not any(item.get("tag") == "direct" for item in normalized_outbounds):
        normalized_outbounds.append({"tag": "direct", "protocol": "freedom"})
    if not any(item.get("tag") == "block" for item in normalized_outbounds):
        normalized_outbounds.append({"tag": "block", "protocol": "blackhole"})

    if len(proxy_tags) == 1:
        routing = {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "inboundTag": ["telegram-socks"], "outboundTag": proxy_tags[0]}],
        }
    else:
        routing = {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "inboundTag": ["telegram-socks"], "balancerTag": "telegram-vless"}],
            "balancers": [{"tag": "telegram-vless", "selector": proxy_tags}],
        }

    normalized_config = {
        "log": raw_config.get("log") or {"loglevel": "warning"},
        "inbounds": [telegram_socks_inbound()],
        "outbounds": normalized_outbounds,
        "routing": routing,
    }
    if raw_config.get("dns") is not None:
        normalized_config["dns"] = raw_config.get("dns")
    return normalized_config


def probe_general_proxy() -> tuple[bool, str]:
    command = [
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        "20",
        "--socks5-hostname",
        "127.0.0.1:9050",
        "https://www.google.com/generate_204",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=25,
        )
    except Exception as exc:
        return False, f"تست عمومی پروکسی اجرا نشد: {exc}"
    code = (result.stdout or "").strip()
    if result.returncode == 0 and code in {"200", "204"}:
        return True, "پروکسی عمومی سالم است."
    detail = (result.stderr or result.stdout or "").strip()
    return False, f"تست عمومی پروکسی شکست خورد: {detail or f'HTTP {code or result.returncode}'}"


def probe_telegram_api_ip(token: str) -> tuple[str | None, str]:
    token = str(token or "").strip()
    if not token:
        return None, "توکن ربات برای تست Telegram API تنظیم نشده است."

    for ip in TELEGRAM_API_IP_CANDIDATES:
        command = [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "--socks5-hostname",
            "127.0.0.1:9050",
            "--resolve",
            f"api.telegram.org:443:{ip}",
            f"https://api.telegram.org/bot{token}/getMe",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=25,
            )
        except Exception:
            continue
        output = (result.stdout or "").strip()
        if result.returncode == 0 and '"ok":true' in output:
            return ip, f"IP سالم تلگرام پیدا شد: {ip}"
    return None, "هیچ IP سالمی برای Telegram API از داخل این پروکسی پیدا نشد."


def finalize_telegram_proxy() -> None:
    settings = read_settings()
    proxy_ok, proxy_message = probe_general_proxy()
    append_log(proxy_message)
    if not proxy_ok:
        raise RuntimeError(proxy_message)

    telegram_ip, ip_message = probe_telegram_api_ip(settings.get("bot_token") or settings.get("token", ""))
    append_log(ip_message)
    if not telegram_ip:
        raise RuntimeError(ip_message)

    settings["telegram_api_ip"] = telegram_ip
    write_settings(settings)
    append_log(f"telegram_api_ip saved as {telegram_ip}")


def patch_install_offline() -> None:
    path = ROOT_DIR / "install_offline.sh"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    old = '''if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    VIRTUALENV_WHEEL="$(ls "$WHEEL_DIR"/virtualenv-*.whl | head -n 1)"
    "$PYTHON_BIN" "$VIRTUALENV_WHEEL" "$VENV_DIR" --no-download --extra-search-dir "$WHEEL_DIR"
fi'''
    new = '''if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    rm -rf "$VENV_DIR"
    WHEEL_PATHS="$(printf ":%s" "$WHEEL_DIR"/*.whl)"
    PYTHONPATH="${WHEEL_PATHS#:}" "$PYTHON_BIN" -m virtualenv "$VENV_DIR" --no-download --extra-search-dir "$WHEEL_DIR"
fi'''
    if old in content:
        path.write_text(content.replace(old, new), encoding="utf-8")


def run_command(command: list[str], check: bool = True) -> bool:
    append_log("$ " + " ".join(command))
    process = subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        append_log(line)
    code = process.wait()
    append_log(f"[exit {code}]")
    if check and code != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}")
    return code == 0


def install_flow() -> None:
    global INSTALL_RUNNING, INSTALL_DONE, INSTALL_OK
    with INSTALL_LOCK:
        INSTALL_RUNNING = True
        INSTALL_DONE = False
        INSTALL_OK = False
        INSTALL_LINES.clear()
    SETUP_LOG_PATH.write_text("", encoding="utf-8")
    try:
        append_log("Starting full setup...")
        patch_install_offline()
        run_command(["chmod", "+x", "install_offline.sh", "bootstrap_offline.sh"])
        run_command(["chmod", "+x", *[str(path.relative_to(ROOT_DIR)) for path in (ROOT_DIR / "scripts").glob("*.sh")]])
        run_command(["./scripts/stop_all.sh"], check=False)
        run_command(["./scripts/install_xray_offline.sh"])
        run_command(["./install_offline.sh"])
        run_command(["./scripts/start_xray.sh"])
        run_command(["./scripts/set_telegram_proxy.sh", DEFAULT_PROXY_URL])
        if XRAY_CONFIG_PATH.exists():
            finalize_telegram_proxy()
        run_command(["./scripts/start_all.sh"])
        run_command(["./scripts/status.sh"], check=False)
        append_log("Finished successfully.")
        with INSTALL_LOCK:
            INSTALL_OK = True
    except Exception as exc:
        append_log(f"ERROR: {exc}")
        with INSTALL_LOCK:
            INSTALL_OK = False
    finally:
        with INSTALL_LOCK:
            INSTALL_RUNNING = False
            INSTALL_DONE = True


def cleanup_and_exit() -> None:
    time.sleep(1)
    for relative in ("setup.sh", "setup_wizard.py", "setup_wizard.log"):
        try:
            (ROOT_DIR / relative).unlink(missing_ok=True)
        except Exception:
            pass
    os._exit(0)


def render_page(body: str, title: str = "3x-ui Pro Panel Devaloper Rogerpick") -> bytes:
    page = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #08111b;
      --ink: #ebf6ff;
      --muted: #93a8b7;
      --line: rgba(102, 164, 255, 0.2);
      --surface: rgba(10, 18, 28, 0.78);
      --primary: #14b8a6;
      --primary-2: #3b82f6;
      --accent: #8b5cf6;
      --danger: #ff5d73;
      --shadow: 0 22px 68px rgba(0, 0, 0, 0.42);
      --shadow-soft: 0 14px 34px rgba(0, 0, 0, 0.32);
      --glow: 0 0 0 1px rgba(59, 130, 246, 0.15) inset;
      --radius: 8px;
      font-family: "Vazirmatn", "Segoe UI", Tahoma, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: #060d15; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        linear-gradient(115deg, rgba(20, 184, 166, 0.2), transparent 34%),
        linear-gradient(245deg, rgba(59, 130, 246, 0.16), transparent 38%),
        linear-gradient(180deg, rgba(9, 16, 25, 0.96), rgba(8, 17, 27, 0.98)),
        var(--bg);
      overflow-x: hidden;
      position: relative;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      z-index: -2;
      pointer-events: none;
      background:
        repeating-linear-gradient(90deg, rgba(59, 130, 246, 0.045) 0 1px, transparent 1px 72px),
        repeating-linear-gradient(0deg, rgba(20, 184, 166, 0.035) 0 1px, transparent 1px 72px);
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.82), rgba(0, 0, 0, 0.2));
    }}
    body::after {{
      content: "";
      position: fixed;
      inset: -35% -20%;
      z-index: -3;
      pointer-events: none;
      background:
        linear-gradient(120deg, transparent 0 18%, rgba(20, 184, 166, 0.24) 24%, transparent 32% 55%, rgba(139, 92, 246, 0.16) 63%, transparent 72%),
        linear-gradient(28deg, rgba(59, 130, 246, 0.12), transparent 42%, rgba(20, 184, 166, 0.16));
    }}
    main {{
      width: min(1180px, calc(100% - 28px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 16px 18px;
      margin-bottom: 18px;
      background: rgba(10, 18, 28, 0.72);
      border: 1px solid rgba(102, 164, 255, 0.2);
      border-radius: var(--radius);
      box-shadow: var(--shadow-soft), var(--glow);
      backdrop-filter: blur(22px) saturate(1.2);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .brand-mark {{
      width: 44px;
      height: 44px;
      display: grid;
      place-items: center;
      border-radius: var(--radius);
      background: linear-gradient(135deg, var(--primary), var(--primary-2) 55%, var(--accent));
      color: #f4fbff;
      font-weight: 900;
      box-shadow: 0 12px 28px rgba(20, 184, 166, 0.22);
      flex: 0 0 auto;
    }}
    .brand-copy {{
      min-width: 0;
    }}
    .eyebrow {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 4px;
    }}
    .brand-copy h1, .panel h2 {{
      margin: 0;
      letter-spacing: 0;
    }}
    .brand-copy p, .panel > p, .hint {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.85;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      width: fit-content;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(20, 184, 166, 0.12);
      color: var(--primary);
      font-size: 12px;
      font-weight: 900;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      display: grid;
      gap: 14px;
      background: var(--surface);
      border: 1px solid rgba(102, 164, 255, 0.18);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}
    .hero-panel {{
      background:
        linear-gradient(180deg, rgba(19, 29, 41, 0.82), rgba(10, 16, 24, 0.72)),
        linear-gradient(135deg, rgba(20,184,166,0.14), rgba(59,130,246,0.12));
    }}
    .hero-list {{
      display: grid;
      gap: 12px;
      margin-top: 4px;
    }}
    .hero-item {{
      padding: 12px 14px;
      border-radius: var(--radius);
      border: 1px solid rgba(102, 164, 255, 0.18);
      background: rgba(12, 20, 30, 0.64);
      box-shadow: var(--glow);
      line-height: 1.8;
    }}
    .hero-item strong {{
      display: block;
      margin-bottom: 5px;
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 7px;
      color: var(--muted);
      font-size: 13px;
      min-width: 0;
    }}
    label span {{
      font-weight: 850;
      color: var(--ink);
    }}
    label small {{
      color: var(--muted);
      line-height: 1.7;
    }}
    button, input, textarea {{
      font: inherit;
      letter-spacing: 0;
    }}
    input, textarea {{
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(10, 16, 24, 0.84);
      color: var(--ink);
      padding: 9px 11px;
      outline: none;
      transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }}
    input {{
      direction: ltr;
    }}
    textarea {{
      min-height: 220px;
      resize: vertical;
      line-height: 1.7;
      direction: ltr;
      text-align: left;
      font-family: Consolas, "Courier New", monospace;
    }}
    input:focus, textarea:focus {{
      border-color: rgba(59, 130, 246, 0.72);
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.13), 0 10px 22px rgba(0, 0, 0, 0.28);
      background: #101923;
    }}
    .full {{
      grid-column: 1 / -1;
    }}
    button, .button {{
      min-height: 42px;
      border: 0;
      border-radius: var(--radius);
      padding: 9px 15px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-weight: 800;
      white-space: nowrap;
      text-decoration: none;
      transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }}
    button:hover, .button:hover {{
      transform: translateY(-1px);
      text-decoration: none;
    }}
    button, .button.primary {{
      background: linear-gradient(135deg, #14b8a6, #3b82f6 55%, #8b5cf6);
      color: #fff;
      box-shadow: 0 12px 28px rgba(20, 184, 166, 0.22);
    }}
    .button.secondary {{
      background: rgba(16, 23, 34, 0.72);
      color: var(--ink);
      border: 1px solid rgba(102, 164, 255, 0.22);
      box-shadow: var(--glow);
    }}
    .button.danger {{
      background: var(--danger);
      color: #fff;
      box-shadow: 0 10px 22px rgba(184, 51, 51, 0.13);
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
    }}
    pre {{
      margin: 0;
      direction: ltr;
      text-align: left;
      background: #111827;
      color: #d1fae5;
      border-radius: var(--radius);
      padding: 14px;
      min-height: 320px;
      max-height: 520px;
      overflow: auto;
      white-space: pre-wrap;
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }}
    @media (max-width: 920px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 780px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
      .topbar {{
        align-items: start;
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="topbar">
      <div class="brand">
        <div class="brand-mark">3X</div>
        <div class="brand-copy">
          <div class="eyebrow">Setup Wizard</div>
          <h1>{html.escape(title)}</h1>
          <p>پیکربندی اولیه و راه‌اندازی آفلاین پروژه با همان ظاهر و حس پنل اصلی.</p>
        </div>
      </div>
      <div class="status-pill">Offline Bundle Ready</div>
    </section>
    {body}
  </main>
</body></html>"""
    return page.encode("utf-8")


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def send_html(self, body: str, status: int = 200) -> None:
        payload = render_page(body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        data = parse_qs(raw)
        return {key: values[-1] for key, values in data.items()}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/status.json":
            with INSTALL_LOCK:
                payload = {
                    "running": INSTALL_RUNNING,
                    "done": INSTALL_DONE,
                    "ok": INSTALL_OK,
                    "log": "\n".join(INSTALL_LINES),
                }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/start":
            self.send_html("""<section class="layout">
  <section class="panel">
    <h2>اجرای نصب و راه‌اندازی</h2>
    <p>از اینجا نصب آفلاین پروژه، پیکربندی Xray و بالا آوردن سرویس‌های اصلی انجام می‌شود.</p>
    <form method="post" action="/start" class="actions">
      <button type="submit">Start Setup</button>
      <a class="button secondary" href="/">بازگشت به تنظیمات</a>
      <a class="button danger" href="/finish">Finish و بستن setup</a>
    </form>
    <pre id="log">منتظر شروع...</pre>
  </section>
  <aside class="panel hero-panel">
    <h2>خروجی این مرحله</h2>
    <div class="hero-list">
      <div class="hero-item">
        <strong>محیط اجرا</strong>
        محیط پایتون و بسته‌های محلی از داخل bundle آماده می‌شوند.
      </div>
      <div class="hero-item">
        <strong>پروکسی تلگرام</strong>
        Xray روی socks5 داخلی تنظیم می‌شود تا فقط ارتباط تلگرام از آن عبور کند.
      </div>
      <div class="hero-item">
        <strong>اجرای سرویس‌ها</strong>
        bot، web panel و cronjob در انتها بالا می‌آیند و وضعیتشان ثبت می‌شود.
      </div>
    </div>
  </aside>
</section>
<script>
async function tick() {{
  const r = await fetch('/status.json');
  const s = await r.json();
  document.getElementById('log').textContent = s.log || '...';
  setTimeout(tick, 1500);
}}
tick();
</script>""")
            return

        if path == "/finish":
            self.send_html("<section class='layout'><section class='panel'><h2>Setup بسته شد</h2><p>فایل‌های setup حذف می‌شوند و خود wizard متوقف خواهد شد.</p></section><aside class='panel hero-panel'><h2>گام بعدی</h2><p>اگر نصب کامل شده باشد، ادامه‌ی مدیریت از داخل پنل اصلی پروژه انجام می‌شود.</p></aside></section>")
            threading.Thread(target=cleanup_and_exit, daemon=True).start()
            return

        settings = read_settings()
        xray_json = XRAY_CONFIG_PATH.read_text(encoding="utf-8") if XRAY_CONFIG_PATH.exists() else ""
        body = f"""<section class="layout">
<form class="panel" method="post" action="/save">
  <h2>ورود اطلاعات حیاتی</h2>
  <p>این بخش فقط برای پارامترهای اولیه‌ی حساس است؛ چیزهایی که کاربر باید بدون دست‌کاری کد بتواند برای خودش شخصی‌سازی کند.</p>
  <div class="grid">
    <label>
      <span>توکن ربات تلگرام</span>
      <input name="bot_token" required value="{html.escape(str(settings.get('bot_token', '')))}" placeholder="123456:ABC...">
      <small>توکن اصلی BotFather را اینجا وارد کن.</small>
    </label>
    <label>
      <span>آیدی عددی ادمین اصلی</span>
      <input name="main_admin_chat_id" required inputmode="numeric" value="{html.escape(str((settings.get('main_admin_chat_ids') or [''])[0]))}" placeholder="123456789">
      <small>این آیدی برای دسترسی کامل و دکمه‌های ویژه استفاده می‌شود.</small>
    </label>
    <label class="full">
      <span>پسورد وب ادمین اصلی</span>
      <input name="admin_web_password" required value="{html.escape(str(settings.get('admin_web_password', '')))}" placeholder="رمز ورود پنل">
      <small>بعدا باید از داخل پنل هم قابل تغییر باشد، اما برای شروع اینجا ست می‌شود.</small>
    </label>
    <label class="full">
      <span>کانفیگ JSON پروکسی Xray برای تلگرام</span>
      <textarea name="xray_config_json" placeholder='vless://... یا {"outbounds":[...]}'>{html.escape(xray_json)}</textarea>
      <small>اگر JSON خام Xray/V2Ray وارد شود، setup آن را به فرمت داخلی مناسب پروژه تبدیل می‌کند.</small>
    </label>
  </div>
  <p class="hint">پروکسی تلگرام به صورت خودکار روی {DEFAULT_PROXY_URL} تنظیم می‌شود و خروجی نهایی داخل xray/config.json ذخیره خواهد شد.</p>
  <div class="actions">
    <button type="submit">ذخیره و رفتن به اجرای setup</button>
  </div>
</form>
<aside class="panel hero-panel">
  <h2>راهنمای سریع</h2>
  <div class="hero-list">
    <div class="hero-item">
      <strong>توکن و ادمین</strong>
      هویت ربات و دسترسی اصلی پروژه با این دو مقدار مشخص می‌شود.
    </div>
    <div class="hero-item">
      <strong>پروکسی تلگرام</strong>
      اگر سرور دسترسی مستقیم نداشته باشد، همین JSON مسیر تلگرام را زنده می‌کند.
    </div>
    <div class="hero-item">
      <strong>مرحله بعد</strong>
      بعد از ذخیره، وارد اجرای کامل setup و نصب آفلاین می‌شوی.
    </div>
  </div>
</aside>
</section>"""
        self.send_html(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/start":
            global INSTALL_RUNNING
            with INSTALL_LOCK:
                already_running = INSTALL_RUNNING
            if not already_running:
                threading.Thread(target=install_flow, daemon=True).start()
            self.send_response(303)
            self.send_header("Location", "/start")
            self.end_headers()
            return

        if path == "/save":
            form = self.read_form()
            try:
                admin_id = int(form.get("main_admin_chat_id", "").strip())
            except ValueError:
                self.send_html("<section class='layout'><section class='panel'><h2>آیدی ادمین معتبر نیست</h2><p>لطفا یک آیدی عددی درست وارد کن.</p><div class='actions'><a class='button primary' href='/'>بازگشت</a></div></section></section>", 400)
                return

            xray_config_text = form.get("xray_config_json", "").strip()
            if xray_config_text:
                try:
                    xray_config = normalize_telegram_xray_config(parse_telegram_proxy_input(xray_config_text))
                except json.JSONDecodeError as exc:
                    self.send_html(f"<section class='layout'><section class='panel'><h2>JSON پروکسی معتبر نیست</h2><p>{html.escape(str(exc))}</p><div class='actions'><a class='button primary' href='/'>بازگشت</a></div></section></section>", 400)
                    return
                except ValueError as exc:
                    self.send_html(f"<section class='layout'><section class='panel'><h2>کانفیگ پروکسی معتبر نیست</h2><p>{html.escape(str(exc))}</p><div class='actions'><a class='button primary' href='/'>بازگشت</a></div></section></section>", 400)
                    return
                XRAY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                XRAY_CONFIG_PATH.write_text(json.dumps(xray_config, ensure_ascii=False, indent=2), encoding="utf-8")

            settings = read_settings()
            settings.update(
                {
                    "panel_secret": settings.get("panel_secret")
                    if settings.get("panel_secret") and settings.get("panel_secret") != "change-this-secret"
                    else secrets.token_hex(32),
                    "database_url": settings.get("database_url") or "sqlite:///bot_panel.db",
                    "bot_token": form.get("bot_token", "").strip(),
                    "primary_owner_chat_id": admin_id,
                    "main_admin_chat_ids": [admin_id],
                    "admin_chat_ids": [admin_id],
                    "admin_web_password": form.get("admin_web_password", "").strip(),
                    "telegram_proxy_url": DEFAULT_PROXY_URL,
                    "telegram_api_ip": "",
                }
            )
            write_settings(settings)
            self.send_response(303)
            self.send_header("Location", "/start")
            self.end_headers()
            return

        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SetupHandler)
    print(f"Setup wizard listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
