from __future__ import annotations

import base64
import csv
import json
import os
import re
import secrets
import string
import subprocess
import tempfile
import traceback
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from time import sleep
from time import time
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_sock import Sock
from sqlalchemy import func, inspect, or_, text
from telebot import TeleBot
from werkzeug.security import check_password_hash

from app_settings import load_settings, save_settings
from database import BalanceTransfer, Config, Server, Session, Subscription, User, Waitlist, engine
from networking import configure_telegram_proxy, direct_requests_session


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
BOT_STATUS_PATH = BASE_DIR / "config.json"
XRAY_PRESET_CONFIG_PATH = ROOT_DIR / "xray" / "config.json"
XRAY_RUNTIME_DIR = ROOT_DIR / "xray" / "runtime"
XRAY_RUNTIME_CONFIG_PATH = XRAY_RUNTIME_DIR / "config.json"
XRAY_LOG_DIR = BASE_DIR / "logs"
TELEGRAM_PROXY_URL = "socks5h://127.0.0.1:9050"
TELEGRAM_API_IP_CANDIDATES = [
    "149.154.167.220",
    "149.154.167.99",
    "149.154.167.91",
    "149.154.167.92",
    "149.154.167.50",
    "149.154.167.51",
]
STATS_DIR = Path(os.environ.get("BOT_STATS_DIR", "/var/bot/stats"))
settings = load_settings()
schema_checked = False
PRIMARY_OWNER_CHAT_ID = int(settings.get("primary_owner_chat_id") or (settings.get("main_admin_chat_ids", [0])[0] if settings.get("main_admin_chat_ids") else 0))
CRYPTO_PRICE_TTL_SECONDS = 20
CRYPTO_PRICE_CACHE = {"updated_at": 0.0, "prices": {}, "error": ""}
CRYPTO_ASSET_LABELS = {
    "bnb": "BNB",
    "trx": "TRX",
    "usdt_trc20": "USDT TRC20",
    "usdt_bep20": "USDT BEP20",
}
CRYPTO_PRICE_SYMBOLS = {
    "bnb": "bnb",
    "trx": "trx",
    "usdt_trc20": "usdt",
    "usdt_bep20": "usdt",
}
PAYMENT_RECEIPT_DIR = BASE_DIR / "static" / "payment_receipts"
PAYMENT_RECEIPT_STATIC_PREFIX = "payment_receipts"
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_APPROVED = "approved"
PAYMENT_STATUS_REJECTED = "rejected"

app = Flask(__name__)
app.secret_key = settings.get("panel_secret") or os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
sock = Sock(app)


@app.before_request
def refresh_settings_for_request():
    settings.clear()
    settings.update(load_settings())


def ensure_schema() -> None:
    global schema_checked
    if schema_checked:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "web_password_hash" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN web_password_hash VARCHAR(255)"))
    if "is_blocked" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0"))
    waitlist_columns = {column["name"] for column in inspect(engine).get_columns("waitlist")}
    if "receipt_image_path" not in waitlist_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE waitlist ADD COLUMN receipt_image_path VARCHAR(255)"))
    waitlist_updates = {
        "status": "ALTER TABLE waitlist ADD COLUMN status VARCHAR(32) DEFAULT 'pending'",
        "created_at": "ALTER TABLE waitlist ADD COLUMN created_at VARCHAR(32)",
        "reviewed_at": "ALTER TABLE waitlist ADD COLUMN reviewed_at VARCHAR(32)",
    }
    missing_waitlist_updates = [sql for name, sql in waitlist_updates.items() if name not in waitlist_columns]
    if missing_waitlist_updates:
        with engine.begin() as connection:
            for sql in missing_waitlist_updates:
                connection.execute(text(sql))
    schema_checked = True


@dataclass
class CurrentUser:
    tg_id: int
    role: str
    user: User | None

    @property
    def is_admin(self) -> bool:
        return self.role in {"admin", "main_admin"}

    @property
    def is_main_admin(self) -> bool:
        return self.role == "main_admin"


def normalize_tg_id(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def get_role(tg_id: int) -> str:
    main_admins = set(map(int, settings.get("main_admin_chat_ids", [])))
    admins = set(map(int, settings.get("admin_chat_ids", []))) | main_admins
    if tg_id in main_admins:
        return "main_admin"
    if tg_id in admins:
        return "admin"
    return "user"


def visible_admin_ids(values: list[int] | tuple[int, ...]) -> list[int]:
    return [int(item) for item in values if int(item) not in hidden_admin_display_ids()]


def hidden_admin_display_ids() -> set[int]:
    return set(map(int, settings.get("main_admin_chat_ids", []))) | {PRIMARY_OWNER_CHAT_ID}


def admin_password_matches(raw_password: str) -> bool:
    configured = settings.get("admin_web_password") or os.environ.get("ADMIN_WEB_PASSWORD", "")
    configured_hash = settings.get("admin_web_password_hash") or os.environ.get("ADMIN_WEB_PASSWORD_HASH", "")
    if configured_hash:
        return check_password_hash(configured_hash, raw_password)
    return bool(configured) and secrets.compare_digest(str(configured), raw_password)


def current_user() -> CurrentUser | None:
    tg_id = session.get("tg_id")
    if not tg_id:
        return None
    ensure_schema()
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=int(tg_id)).first()
        return CurrentUser(tg_id=int(tg_id), role=get_role(int(tg_id)), user=user)
    finally:
        db.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("tg_id"):
            return redirect(url_for("login", next=request.path))
        user = current_user()
        if user and not user.is_admin and user.user and user.user.is_blocked:
            session.clear()
            flash("دسترسی شما به پنل مسدود شده است.", "error")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user.is_admin:
            flash("دسترسی ادمین لازم است.", "error")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)

    return wrapper


def main_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user.is_main_admin:
            flash("این عملیات فقط برای ادمین اصلی فعال است.", "error")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)

    return wrapper


def extract_ip(url: str) -> str:
    parsed_url = urlparse(url)
    return parsed_url.netloc.split(":")[0]


def generate_random_uuid() -> str:
    return str(uuid.uuid4())


def generate_random_email() -> str:
    username = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    domain = "".join(secrets.choice(string.ascii_lowercase) for _ in range(5))
    tld = "".join(secrets.choice(string.ascii_lowercase) for _ in range(3))
    return f"{username}@{domain}.{tld}"


def current_millis() -> int:
    return int(__import__("time").time() * 1000)


def build_3xui_client(client_uuid: str | None = None, client_email: str | None = None, is_active: bool = True):
    now = current_millis()
    return {
        "id": client_uuid or generate_random_uuid(),
        "flow": "",
        "email": client_email or generate_random_email(),
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": is_active,
        "tgId": "",
        "subId": "",
        "reset": 0,
        "comment": "",
        "created_at": now,
        "updated_at": now,
    }


def server_protocol(server: Server) -> str:
    return (getattr(server, "protocol", None) or ("vless" if server.is_vless else "vmess")).lower()


def server_network(server: Server) -> str:
    return (getattr(server, "network", None) or ("tcp" if server.is_tcp else "ws")).lower()


def server_security(server: Server) -> str:
    return (getattr(server, "security", None) or ("none" if server.sni == "-1" else "tls")).lower()


def json_or_none(raw: str | None):
    raw = (raw or "").strip()
    if not raw:
        return None
    return json.loads(raw)


def render_json_template(raw: str | None, values: dict[str, Any]):
    data = json_or_none(raw)
    if data is None:
        return None
    rendered = json.dumps(data)
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return json.loads(rendered)


def build_server_client(server: Server, is_active: bool):
    client = build_3xui_client(is_active=is_active)
    template = render_json_template(
        getattr(server, "client_template_json", None),
        {
            "uuid": client["id"],
            "password": client["id"],
            "email": client["email"],
            "enable": str(is_active).lower(),
            "now": current_millis(),
        },
    )
    if template:
        template.setdefault("email", client["email"])
        template.setdefault("enable", is_active)
        template.setdefault("id", client["id"])
        client = template
    elif server_protocol(server) == "trojan":
        client["password"] = client.pop("id")
    elif server_protocol(server) in {"shadowsocks", "shadowsocks2022"}:
        client["password"] = client.pop("id")
        client.setdefault("method", "aes-128-gcm")
    return client


def parse_3xui_response(response: requests.Response, assume_success_on_empty: bool = False):
    text = response.text.strip() if response.text else ""
    if response.status_code != 200:
        return False, text
    if not text and assume_success_on_empty:
        return True, {}
    try:
        payload = response.json()
    except Exception:
        return (True, {}) if assume_success_on_empty else (False, text)
    return bool(payload.get("success")), payload


def authenticate(base_url: str, username: str, password: str):
    login_session = direct_requests_session()
    response = login_session.post(
        f"{base_url}/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "username": username,
            "password": password,
            "twoFactorCode": settings.get("xui_two_factor_code", ""),
        }),
        timeout=20,
    )
    success, payload = parse_3xui_response(response)
    if success:
        return True, login_session
    return False, payload


def add_client_to_inbound(base_url: str, login_session: requests.Session, inbound_id: int, is_active: bool, server: Server | None = None):
    client_payload = build_server_client(server, is_active) if server else build_3xui_client(is_active=is_active)
    client = {
        "client_uuid": client_payload.get("id") or client_payload.get("password"),
        "client_email": client_payload.get("email") or generate_random_email(),
    }
    client_data = {
        "id": inbound_id,
        "settings": json.dumps({"clients": [client_payload]}),
    }
    response = login_session.post(
        f"{base_url}/panel/api/inbounds/addClient",
        headers={"Content-Type": "application/json"},
        data=json.dumps(client_data),
        timeout=20,
    )
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True, client
    return False, payload


def add_inbound(server: Server, login_session: requests.Session):
    protocol = server_protocol(server)
    network = server_network(server)
    security = server_security(server)
    tls_enabled = security == "tls"
    inbound_settings = json_or_none(getattr(server, "inbound_settings_json", None))
    stream_settings = json_or_none(getattr(server, "stream_settings_json", None))
    sniffing = json_or_none(getattr(server, "sniffing_json", None))
    inbound_data = {
        "protocol": protocol,
        "enable": True,
        "port": server.port,
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": f"{protocol}-{server.port}",
        "expiryTime": 0,
        "listen": "",
        "settings": json.dumps(inbound_settings or {"clients": [], "decryption": "none", "fallbacks": []}),
        "streamSettings": json.dumps(stream_settings or
            {
                "network": network,
                "security": security,
                "tlsSettings": {
                    "serverName": server.domain_name,
                    "minVersion": "1.2",
                    "maxVersion": "1.3",
                    "cipherSuites": "",
                    "certificates": [
                        {"certificateFile": server.pub_key, "keyFile": server.private_key}
                    ],
                    "alpn": ["h2", "http/1.1"],
                    "settings": {
                        "allowInsecure": False,
                        "fingerprint": "",
                        "serverName": server.sni,
                        "domains": [],
                    },
                } if tls_enabled else {},
                "tcpSettings": {
                    "acceptProxyProtocol": False,
                    "header": {"type": "none" if tls_enabled else "http"},
                },
            }
        ),
        "sniffing": json.dumps(sniffing or {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
            "metadataOnly": False,
            "routeOnly": False,
        }),
        "allocate": json.dumps({"strategy": "always", "refresh": 5, "concurrency": 3}),
    }
    response = login_session.post(f"{server.domain}/panel/api/inbounds/add", json=inbound_data, timeout=20)
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get("obj")
    return False, payload


def delete_inbound(base_url: str, login_session: requests.Session, inbound_id: int) -> bool:
    response = login_session.post(f"{base_url}/panel/api/inbounds/del/{inbound_id}", timeout=20)
    success, _ = parse_3xui_response(response, assume_success_on_empty=True)
    return success


def update_client(base_url: str, login_session: requests.Session, inbound_id: int, config: Config, enable: bool):
    client_data = {
        "id": inbound_id,
        "settings": json.dumps({"clients": [build_3xui_client(
            client_uuid=config.client_uuid,
            client_email=config.client_email,
            is_active=enable,
        )]}),
    }
    response = login_session.post(
        f"{base_url}/panel/api/inbounds/updateClient/{config.client_uuid}",
        headers={"Content-Type": "application/json"},
        data=json.dumps(client_data),
        timeout=20,
    )
    success, _ = parse_3xui_response(response, assume_success_on_empty=True)
    return success


def delete_client(base_url: str, login_session: requests.Session, inbound_id: int, client_uuid: str) -> bool:
    response = login_session.post(
        f"{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
        timeout=20,
    )
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True
    return remove_client_from_inbound_settings(base_url, login_session, inbound_id, client_uuid)


def remove_client_from_inbound_settings(base_url: str, login_session: requests.Session, inbound_id: int, client_uuid: str) -> bool:
    ok, inbound = get_inbound_by_id(base_url, login_session, inbound_id)
    if not ok or not inbound:
        return False
    settings_data = parse_json_field(inbound.get("settings"))
    clients = settings_data.get("clients") or []
    filtered_clients = [
        client for client in clients
        if client.get("id") != client_uuid and client.get("password") != client_uuid
    ]
    if len(filtered_clients) == len(clients):
        return True
    settings_data["clients"] = filtered_clients
    payload = {
        "id": inbound.get("id"),
        "protocol": inbound.get("protocol"),
        "enable": inbound.get("enable", True),
        "port": inbound.get("port"),
        "up": inbound.get("up", 0),
        "down": inbound.get("down", 0),
        "total": inbound.get("total", 0),
        "remark": inbound.get("remark", ""),
        "expiryTime": inbound.get("expiryTime", 0),
        "listen": inbound.get("listen", ""),
        "settings": json.dumps(settings_data),
        "streamSettings": inbound.get("streamSettings") or "{}",
        "sniffing": inbound.get("sniffing") or "{}",
        "allocate": inbound.get("allocate") or "{}",
    }
    response = login_session.post(f"{base_url}/panel/api/inbounds/update/{inbound_id}", json=payload, timeout=20)
    success, _ = parse_3xui_response(response, assume_success_on_empty=True)
    return success


def generate_link(server: Server, client_uuid: str, email: str) -> str:
    protocol = server_protocol(server)
    network = server_network(server)
    security = server_security(server)
    address = extract_ip(server.domain)
    port = server.port
    stream: dict[str, Any] = {}

    if protocol == "vless":
        security = "" if server.sni == "-1" else f"&security=tls&fp=chrome&alpn=h2%2Chttp%2F1.1&sni={server.sni}"
        header = "&headerType=http" if server.is_tcp and server.sni == "-1" else ""
        return (
            f"vless://{client_uuid}@{address}:{port}"
            f"?type={network}&path=%2F{security}{header}#{quote(email)}"
        )

    if protocol == "trojan":
        params = [f"type={network}"]
        if security == "tls":
            tls = stream.get("tlsSettings", {})
            params.append("security=tls")
            if tls.get("serverName"):
                params.append(f"sni={tls.get('serverName')}")
        elif security == "reality":
            reality = stream.get("realitySettings", {})
            reality_settings = reality.get("settings", {})
            params.append("security=reality")
            if reality_settings.get("publicKey"):
                params.append(f"pbk={reality_settings.get('publicKey')}")
            short_ids = reality.get("shortIds") or []
            if short_ids:
                params.append(f"sid={short_ids[0]}")
        return f"trojan://{client_uuid}@{address}:{port}?{'&'.join(params)}#{quote(email)}"

    if protocol in {"shadowsocks", "shadowsocks2022"}:
        method = "aes-128-gcm"
        userinfo = base64.urlsafe_b64encode(f"{method}:{client_uuid}".encode("utf-8")).decode("utf-8").rstrip("=")
        return f"ss://{userinfo}@{address}:{port}#{quote(email)}"

    vmess_config = {
        "v": "2",
        "ps": email,
        "add": address,
        "port": int(port),
        "id": client_uuid,
        "aid": "0",
        "net": network,
        "type": "http" if server.is_tcp else "none",
        "tls": "tls",
        "path": "/",
        "sni": server.sni,
        "alpn": "h2,http/1.1",
        "headerType": "http",
    }
    if server.sni == "-1":
        for key in ("sni", "alpn", "tls"):
            vmess_config.pop(key, None)
    else:
        vmess_config["fp"] = "chrome"
    if not server.is_tcp or server.sni != "-1":
        vmess_config.pop("headerType", None)
    return "vmess://" + base64.b64encode(json.dumps(vmess_config).encode("utf-8")).decode("utf-8")


def parse_json_field(value, default=None):
    if default is None:
        default = {}
    if isinstance(value, dict):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def get_inbound_by_id(base_url: str, login_session: requests.Session, inbound_id: int):
    response = login_session.get(f"{base_url}/panel/api/inbounds/get/{inbound_id}", timeout=20)
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get("obj")
    response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=20)
    success, payload = parse_3xui_response(response)
    if success:
        inbounds = payload.get("obj") or []
        return True, next((item for item in inbounds if item.get("id") == inbound_id), None)
    return False, payload


def get_all_inbounds(base_url: str, login_session: requests.Session):
    response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=20)
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get("obj") or []
    return False, payload


def inbound_label(inbound: dict[str, Any]) -> dict[str, Any]:
    stream = parse_json_field(inbound.get("streamSettings"))
    settings_data = parse_json_field(inbound.get("settings"))
    return {
        "id": inbound.get("id"),
        "remark": inbound.get("remark") or "-",
        "port": inbound.get("port") or 0,
        "protocol": inbound.get("protocol") or "-",
        "network": stream.get("network") or "-",
        "security": stream.get("security") or "none",
        "clients": len(settings_data.get("clients") or []),
        "enable": bool(inbound.get("enable", True)),
    }


def apply_existing_inbound(server: Server, inbound: dict[str, Any]) -> None:
    stream = parse_json_field(inbound.get("streamSettings"))
    server.inbound_id = int(inbound.get("id") or 0)
    server.port = int(inbound.get("port") or server.port or 0)
    server.protocol = (inbound.get("protocol") or server.protocol or "vless").lower()
    server.network = (stream.get("network") or server.network or "tcp").lower()
    server.security = (stream.get("security") or server.security or "none").lower()
    server.is_vless = server.protocol == "vless"
    server.is_tcp = server.network == "tcp"
    server.inbound_settings_json = inbound.get("settings") or server.inbound_settings_json
    server.stream_settings_json = inbound.get("streamSettings") or server.stream_settings_json
    server.sniffing_json = inbound.get("sniffing") or server.sniffing_json


def generate_link_from_inbound(server: Server, inbound: dict[str, Any] | None, client_uuid: str, email: str) -> str:
    if not inbound:
        return generate_link(server, client_uuid, email)

    stream = parse_json_field(inbound.get("streamSettings"))
    network = stream.get("network", "tcp")
    security = stream.get("security", "none")
    port = inbound.get("port") or server.port
    address = extract_ip(server.domain)

    if server.is_vless:
        params = [f"type={network}"]
        if network == "ws":
            path = stream.get("wsSettings", {}).get("path", "/")
            params.append(f"path={quote(path, safe='')}")
            host = stream.get("wsSettings", {}).get("host") or stream.get("wsSettings", {}).get("headers", {}).get("Host")
            if host:
                params.append(f"host={quote(str(host), safe='')}")
        elif network == "tcp":
            header_type = stream.get("tcpSettings", {}).get("header", {}).get("type")
            if header_type and header_type != "none":
                params.append(f"headerType={header_type}")

        if security == "tls":
            tls = stream.get("tlsSettings", {})
            params.extend(["security=tls", "fp=chrome"])
            if tls.get("serverName"):
                params.append(f"sni={tls.get('serverName')}")
            alpn = tls.get("alpn")
            if alpn:
                params.append(f"alpn={quote(','.join(alpn), safe='')}")
        elif security == "reality":
            reality = stream.get("realitySettings", {})
            reality_settings = reality.get("settings", {})
            params.append("security=reality")
            if reality_settings.get("fingerprint"):
                params.append(f"fp={reality_settings.get('fingerprint')}")
            server_names = reality.get("serverNames") or []
            sni = reality_settings.get("serverName") or (server_names[0] if server_names else "")
            if sni:
                params.append(f"sni={sni}")
            if reality_settings.get("publicKey"):
                params.append(f"pbk={reality_settings.get('publicKey')}")
            short_ids = reality.get("shortIds") or []
            if short_ids:
                params.append(f"sid={short_ids[0]}")
            if reality_settings.get("spiderX"):
                params.append(f"spx={quote(reality_settings.get('spiderX'), safe='')}")

        return f"vless://{client_uuid}@{address}:{port}?{'&'.join(params)}#{quote(email)}"

    vmess_config = {
        "v": "2",
        "ps": email,
        "add": address,
        "port": int(port),
        "id": client_uuid,
        "aid": "0",
        "net": network,
        "type": "none",
        "path": "/",
    }
    if network == "ws":
        ws_settings = stream.get("wsSettings", {})
        vmess_config["path"] = ws_settings.get("path", "/")
        host = ws_settings.get("host") or ws_settings.get("headers", {}).get("Host")
        if host:
            vmess_config["host"] = host
    if network == "tcp":
        vmess_config["type"] = stream.get("tcpSettings", {}).get("header", {}).get("type", "none")
    if security == "tls":
        tls = stream.get("tlsSettings", {})
        vmess_config["tls"] = "tls"
        vmess_config["sni"] = tls.get("serverName", "")
        vmess_config["alpn"] = ",".join(tls.get("alpn", []))
        vmess_config["fp"] = "chrome"
    return "vmess://" + base64.b64encode(json.dumps(vmess_config, separators=(",", ":")).encode("utf-8")).decode("utf-8")


def get_client_traffic(base_url: str, login_session: requests.Session, email: str):
    response = login_session.get(f"{base_url}/panel/api/inbounds/getClientTraffics/{email}", timeout=20)
    success, payload = parse_3xui_response(response)
    if success:
        obj = payload.get("obj") or {}
        return True, ((obj.get("up", 0) / 1024 / 1024 / 1024), (obj.get("down", 0) / 1024 / 1024 / 1024))
    return False, (0, 0)


def bytes_to_gib(value: Any) -> float:
    try:
        return float(value or 0) / 1024 / 1024 / 1024
    except (TypeError, ValueError):
        return 0.0


def percent(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0), 100.0))
    except (TypeError, ValueError):
        return 0.0


def ratio_percent(current: Any, total: Any) -> float:
    try:
        total_value = float(total or 0)
        if total_value <= 0:
            return 0.0
        return percent(float(current or 0) * 100 / total_value)
    except (TypeError, ValueError):
        return 0.0


def parse_int_list(raw: str) -> list[int]:
    return [int(item) for item in raw.replace(",", " ").split() if item.strip().lstrip("-").isdigit()]


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_number_text(value: Any) -> str:
    return str(value or "").translate(PERSIAN_DIGITS)


def normalize_price_token(value: Any) -> int | None:
    token = normalize_number_text(value)
    token = re.sub(r"[^\d-]", "", token)
    if not token or token == "-":
        return None
    try:
        return int(token)
    except ValueError:
        return None


def normalize_fixed_prices(raw: Any = None) -> dict[int, int]:
    source = settings.get("fixed_prices", {}) if raw is None else raw
    items = source.items() if isinstance(source, dict) else []
    result: dict[int, int] = {}
    for gb, price in items:
        gb_value = normalize_price_token(gb)
        price_value = normalize_price_token(price)
        if gb_value and gb_value > 0 and price_value is not None and price_value >= 0:
            result[gb_value] = price_value
    return dict(sorted(result.items()))


def parse_fixed_prices(raw: str) -> dict[str, int]:
    result: dict[int, int] = {}
    for line in normalize_number_text(raw).splitlines():
        numbers = re.findall(r"\d[\d,.\s]*", line)
        parsed = [normalize_price_token(item) for item in numbers]
        parsed = [item for item in parsed if item is not None]
        if len(parsed) >= 2 and parsed[0] > 0 and parsed[1] >= 0:
            result[parsed[0]] = parsed[1]
    return {str(gb): price for gb, price in sorted(result.items())}


def fixed_prices_text() -> str:
    return "\n".join(f"{gb} GB = {price}" for gb, price in normalize_fixed_prices().items())


def normalize_static_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip()
    return value.lstrip("/")


def get_server_status(server: Server) -> dict[str, Any]:
    ok, login_session = authenticate(server.domain, server.username, server.password)
    if not ok:
        return {"ok": False, "error": "login failed"}

    response = login_session.get(f"{server.domain}/panel/api/server/status", timeout=20)
    success, payload = parse_3xui_response(response)
    if not success:
        return {"ok": False, "error": payload}

    obj = payload.get("obj") or {}
    cpu = percent(obj.get("cpu"))
    mem = obj.get("mem") or {}
    disk = obj.get("disk") or {}
    xray = obj.get("xray") or {}
    net_io = obj.get("netIO") or obj.get("netIo") or {}
    net_traffic = obj.get("netTraffic") or {}

    return {
        "ok": True,
        "cpu": cpu,
        "mem_current": bytes_to_gib(mem.get("current")),
        "mem_total": bytes_to_gib(mem.get("total")),
        "mem_percent": percent(mem.get("percent")) if mem.get("percent") is not None else ratio_percent(mem.get("current"), mem.get("total")),
        "disk_current": bytes_to_gib(disk.get("current")),
        "disk_total": bytes_to_gib(disk.get("total")),
        "disk_percent": percent(disk.get("percent")) if disk.get("percent") is not None else ratio_percent(disk.get("current"), disk.get("total")),
        "net_up": bytes_to_gib(net_io.get("up")),
        "net_down": bytes_to_gib(net_io.get("down")),
        "traffic_up": bytes_to_gib(net_traffic.get("sent")),
        "traffic_down": bytes_to_gib(net_traffic.get("recv")),
        "xray_state": xray.get("state"),
        "xray_version": xray.get("version"),
        "uptime": obj.get("uptime"),
    }


def restart_xray_service(server: Server) -> tuple[bool, Any]:
    ok, login_session = authenticate(server.domain, server.username, server.password)
    if not ok:
        return False, "login failed"
    response = login_session.post(f"{server.domain}/panel/api/server/restartXrayService", timeout=20)
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    return success, payload


def auto_restart_config() -> dict[str, Any]:
    cfg = settings.setdefault("xray_auto_restart", {})
    cfg.setdefault("enabled_servers", {})
    cfg.setdefault("last_restart", {})
    cfg.setdefault("cpu_threshold", 90)
    cfg.setdefault("cooldown_seconds", 600)
    return cfg


def maybe_auto_restart_xray(server: Server, status: dict[str, Any]) -> dict[str, Any]:
    cfg = auto_restart_config()
    server_key = str(server.id)
    enabled = bool(cfg["enabled_servers"].get(server_key))
    status["auto_restart_enabled"] = enabled
    status["auto_restart_threshold"] = cfg["cpu_threshold"]
    status["auto_restart_cooldown"] = cfg["cooldown_seconds"]
    if not enabled or not status.get("ok"):
        return status
    if float(status.get("cpu") or 0) < float(cfg["cpu_threshold"]):
        return status

    now = int(time())
    last_restart = int(cfg["last_restart"].get(server_key, 0) or 0)
    if now - last_restart < int(cfg["cooldown_seconds"]):
        status["auto_restart_waiting"] = True
        return status

    success, payload = restart_xray_service(server)
    status["auto_restart_triggered"] = success
    status["auto_restart_error"] = None if success else payload
    if success:
        cfg["last_restart"][server_key] = now
        save_settings(settings)
    return status


def calculate_traffic(db, subscription: Subscription) -> tuple[bool, tuple[float, float]]:
    total_up = 0.0
    total_down = 0.0
    all_ok = True
    for config in subscription.configs:
        total_up += config.up or 0
        total_down += config.down or 0
        server = db.query(Server).filter_by(id=config.server_id).first()
        if not server:
            all_ok = False
            continue
        ok, login_session = authenticate(server.domain, server.username, server.password)
        if not ok:
            all_ok = False
            continue
        ok, traffic = get_client_traffic(server.domain, login_session, config.client_email)
        if ok:
            total_up += traffic[0]
            total_down += traffic[1]
        else:
            all_ok = False
    return all_ok, (total_up, total_down)


def calculate_traffic_best_effort(db, subscription: Subscription) -> tuple[float, float]:
    total_up = 0.0
    total_down = 0.0
    for config in subscription.configs:
        total_up += config.up or 0
        total_down += config.down or 0
        server = db.query(Server).filter_by(id=config.server_id).first()
        if not server:
            continue
        ok, login_session = authenticate(server.domain, server.username, server.password)
        if not ok:
            continue
        ok, traffic = get_client_traffic(server.domain, login_session, config.client_email)
        if ok:
            total_up += traffic[0]
            total_down += traffic[1]
    return total_up, total_down


def price_for_gigabytes(gigabytes: int) -> int:
    if settings.get("pricing_mode", "range") == "fixed":
        return normalize_fixed_prices().get(int(gigabytes), 0)
    ranges = list(map(int, settings.get("ranges", [])))
    prices = list(map(int, settings.get("prices", [])))
    if not prices:
        return 0
    for index, limit in enumerate(ranges):
        if gigabytes < limit:
            return prices[index] * gigabytes
    return prices[-1] * gigabytes


def has_price_for_gigabytes(gigabytes: int) -> bool:
    if settings.get("pricing_mode", "range") == "fixed":
        return int(gigabytes) in normalize_fixed_prices()
    return price_for_gigabytes(gigabytes) > 0


def normalize_nobitex_price_to_irr(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def fetch_crypto_prices_from_nobitex() -> dict[str, float]:
    response = requests.get(
        "https://api.nobitex.ir/market/stats",
        params={"srcCurrency": "bnb,trx,usdt", "dstCurrency": "rls"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    stats = payload.get("stats") or payload.get("global") or {}
    prices_by_symbol: dict[str, float] = {}
    for symbol in {"bnb", "trx", "usdt"}:
        candidates = [
            stats.get(f"{symbol}-rls"),
            stats.get(f"{symbol}rls"),
            stats.get(symbol.upper()),
            stats.get(symbol),
        ]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            value = item.get("latest") or item.get("lastTradePrice") or item.get("bestSell") or item.get("bestBuy")
            price = normalize_nobitex_price_to_irr(value)
            if price:
                prices_by_symbol[symbol] = price
                break
    result = {}
    for asset, symbol in CRYPTO_PRICE_SYMBOLS.items():
        if symbol in prices_by_symbol:
            result[asset] = prices_by_symbol[symbol]
    if not result:
        raise RuntimeError("Nobitex response did not contain usable prices")
    return result


def fetch_crypto_prices_from_wallex() -> dict[str, float]:
    response = requests.get("https://api.wallex.ir/v1/markets", timeout=15)
    response.raise_for_status()
    payload = response.json()
    symbols = ((payload.get("result") or {}).get("symbols") or {})
    symbol_map = {
        "bnb": "BNBTMN",
        "trx": "TRXTMN",
        "usdt_trc20": "USDTTMN",
        "usdt_bep20": "USDTTMN",
    }
    result = {}
    for asset, market_symbol in symbol_map.items():
        market = symbols.get(market_symbol) or {}
        stats = market.get("stats") or {}
        price_toman = normalize_nobitex_price_to_irr(
            stats.get("lastPrice") or stats.get("askPrice") or stats.get("bidPrice")
        )
        if price_toman:
            result[asset] = price_toman * 10
    if not result:
        raise RuntimeError("Wallex response did not contain usable prices")
    return result


def fetch_crypto_prices_from_coingecko_wallex() -> dict[str, float]:
    wallex = fetch_crypto_prices_from_wallex()
    usdt_irr = wallex.get("usdt_trc20") or wallex.get("usdt_bep20")
    if not usdt_irr:
        raise RuntimeError("USDT/IRR price is unavailable")
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "tether,tron,binancecoin", "vs_currencies": "usd"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    tether_usd = float((payload.get("tether") or {}).get("usd") or 1)
    bnb_usd = float((payload.get("binancecoin") or {}).get("usd") or 0)
    trx_usd = float((payload.get("tron") or {}).get("usd") or 0)
    usd_irr = usdt_irr / tether_usd
    result = {
        "usdt_trc20": usdt_irr,
        "usdt_bep20": usdt_irr,
    }
    if bnb_usd:
        result["bnb"] = bnb_usd * usd_irr
    if trx_usd:
        result["trx"] = trx_usd * usd_irr
    return result


def get_crypto_prices_cached(force: bool = False) -> dict[str, Any]:
    now = time()
    if not force and now - float(CRYPTO_PRICE_CACHE.get("updated_at") or 0) < CRYPTO_PRICE_TTL_SECONDS:
        return dict(CRYPTO_PRICE_CACHE)
    try:
        errors = []
        prices = {}
        for fetcher in (fetch_crypto_prices_from_nobitex, fetch_crypto_prices_from_wallex, fetch_crypto_prices_from_coingecko_wallex):
            try:
                prices = fetcher()
                if prices:
                    break
            except Exception as exc:
                errors.append(f"{fetcher.__name__}: {exc}")
        if not prices:
            raise RuntimeError(" | ".join(errors) or "No crypto price provider returned data")
        CRYPTO_PRICE_CACHE.update({"updated_at": now, "prices": prices, "error": ""})
    except Exception as exc:
        app.logger.error(traceback.format_exc())
        CRYPTO_PRICE_CACHE["error"] = str(exc)
        if not CRYPTO_PRICE_CACHE.get("updated_at"):
            CRYPTO_PRICE_CACHE["updated_at"] = now
    return dict(CRYPTO_PRICE_CACHE)


def crypto_quote_for_gigabytes(gigabytes: int, asset: str) -> dict[str, Any] | None:
    price_toman = price_for_gigabytes(gigabytes)
    prices = get_crypto_prices_cached().get("prices") or {}
    price_irr = float(prices.get(asset) or 0)
    if price_toman <= 0 or price_irr <= 0:
        return None
    amount_irr = price_toman * 10
    crypto_amount = amount_irr / price_irr
    return {
        "asset": asset,
        "label": CRYPTO_ASSET_LABELS.get(asset, asset),
        "price_toman": price_toman,
        "amount_irr": amount_irr,
        "price_irr": price_irr,
        "crypto_amount": crypto_amount,
    }


def sync_stats_placeholder(*_args, **_kwargs) -> None:
    # The Telegram bot writes CSV stats under /var/bot/stats. The web panel keeps DB
    # as source of truth; CSV reporting can be added once the production path exists.
    return None


def create_subscription_for_user(user_tg_id: int, gigabytes: int, name: str):
    db = Session()
    created_clients = []
    try:
        user = db.query(User).filter_by(tg_id=user_tg_id).first()
        if not user:
            return False, "کاربر پیدا نشد."
        if user.balance < gigabytes:
            return False, "موجودی کافی نیست."

        servers = db.query(Server).all()
        if not servers:
            return False, "هیچ سروری ثبت نشده است."

        safe_name = quote(name.strip().replace(" ", "_").replace("/", "_"))
        subscription = Subscription(name=safe_name, gigabytes=gigabytes, user=user, is_active=True)
        db.add(subscription)
        db.flush()

        links = []
        for server in servers:
            ok, login_session = authenticate(server.domain, server.username, server.password)
            if not ok:
                raise RuntimeError(f"اتصال به سرور {server.domain} ناموفق بود.")
            ok, client = add_client_to_inbound(server.domain, login_session, server.inbound_id, True, server)
            if not ok:
                raise RuntimeError(f"ساخت کلاینت روی {server.domain} ناموفق بود.")
            email = f"{server.country}_{safe_name}"
            _, inbound_info = get_inbound_by_id(server.domain, login_session, server.inbound_id)
            link = generate_link_from_inbound(server, inbound_info, client["client_uuid"], email)
            links.append(link)
            db.add(
                Config(
                    server_id=server.id,
                    client_uuid=client["client_uuid"],
                    client_email=client["client_email"],
                    link=link,
                    subscription=subscription,
                )
            )
            created_clients.append((server, login_session, client["client_uuid"]))

        subscription.links = ", ".join(links)
        subscription.link = f"{safe_name}_{secrets.token_hex(8)}"
        user.balance -= gigabytes
        db.commit()
        sync_stats_placeholder(user_tg_id)
        return True, subscription.link
    except Exception as exc:
        db.rollback()
        for server, login_session, client_uuid in created_clients:
            try:
                delete_client(server.domain, login_session, server.inbound_id, client_uuid)
            except Exception:
                pass
        app.logger.error(traceback.format_exc())
        return False, str(exc)
    finally:
        db.close()


def extend_subscription_for_user(user_tg_id: int, sub_link: str, gigabytes: int):
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=user_tg_id).first()
        subscription = db.query(Subscription).filter_by(link=sub_link).first()
        if not user or not subscription:
            return False, "لینک کانفیگ اشتباه است."
        if user.balance < gigabytes:
            return False, "موجودی کافی نیست."

        if not subscription.is_active:
            ok, traffic = calculate_traffic(db, subscription)
            if ok and (traffic[0] + traffic[1]) < subscription.gigabytes + gigabytes:
                for config in subscription.configs:
                    server = db.query(Server).filter_by(id=config.server_id).first()
                    ok, login_session = authenticate(server.domain, server.username, server.password)
                    if ok and not update_client(server.domain, login_session, server.inbound_id, config, True):
                        return False, "فعال‌سازی روی یکی از سرورها ناموفق بود."

        subscription.gigabytes += gigabytes
        subscription.is_active = True
        user.balance -= gigabytes
        db.commit()
        return True, "کانفیگ تمدید شد."
    except Exception:
        db.rollback()
        app.logger.error(traceback.format_exc())
        return False, "خطا در تمدید کانفیگ."
    finally:
        db.close()


def delete_subscription_by_link(actor: CurrentUser, sub_link: str):
    db = Session()
    try:
        query = db.query(Subscription).filter_by(link=sub_link)
        if not actor.is_admin and actor.user:
            query = query.filter_by(user_id=actor.user.id)
        subscription = query.first()
        if not subscription:
            return False, "کانفیگ پیدا نشد یا دسترسی ندارید."

        ok, traffic = calculate_traffic(db, subscription)
        if not ok:
            traffic = calculate_traffic_best_effort(db, subscription)

        failed = 0
        for config in list(subscription.configs):
            server = db.query(Server).filter_by(id=config.server_id).first()
            ok, login_session = authenticate(server.domain, server.username, server.password)
            if ok and delete_client(server.domain, login_session, server.inbound_id, config.client_uuid):
                db.delete(config)
            else:
                failed += 1
        if failed:
            db.commit()
            return False, f"حذف روی {failed} سرور کامل نشد."

        remain = int(max(subscription.gigabytes - (traffic[0] + traffic[1]) + 0.03, 0))
        subscription.user.balance += remain
        db.delete(subscription)
        db.commit()
        return True, "کانفیگ حذف شد و باقی‌مانده به موجودی برگشت."
    except Exception:
        db.rollback()
        app.logger.error(traceback.format_exc())
        return False, "خطا در حذف کانفیگ."
    finally:
        db.close()


def transfer_balance(source_tg_id: int, destination_tg_id: int, gigabytes: int):
    db = Session()
    try:
        source = db.query(User).filter_by(tg_id=source_tg_id).first()
        destination = db.query(User).filter_by(tg_id=destination_tg_id).first()
        if not source or not destination:
            return False, "کاربر پیدا نشد."
        if source.balance < gigabytes:
            return False, "موجودی کافی نیست."
        source.balance -= gigabytes
        destination.balance += gigabytes
        db.add(BalanceTransfer(
            source_tg_id=source_tg_id,
            destination_tg_id=destination_tg_id,
            gigabytes=gigabytes,
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
        ))
        db.commit()
        return True, "انتقال انجام شد."
    except Exception:
        db.rollback()
        return False, "خطا در انتقال موجودی."
    finally:
        db.close()


def add_balance(destination_tg_id: int, gigabytes: int):
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=destination_tg_id).first()
        if not user:
            return False, "کاربر پیدا نشد."
        user.balance += gigabytes
        db.commit()
        return True, "موجودی افزایش پیدا کرد."
    except Exception:
        db.rollback()
        return False, "خطا در افزایش موجودی."
    finally:
        db.close()


def save_payment_receipt(file_storage) -> str:
    if not file_storage or not file_storage.filename:
        return ""
    suffix = Path(file_storage.filename).suffix.lower()
    if suffix not in ALLOWED_RECEIPT_EXTENSIONS:
        raise ValueError("فرمت تصویر رسید معتبر نیست. فقط jpg، png و webp مجاز است.")
    PAYMENT_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(6)}{suffix}"
    receipt_path = PAYMENT_RECEIPT_DIR / filename
    file_storage.save(receipt_path)
    return f"{PAYMENT_RECEIPT_STATIC_PREFIX}/{filename}"


def bot_sales_enabled() -> bool:
    if not BOT_STATUS_PATH.exists():
        return False
    try:
        return bool(json.loads(BOT_STATUS_PATH.read_text(encoding="utf-8")).get("status", False))
    except Exception:
        return False


def set_bot_sales_enabled(enabled: bool) -> None:
    data = {}
    if BOT_STATUS_PATH.exists():
        try:
            data = json.loads(BOT_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["status"] = enabled
    BOT_STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_backup(base_url: str, login_session: requests.Session) -> bool:
    response = login_session.get(f"{base_url}/panel/api/server/getDb", timeout=30)
    if response.ok and response.content and not response.content.lstrip().startswith((b"{", b"[")):
        return True
    for method, endpoint in (
        ("post", "/panel/api/backuptotgbot"),
        ("get", "/panel/api/inbounds/createbackup"),
    ):
        response = getattr(login_session, method)(f"{base_url}{endpoint}", timeout=30)
        success, _ = parse_3xui_response(response, assume_success_on_empty=True)
        if success:
            return True
    response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=30)
    success, _ = parse_3xui_response(response)
    return success


def backup_filename_from_response(response: requests.Response, server_domain: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename="?([^";]+)"?', disposition)
    if match:
        return match.group(1)
    safe_domain = re.sub(r"[^a-zA-Z0-9_.-]+", "_", server_domain).strip("_") or "server"
    return f"{safe_domain}_x-ui.db"


def download_real_server_backup(server: Server) -> tuple[bool, Path | None, str | None, str]:
    ok, login_session = authenticate(server.domain, server.username, server.password)
    if not ok:
        return False, None, None, "login failed"
    response = login_session.get(f"{server.domain}/panel/api/server/getDb", timeout=60)
    if not response.ok or not response.content or response.content.lstrip().startswith((b"{", b"[")):
        return False, None, None, f"backup endpoint failed: {response.status_code}"
    filename = backup_filename_from_response(response, server.domain)
    safe_domain = re.sub(r"[^a-zA-Z0-9_.-]+", "_", server.domain).strip("_") or "server"
    backup_dir = Path(tempfile.gettempdir()) / f"xui_backup_{secrets.token_hex(6)}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / filename
    backup_path.write_bytes(response.content)
    return True, backup_path, safe_domain, ""


def collect_real_server_backups() -> tuple[list[tuple[Path, str, str]], list[str]]:
    db = Session()
    backups: list[tuple[Path, str, str]] = []
    failed: list[str] = []
    try:
        seen_domains = set()
        for server in db.query(Server).order_by(Server.id).all():
            if server.domain in seen_domains:
                continue
            seen_domains.add(server.domain)
            ok, path, folder_name, error = download_real_server_backup(server)
            if ok and path and folder_name:
                backups.append((path, folder_name, server.domain))
            else:
                failed.append(f"{server.domain} ({error})")
    finally:
        db.close()
    return backups, failed


def inbound_restore_payload(inbound: dict[str, Any]) -> dict[str, Any]:
    payload = {}
    for key in (
        "up", "down", "total", "remark", "enable", "expiryTime", "listen",
        "port", "protocol", "settings", "streamSettings", "tag", "sniffing",
        "allocate",
    ):
        if key in inbound:
            payload[key] = inbound[key]
    payload.setdefault("up", 0)
    payload.setdefault("down", 0)
    payload.setdefault("total", 0)
    payload.setdefault("remark", f"restored-{payload.get('port', '')}")
    payload.setdefault("enable", True)
    payload.setdefault("expiryTime", 0)
    payload.setdefault("listen", "")
    payload.setdefault("settings", json.dumps({"clients": [], "decryption": "none", "fallbacks": []}))
    payload.setdefault("streamSettings", json.dumps({"network": "tcp", "security": "none"}))
    payload.setdefault("sniffing", json.dumps({"enabled": True, "destOverride": ["http", "tls", "quic"]}))
    payload.setdefault("allocate", json.dumps({"strategy": "always", "refresh": 5, "concurrency": 3}))
    return payload


def restore_inbounds_to_server(base_url: str, login_session: requests.Session, inbounds: list[dict[str, Any]]) -> tuple[int, int, str | None]:
    response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=30)
    success, payload = parse_3xui_response(response)
    if not success:
        return 0, len(inbounds), "لیست inboundهای فعلی قابل دریافت نیست."
    current_inbounds = payload.get("obj") or []
    current_by_id = {item.get("id"): item for item in current_inbounds}
    current_by_port = {item.get("port"): item for item in current_inbounds}
    done = 0
    failed = 0
    for inbound in inbounds:
        restore_payload = inbound_restore_payload(inbound)
        current = current_by_id.get(inbound.get("id")) or current_by_port.get(inbound.get("port"))
        if current:
            restore_response = login_session.post(
                f"{base_url}/panel/api/inbounds/update/{current.get('id')}",
                json=restore_payload,
                timeout=30,
            )
        else:
            restore_response = login_session.post(f"{base_url}/panel/api/inbounds/add", json=restore_payload, timeout=30)
        ok, _ = parse_3xui_response(restore_response)
        if ok:
            done += 1
        else:
            failed += 1
    return done, failed, None


def backup_all_servers():
    db = Session()
    done = 0
    failed = []
    try:
        seen_domains = set()
        for server in db.query(Server).order_by(Server.id).all():
            if server.domain in seen_domains:
                continue
            seen_domains.add(server.domain)
            ok, login_session = authenticate(server.domain, server.username, server.password)
            if ok and create_backup(server.domain, login_session):
                done += 1
            else:
                failed.append(server.domain)
        return True, f"بکاپ برای {done} سرور انجام شد." + (f" ناموفق: {', '.join(failed)}" if failed else "")
    finally:
        db.close()


def restore_server_backup_upload(file_storage) -> tuple[bool, str]:
    try:
        payload = json.loads(file_storage.read().decode("utf-8"))
    except Exception as exc:
        return False, f"فایل بکاپ قابل خواندن نیست: {exc}"
    if not isinstance(payload, dict) or payload.get("type") != "manual_3xui_backup":
        return False, "این نوع بکاپ پشتیبانی نمی‌شود. فایل باید JSON ساخته‌شده توسط بکاپ سرورهای همین پروژه باشد."
    source = payload.get("source")
    inbounds = payload.get("inbounds") or []
    if not source or not inbounds:
        return False, "فایل بکاپ source یا inbound معتبر ندارد."
    db = Session()
    try:
        server = db.query(Server).filter_by(domain=source).first()
        if not server:
            return False, f"سرور مقصد برای این بکاپ پیدا نشد: {source}"
        ok, login_session = authenticate(server.domain, server.username, server.password)
        if not ok:
            return False, f"ورود به سرور مقصد ناموفق بود: {server.domain}"
        done, failed, error = restore_inbounds_to_server(server.domain, login_session, inbounds)
        if error:
            return False, error
        return failed == 0, f"بارگذاری بکاپ انجام شد. موفق: {done}، ناموفق: {failed}"
    finally:
        db.close()


def telegram_bot() -> TeleBot:
    token = (settings.get("bot_token") or settings.get("token") or "").strip()
    if not token:
        raise RuntimeError("توکن تلگرام در تنظیمات ثبت نشده است.")
    configure_telegram_proxy(settings.get("telegram_proxy_url", ""), settings.get("telegram_api_ip", ""))
    return TeleBot(token)


def broadcast_message_to_users(message_text: str):
    db = Session()
    sent = 0
    failed = 0
    try:
        bot = telegram_bot()
        for user in db.query(User).order_by(User.id).all():
            try:
                bot.send_message(user.tg_id, message_text)
                sent += 1
            except Exception:
                failed += 1
                app.logger.error(traceback.format_exc())
        return True, f"پیام برای {sent} کاربر ارسال شد. ناموفق: {failed}"
    except Exception as exc:
        app.logger.error(traceback.format_exc())
        return False, str(exc) or "خطا در ارسال پیام همگانی."
    finally:
        db.close()


def send_message_to_user(tg_id: int, message_text: str):
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=tg_id).first()
        if not user:
            return False, "کاربر پیدا نشد."
        bot = telegram_bot()
        bot.send_message(tg_id, message_text)
        return True, "پیام برای کاربر ارسال شد."
    except Exception as exc:
        app.logger.error(traceback.format_exc())
        return False, str(exc) or "ارسال پیام به کاربر با خطا روبه‌رو شد."
    finally:
        db.close()


def load_xray_config_text() -> str:
    for path in (XRAY_PRESET_CONFIG_PATH, XRAY_RUNTIME_CONFIG_PATH):
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def telegram_socks_inbound() -> dict[str, Any]:
    return {
        "tag": "telegram-socks",
        "listen": "127.0.0.1",
        "port": 9050,
        "protocol": "socks",
        "settings": {
            "auth": "noauth",
            "udp": True,
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls"],
        },
    }


def outbound_server_host(outbound: dict[str, Any]) -> str:
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


def normalize_ws_transport(outbound: dict[str, Any]) -> None:
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


def parse_vless_uri(raw_text: str) -> dict[str, Any]:
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

    outbound: dict[str, Any] = {
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
        tls_settings: dict[str, Any] = {
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


def parse_telegram_proxy_input(raw_text: str) -> dict[str, Any]:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        raise ValueError("کانفیگ پروکسی خالی است.")
    if raw_text.lower().startswith("vless://"):
        return parse_vless_uri(raw_text)
    return json.loads(raw_text)


def normalize_telegram_xray_config(raw_config: dict[str, Any]) -> dict[str, Any]:
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
            "rules": [{
                "type": "field",
                "inboundTag": ["telegram-socks"],
                "outboundTag": proxy_tags[0],
            }],
        }
    else:
        routing = {
            "domainStrategy": "AsIs",
            "rules": [{
                "type": "field",
                "inboundTag": ["telegram-socks"],
                "balancerTag": "telegram-vless",
            }],
            "balancers": [{
                "tag": "telegram-vless",
                "selector": proxy_tags,
            }],
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


def restart_local_xray() -> tuple[bool, str]:
    XRAY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    pid_path = XRAY_LOG_DIR / "xray.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(pid, 15)
            sleep(1)
        except Exception:
            pass
        pid_path.unlink(missing_ok=True)

    xray_bin = XRAY_RUNTIME_DIR / "xray"
    if not xray_bin.exists():
        return False, "Xray نصب نشده است. ابتدا از setup یا ترمینال install_xray_offline را اجرا کنید."
    if not XRAY_RUNTIME_CONFIG_PATH.exists():
        return False, "فایل runtime config ساخته نشد."

    out_log = (XRAY_LOG_DIR / "xray.out.log").open("ab")
    err_log = (XRAY_LOG_DIR / "xray.err.log").open("ab")
    process = subprocess.Popen(
        [str(xray_bin), "run", "-config", str(XRAY_RUNTIME_CONFIG_PATH)],
        cwd=str(ROOT_DIR),
        stdout=out_log,
        stderr=err_log,
        start_new_session=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    sleep(1)
    if process.poll() is not None:
        return False, "Xray بعد از اجرا متوقف شد. لاگ xray.err.log را بررسی کنید."
    return True, f"Xray با PID {process.pid} اجرا شد."


def apply_telegram_proxy_config(raw_text: str) -> tuple[bool, str]:
    try:
        raw_config = parse_telegram_proxy_input(raw_text)
        normalized = normalize_telegram_xray_config(raw_config)
    except Exception as exc:
        return False, f"JSON پروکسی معتبر نیست: {exc}"

    XRAY_PRESET_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    XRAY_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2)
    XRAY_PRESET_CONFIG_PATH.write_text(payload, encoding="utf-8")
    XRAY_RUNTIME_CONFIG_PATH.write_text(payload, encoding="utf-8")

    settings["telegram_proxy_url"] = TELEGRAM_PROXY_URL
    settings.pop("telegram_api_ip", None)
    save_settings(settings)
    configure_telegram_proxy(TELEGRAM_PROXY_URL, "")

    ok, message = restart_local_xray()
    if not ok:
        return False, f"کانفیگ ذخیره شد ولی Xray اجرا نشد: {message}"
    return True, f"کانفیگ پروکسی تلگرام ذخیره و اجرا شد. {message}"


def apply_telegram_proxy_config(raw_text: str) -> tuple[bool, str]:
    try:
        raw_config = parse_telegram_proxy_input(raw_text)
        normalized = normalize_telegram_xray_config(raw_config)
    except Exception as exc:
        return False, f"ورودی پروکسی معتبر نیست: {exc}"

    XRAY_PRESET_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    XRAY_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2)
    XRAY_PRESET_CONFIG_PATH.write_text(payload, encoding="utf-8")
    XRAY_RUNTIME_CONFIG_PATH.write_text(payload, encoding="utf-8")

    settings["telegram_proxy_url"] = TELEGRAM_PROXY_URL
    settings.pop("telegram_api_ip", None)
    save_settings(settings)
    configure_telegram_proxy(TELEGRAM_PROXY_URL, "")

    ok, message = restart_local_xray()
    if not ok:
        return False, f"کانفیگ ذخیره شد ولی Xray اجرا نشد: {message}"

    proxy_ok, proxy_message = probe_general_proxy()
    if not proxy_ok:
        return False, f"کانفیگ ذخیره و Xray اجرا شد، اما پروکسی عمومی سالم نشد. {proxy_message}"

    token = settings.get("bot_token") or settings.get("token", "")
    telegram_ip, ip_message = probe_telegram_api_ip(token)
    if not telegram_ip:
        return False, f"پروکسی عمومی بالا آمد، اما Telegram API هنوز مسیر سالم پیدا نکرد. {ip_message}"

    settings["telegram_api_ip"] = telegram_ip
    save_settings(settings)
    configure_telegram_proxy(TELEGRAM_PROXY_URL, telegram_ip)
    return True, f"کانفیگ پروکسی ذخیره و اجرا شد. {proxy_message} {ip_message}"


def available_stats() -> list[tuple[str, str]]:
    current = datetime.now()
    result = [(f"{current.month:02d}", str(current.year))]
    if not STATS_DIR.exists():
        return result
    for path in STATS_DIR.iterdir():
        match = re.match(r"user_stats_(\w+)_(\d+)\.csv$", path.name)
        if match and match.groups() not in result:
            result.append(match.groups())
    return sorted(result, key=lambda item: (int(item[1]), item[0]))


def user_stats_for_month(user_tg_id: int, month: str, year: str):
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=user_tg_id).first()
        if not user:
            return None
        month_prefix = f"{year}-{month.zfill(2)}"
        received_balance = db.query(func.coalesce(func.sum(BalanceTransfer.gigabytes), 0)).filter(
            BalanceTransfer.destination_tg_id == user_tg_id,
            BalanceTransfer.created_at.like(f"{month_prefix}%"),
        ).scalar()
        sent_balance = db.query(func.coalesce(func.sum(BalanceTransfer.gigabytes), 0)).filter(
            BalanceTransfer.source_tg_id == user_tg_id,
            BalanceTransfer.created_at.like(f"{month_prefix}%"),
        ).scalar()
        return {
            "tg_id": user.tg_id,
            "configs": db.query(Subscription).filter_by(user_id=user.id).count(),
            "active_configs": db.query(Subscription).filter_by(user_id=user.id, is_active=True).count(),
            "balance": int(user.balance or 0),
            "received_balance": int(received_balance or 0),
            "sent_balance": int(sent_balance or 0),
        }
    finally:
        db.close()


def transfer_history_for_user(db, user_tg_id: int | None, limit: int = 200):
    if not user_tg_id:
        return []
    return db.query(BalanceTransfer).filter(
        or_(BalanceTransfer.source_tg_id == user_tg_id, BalanceTransfer.destination_tg_id == user_tg_id)
    ).order_by(BalanceTransfer.id.desc()).limit(limit).all()


def build_server_from_form(form, prefix: str = "") -> Server:
    def field(name: str, default: str = "") -> str:
        return form.get(f"{prefix}{name}", default).strip()

    return Server(
        domain=field("domain"),
        username=field("username"),
        password=field("password"),
        country=field("country"),
        port=normalize_tg_id(field("port")) or 0,
        inbound_id=normalize_tg_id(field("inbound_id")) or 0,
        is_vless=field("protocol", "vless") == "vless",
        is_tcp=field("network", "tcp") == "tcp",
        protocol=field("protocol", "vless").lower(),
        network=field("network", "tcp").lower(),
        security=field("security", "none").lower(),
        sni=field("sni", "-1") or "-1",
        domain_name=field("domain_name", "-1") or "-1",
        pub_key=field("pub_key", "-1") or "-1",
        private_key=field("private_key", "-1") or "-1",
        inbound_settings_json=field("inbound_settings_json") or None,
        stream_settings_json=field("stream_settings_json") or None,
        sniffing_json=field("sniffing_json") or None,
        client_template_json=field("client_template_json") or None,
    )


def validate_server_json(server: Server) -> None:
    for raw_json in (
        server.inbound_settings_json,
        server.stream_settings_json,
        server.sniffing_json,
        server.client_template_json,
    ):
        if raw_json:
            json.loads(raw_json)


def replace_server_with_new(old_server_id: int, new_server: Server, cleanup_old_inbound: bool):
    db = Session()
    created_clients = []
    new_login_session = None
    try:
        old_server = db.query(Server).get(old_server_id)
        if not old_server:
            return False, "سرور قبلی پیدا نشد."
        validate_server_json(new_server)
        db.add(new_server)
        db.flush()

        ok, new_login_session = authenticate(new_server.domain, new_server.username, new_server.password)
        if not ok:
            raise RuntimeError("احراز هویت سرور جدید ناموفق بود.")
        if not new_server.inbound_id:
            ok, inbound = add_inbound(new_server, new_login_session)
            if not ok:
                raise RuntimeError("ساخت inbound روی سرور جدید ناموفق بود.")
            new_server.inbound_id = inbound["id"]
            new_server.port = inbound.get("port", new_server.port)

        old_ok, old_login_session = authenticate(old_server.domain, old_server.username, old_server.password)
        subscriptions = db.query(Subscription).order_by(Subscription.id).all()
        for subscription in subscriptions:
            old_config = db.query(Config).filter_by(server_id=old_server.id, subscription_id=subscription.id).first()
            migrated_up = old_config.up if old_config else 0
            migrated_down = old_config.down if old_config else 0
            if old_ok and old_config:
                traffic_ok, traffic = get_client_traffic(old_server.domain, old_login_session, old_config.client_email)
                if traffic_ok:
                    migrated_up = (migrated_up or 0) + traffic[0]
                    migrated_down = (migrated_down or 0) + traffic[1]

            ok, client = add_client_to_inbound(
                new_server.domain,
                new_login_session,
                new_server.inbound_id,
                subscription.is_active,
                new_server,
            )
            if not ok:
                raise RuntimeError(f"ساخت کلاینت جدید برای {subscription.name} ناموفق بود.")
            created_clients.append(client["client_uuid"])
            email = f"{new_server.country}_{subscription.name}"
            _, inbound_info = get_inbound_by_id(new_server.domain, new_login_session, new_server.inbound_id)
            new_link = generate_link_from_inbound(new_server, inbound_info, client["client_uuid"], email)

            if old_config:
                if subscription.links:
                    subscription.links = subscription.links.replace(old_config.link, new_link)
                old_config.server_id = new_server.id
                old_config.client_uuid = client["client_uuid"]
                old_config.client_email = client["client_email"]
                old_config.link = new_link
                old_config.up = migrated_up
                old_config.down = migrated_down
            else:
                db.add(Config(
                    server_id=new_server.id,
                    client_uuid=client["client_uuid"],
                    client_email=client["client_email"],
                    link=new_link,
                    subscription=subscription,
                    up=migrated_up or 0,
                    down=migrated_down or 0,
                ))
                subscription.links = f"{subscription.links}, {new_link}" if subscription.links else new_link

        if cleanup_old_inbound and old_ok and old_server.inbound_id:
            delete_inbound(old_server.domain, old_login_session, old_server.inbound_id)
        db.delete(old_server)
        db.commit()
        return True, "سرور با موفقیت جایگزین شد و لینک‌های کاربران به‌روزرسانی شدند."
    except Exception as exc:
        db.rollback()
        if new_login_session is not None:
            for client_uuid in created_clients:
                try:
                    delete_client(new_server.domain, new_login_session, new_server.inbound_id, client_uuid)
                except Exception:
                    pass
        app.logger.error(traceback.format_exc())
        return False, str(exc) or "خطا در جایگزینی سرور."
    finally:
        db.close()


def track_purchase(db, user_tg_id: int, gigabytes: int):
    user = db.query(User).filter_by(tg_id=user_tg_id).first()
    if not user or not user.inviter_id:
        return
    if user.purchases >= int(settings.get("referral_rate", 0)):
        return
    inviter = db.query(User).filter_by(id=user.inviter_id).first()
    if not inviter:
        return
    bonus = min(
        int(int(settings.get("referral_percent", 0)) * gigabytes / 100),
        int(settings.get("referral_rate", 0)) - (user.purchases or 0),
    )
    if bonus > 0:
        user.purchases = (user.purchases or 0) + bonus
        inviter.balance += bonus


def parse_subscription_link(raw: str) -> str:
    parsed = urlparse(raw.strip())
    return parsed.path.lstrip("/").rstrip("/") if parsed.path else raw.strip()


def subscription_public_rows(db, subscription: Subscription):
    ok, traffic = calculate_traffic(db, subscription)
    if not ok:
        traffic = calculate_traffic_best_effort(db, subscription)
    used = traffic[0] + traffic[1]
    remain = max(subscription.gigabytes - used, 0)
    links = [item.strip() for item in (subscription.links or "").split(",") if item.strip()]
    return {
        "traffic_ok": ok,
        "up": traffic[0],
        "down": traffic[1],
        "used": used,
        "remain": remain,
        "links": links,
    }


def transfer_stats(db) -> dict[str, int]:
    row = db.query(
        func.count(BalanceTransfer.id),
        func.coalesce(func.sum(BalanceTransfer.gigabytes), 0),
        func.count(func.distinct(BalanceTransfer.source_tg_id)),
        func.count(func.distinct(BalanceTransfer.destination_tg_id)),
    ).one()
    return {
        "count": int(row[0] or 0),
        "gigabytes": int(row[1] or 0),
        "senders": int(row[2] or 0),
        "receivers": int(row[3] or 0),
    }


def transfer_user_stats(db, limit: int = 50):
    rows = db.query(
        BalanceTransfer.source_tg_id,
        func.count(BalanceTransfer.id).label("count"),
        func.coalesce(func.sum(BalanceTransfer.gigabytes), 0).label("gigabytes"),
    ).group_by(BalanceTransfer.source_tg_id).order_by(func.coalesce(func.sum(BalanceTransfer.gigabytes), 0).desc()).limit(limit).all()
    return [
        {"source_tg_id": int(row[0]), "count": int(row[1] or 0), "gigabytes": int(row[2] or 0)}
        for row in rows
    ]


@app.context_processor
def inject_globals():
    return {
        "current": current_user(),
        "settings": settings,
        "bot_domain": settings.get("bot_domain", "").rstrip("/"),
        "visible_admin_chat_ids": visible_admin_ids(settings.get("admin_chat_ids", [])),
        "crypto_prices": dict(CRYPTO_PRICE_CACHE),
        "crypto_asset_labels": CRYPTO_ASSET_LABELS,
        "fixed_prices_text": fixed_prices_text(),
        "web_banner_path": normalize_static_path(settings.get("web_banner_path", "")),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ensure_schema()
        tg_id = normalize_tg_id(request.form.get("tg_id"))
        password = request.form.get("password", "")
        if not tg_id:
            flash("آیدی عددی تلگرام معتبر نیست.", "error")
            return redirect(url_for("login"))
        db = Session()
        try:
            user = db.query(User).filter_by(tg_id=tg_id).first()
            role = get_role(tg_id)
            if role in {"admin", "main_admin"}:
                if not admin_password_matches(password):
                    flash("پسورد ادمین اشتباه است.", "error")
                    return redirect(url_for("login"))
                if not user:
                    user = User(tg_id=tg_id, balance=5)
                    db.add(user)
                    db.commit()
            else:
                if not user:
                    flash("این چت‌آیدی هنوز در ربات ثبت نشده است.", "error")
                    return redirect(url_for("login"))
                if user.is_blocked:
                    flash("دسترسی شما به پنل مسدود شده است.", "error")
                    return redirect(url_for("login"))
                if not user.web_password_hash:
                    flash("اول از داخل ربات گزینه تنظیم پسورد وب را بزنید.", "error")
                    return redirect(url_for("login"))
                if not check_password_hash(user.web_password_hash, password):
                    flash("پسورد وب اشتباه است.", "error")
                    return redirect(url_for("login"))
            session["tg_id"] = tg_id
            next_url = request.args.get("next")
            if next_url:
                return redirect(next_url)
            return redirect(url_for("admin" if role in {"admin", "main_admin"} else "dashboard"))
        finally:
            db.close()
    return render_template("web_panel_login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    actor = current_user()
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=actor.tg_id).first()
        subscriptions = db.query(Subscription).filter_by(user_id=user.id).order_by(Subscription.id.desc()).all()
        rows = []
        for sub in subscriptions:
            ok, traffic = calculate_traffic(db, sub)
            rows.append(
                {
                    "subscription": sub,
                    "traffic_ok": ok,
                    "up": traffic[0],
                    "down": traffic[1],
                    "remain": max(sub.gigabytes - traffic[0] - traffic[1], 0),
                }
            )
        waitlist = db.query(Waitlist).filter_by(user_id=actor.tg_id).order_by(Waitlist.id.desc()).all()
        transfer_history = db.query(BalanceTransfer).filter(
            or_(BalanceTransfer.source_tg_id == actor.tg_id, BalanceTransfer.destination_tg_id == actor.tg_id)
        ).order_by(BalanceTransfer.id.desc()).limit(100).all()
        return render_template(
            "web_panel.html",
            view="dashboard",
            user=user,
            subscriptions=rows,
            waitlist=waitlist,
            transfer_history=transfer_history,
        )
    finally:
        db.close()


@app.get("/crypto/prices.json")
@login_required
def crypto_prices_json():
    return jsonify(crypto_prices_payload())


def crypto_prices_payload(force: bool = False) -> dict[str, Any]:
    payload = get_crypto_prices_cached(force=force)
    return {
        "ok": not bool(payload.get("error")),
        "prices": payload.get("prices") or {},
        "updated_at": payload.get("updated_at") or 0,
        "error": payload.get("error") or "",
        "ttl": CRYPTO_PRICE_TTL_SECONDS,
    }


@app.route("/s/<sub_link>")
@app.route("/sub/<sub_link>")
@app.route("/<sub_link>")
def public_subscription(sub_link: str):
    reserved = {
        "login", "logout", "admin", "static", "subscriptions", "balance",
        "favicon.ico",
    }
    if sub_link in reserved:
        return render_template("web_panel_error.html", error="صفحه پیدا نشد."), 404
    db = Session()
    try:
        subscription = db.query(Subscription).filter_by(link=parse_subscription_link(sub_link)).first()
        if not subscription:
            return render_template("web_panel_error.html", error="کانفیگ پیدا نشد."), 404
        details = subscription_public_rows(db, subscription)
        return render_template(
            "subscription_public.html",
            subscription=subscription,
            details=details,
        )
    finally:
        db.close()


@app.post("/subscriptions/create")
@login_required
def create_subscription_route():
    actor = current_user()
    gigabytes = normalize_tg_id(request.form.get("gigabytes")) or 0
    name = request.form.get("name", "").strip()
    if gigabytes < 1 or not name or not name.isascii():
        flash("نام باید انگلیسی و حجم باید عدد مثبت باشد.", "error")
        return redirect(url_for("dashboard"))
    ok, message = create_subscription_for_user(actor.tg_id, gigabytes, name)
    flash(f"کانفیگ ساخته شد: {settings.get('bot_domain', '').rstrip('/')}/{message}" if ok else message, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.post("/subscriptions/extend")
@login_required
def extend_subscription_route():
    actor = current_user()
    sub_link = parse_subscription_link(request.form.get("sub_link", ""))
    gigabytes = normalize_tg_id(request.form.get("gigabytes")) or 0
    ok, message = extend_subscription_for_user(actor.tg_id, sub_link, gigabytes)
    flash(message, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.post("/subscriptions/delete")
@login_required
def delete_subscription_route():
    actor = current_user()
    sub_link = parse_subscription_link(request.form.get("sub_link", ""))
    ok, message = delete_subscription_by_link(actor, sub_link)
    flash(message, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.post("/balance/transfer")
@login_required
def transfer_route():
    actor = current_user()
    destination_tg_id = normalize_tg_id(request.form.get("destination_tg_id"))
    gigabytes = normalize_tg_id(request.form.get("gigabytes")) or 0
    if not destination_tg_id or gigabytes < 1:
        flash("مقصد و حجم معتبر نیست.", "error")
        return redirect(url_for("dashboard"))
    ok, message = transfer_balance(actor.tg_id, destination_tg_id, gigabytes)
    flash(message, "success" if ok else "error")
    return redirect(url_for("dashboard"))


@app.post("/balance/charge")
@login_required
def charge_route():
    actor = current_user()
    gigabytes = normalize_tg_id(request.form.get("gigabytes")) or 0
    proof = request.form.get("proof", "").strip()
    payment_method = request.form.get("payment_method", "card")
    crypto_asset = request.form.get("crypto_asset", "")
    receipt_image_path = ""
    if gigabytes < 1:
        flash("حجم معتبر نیست.", "error")
        return redirect(url_for("dashboard"))
    price = price_for_gigabytes(gigabytes)
    if not has_price_for_gigabytes(gigabytes):
        flash("برای این حجم، قیمت تعریف نشده است.", "error")
        return redirect(url_for("dashboard"))
    payment_label = "کارت به کارت"
    if payment_method == "crypto":
        wallets = settings.get("crypto_wallets") or {}
        wallet = (wallets.get(crypto_asset) or "").strip()
        if not wallet:
            flash("آدرس کیف پول انتخاب شده هنوز تنظیم نشده است.", "error")
            return redirect(url_for("dashboard"))
        payment_label = f"ارز دیجیتال - {CRYPTO_ASSET_LABELS.get(crypto_asset, crypto_asset)}"
        quote = crypto_quote_for_gigabytes(gigabytes, crypto_asset)
        if quote:
            proof = (
                f"{proof} | مقدار قابل پرداخت: {quote['crypto_amount']:.8f} {quote['label']} "
                f"| قیمت لحظه‌ای: {quote['price_irr']:,.0f} ریال"
            ).strip(" |")
    try:
        receipt_image_path = save_payment_receipt(request.files.get("receipt_image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))
    db = Session()
    try:
        entry = Waitlist(
            user_id=actor.tg_id,
            gigabytes=gigabytes,
            price=price,
            receipt_image_path=receipt_image_path,
            message=f"{payment_label} | {proof or 'ثبت از پنل وب'}"[:255],
            status=PAYMENT_STATUS_PENDING,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.add(entry)
        db.commit()
        flash("درخواست شارژ برای تایید ادمین ثبت شد.", "success")
    finally:
        db.close()
    return redirect(url_for("dashboard"))


@app.route("/admin")
@login_required
@admin_required
def admin():
    admin_tab = request.args.get("tab", "settings")
    stats_tg_id = normalize_tg_id(request.args.get("stats_tg_id"))
    stats_month_year = request.args.get("stats_month_year", "")
    transfer_tg_id = normalize_tg_id(request.args.get("transfer_tg_id"))
    db = Session()
    try:
        hidden_ids = hidden_admin_display_ids()
        users = db.query(User).filter(~User.tg_id.in_(hidden_ids)).order_by(User.id.desc()).limit(200).all()
        waitlist = db.query(Waitlist).filter(
            or_(Waitlist.status == PAYMENT_STATUS_PENDING, Waitlist.status.is_(None))
        ).order_by(Waitlist.id.desc()).all()
        payment_history = db.query(Waitlist).filter(
            Waitlist.status.in_([PAYMENT_STATUS_APPROVED, PAYMENT_STATUS_REJECTED])
        ).order_by(Waitlist.id.desc()).limit(300).all()
        servers = db.query(Server).order_by(Server.id.desc()).all()
        server_status = {}
        for server in servers:
            server_status[server.id] = maybe_auto_restart_xray(server, get_server_status(server))
        subscriptions = db.query(Subscription).order_by(Subscription.id.desc()).limit(200).all()
        stats_result = None
        if stats_tg_id and "|" in stats_month_year:
            month, year = stats_month_year.split("|", 1)
            stats_result = user_stats_for_month(stats_tg_id, month, year)
        transfer_history = transfer_history_for_user(db, transfer_tg_id)
        return render_template(
            "web_panel.html",
            view="admin",
            admin_tab=admin_tab,
            users=users,
            waitlist=waitlist,
            payment_history=payment_history,
            servers=servers,
            server_status=server_status,
            all_subscriptions=subscriptions,
            bot_sales_enabled=bot_sales_enabled(),
            available_stats=available_stats(),
            stats_result=stats_result,
            stats_tg_id=stats_tg_id,
            stats_month_year=stats_month_year,
            transfer_tg_id=transfer_tg_id,
            transfer_history=transfer_history,
            balance_transfer_stats=transfer_stats(db),
            balance_transfer_user_stats=transfer_user_stats(db),
            telegram_xray_config_text=load_xray_config_text(),
        )
    finally:
        db.close()


@app.get("/admin/servers/status.json")
@login_required
@admin_required
def admin_server_status_json():
    return jsonify(server_status_payload())


def server_status_payload() -> dict[str, Any]:
    db = Session()
    try:
        data = {}
        for server in db.query(Server).order_by(Server.id).all():
            data[str(server.id)] = maybe_auto_restart_xray(server, get_server_status(server))
        return {"ok": True, "servers": data, "checked_at": int(time())}
    finally:
        db.close()


@sock.route("/admin/servers/status.ws")
def admin_server_status_ws(ws):
    actor = current_user()
    if not actor or not actor.is_admin:
        ws.close()
        return
    while True:
        try:
            ws.send(json.dumps(server_status_payload(), ensure_ascii=False))
            sleep(3)
        except Exception:
            break


@sock.route("/crypto/prices.ws")
def crypto_prices_ws(ws):
    actor = current_user()
    if not actor:
        ws.close()
        return
    while True:
        try:
            ws.send(json.dumps(crypto_prices_payload(force=True), ensure_ascii=False))
            sleep(CRYPTO_PRICE_TTL_SECONDS)
        except Exception:
            break


@app.post("/admin/waitlist/<int:waitlist_id>/approve")
@login_required
@admin_required
def approve_waitlist_route(waitlist_id: int):
    db = Session()
    try:
        entry = db.query(Waitlist).get(waitlist_id)
        if not entry:
            flash("درخواست پیدا نشد.", "error")
            return redirect(url_for("admin", tab="finance"))
        if entry.status == PAYMENT_STATUS_APPROVED:
            flash("این پرداخت قبلا تایید شده است.", "error")
            return redirect(url_for("admin", tab="finance"))
        if entry.status == PAYMENT_STATUS_REJECTED:
            flash("این پرداخت قبلا رد شده است.", "error")
            return redirect(url_for("admin", tab="finance"))
        user = db.query(User).filter_by(tg_id=entry.user_id).first()
        if not user:
            flash("کاربر درخواست پیدا نشد.", "error")
            return redirect(url_for("admin", tab="finance"))
        user.balance += entry.gigabytes
        track_purchase(db, entry.user_id, entry.gigabytes)
        entry.status = PAYMENT_STATUS_APPROVED
        entry.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
        flash("پرداخت تایید شد و موجودی کاربر افزایش یافت.", "success")
    except Exception:
        db.rollback()
        flash("خطا در تایید پرداخت.", "error")
    finally:
        db.close()
    return redirect(url_for("admin", tab="finance"))


@app.post("/admin/waitlist/<int:waitlist_id>/deny")
@login_required
@admin_required
def deny_waitlist_route(waitlist_id: int):
    db = Session()
    try:
        entry = db.query(Waitlist).get(waitlist_id)
        if entry:
            if entry.status == PAYMENT_STATUS_APPROVED:
                flash("پرداخت تایید شده قابل رد کردن نیست.", "error")
                return redirect(url_for("admin", tab="finance"))
            entry.status = PAYMENT_STATUS_REJECTED
            entry.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            flash("پرداخت رد شد.", "success")
    finally:
        db.close()
    return redirect(url_for("admin", tab="finance"))


@app.post("/admin/users/balance")
@login_required
@admin_required
def admin_set_balance():
    tg_id = normalize_tg_id(request.form.get("tg_id"))
    balance = normalize_tg_id(request.form.get("balance"))
    if tg_id is None or balance is None:
        flash("ورودی معتبر نیست.", "error")
        return redirect(url_for("admin", tab="users"))
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=tg_id).first()
        if not user:
            flash("کاربر پیدا نشد.", "error")
        else:
            user.balance = balance
            db.commit()
            flash("موجودی کاربر تغییر کرد.", "success")
    finally:
        db.close()
    return redirect(url_for("admin", tab="users"))


@app.post("/admin/users/block")
@login_required
@admin_required
def admin_block_user():
    tg_id = normalize_tg_id(request.form.get("tg_id"))
    if not tg_id:
        flash("آیدی عددی معتبر نیست.", "error")
        return redirect(url_for("admin", tab=request.form.get("admin_tab", "users")))
    main_admins = set(map(int, settings.get("main_admin_chat_ids", [])))
    admins = set(map(int, settings.get("admin_chat_ids", []))) | main_admins
    if tg_id in admins:
        flash("ادمین‌ها از این بخش مسدود نمی‌شوند.", "error")
        return redirect(url_for("admin", tab=request.form.get("admin_tab", "users")))
    db = Session()
    try:
        user = db.query(User).filter_by(tg_id=tg_id).first()
        if not user:
            flash("کاربر پیدا نشد.", "error")
        else:
            user.is_blocked = True
            db.commit()
            flash("دسترسی کاربر مسدود شد.", "success")
    except Exception:
        db.rollback()
        app.logger.error(traceback.format_exc())
        flash("مسدود کردن کاربر با خطا روبه‌رو شد.", "error")
    finally:
        db.close()
    return redirect(url_for("admin", tab=request.form.get("admin_tab", "users")))


@app.post("/admin/servers/<int:server_id>/restart-xray")
@login_required
@admin_required
def admin_restart_xray(server_id: int):
    db = Session()
    try:
        server = db.query(Server).get(server_id)
        if not server:
            flash("سرور پیدا نشد.", "error")
            return redirect(url_for("admin", tab="servers"))
        success, payload = restart_xray_service(server)
        flash("هسته Xray ریست شد." if success else f"ریست Xray ناموفق بود: {payload}", "success" if success else "error")
    finally:
        db.close()
    return redirect(url_for("admin", tab="servers"))


@app.post("/admin/servers/<int:server_id>/auto-restart-xray")
@login_required
@admin_required
def admin_toggle_xray_auto_restart(server_id: int):
    enabled = request.form.get("enabled") == "1"
    cfg = auto_restart_config()
    cfg["enabled_servers"][str(server_id)] = enabled
    save_settings(settings)
    flash("ریست خودکار Xray فعال شد." if enabled else "ریست خودکار Xray غیرفعال شد.", "success")
    return redirect(url_for("admin", tab="servers"))


@app.post("/admin/servers/add")
@login_required
@admin_required
def admin_add_server():
    db = Session()
    created_clients = []
    try:
        server = Server(
            domain=request.form.get("domain", "").strip(),
            username=request.form.get("username", "").strip(),
            password=request.form.get("password", "").strip(),
            country=request.form.get("country", "").strip(),
            port=normalize_tg_id(request.form.get("port")) or 0,
            inbound_id=normalize_tg_id(request.form.get("inbound_id")) or 0,
            is_vless=request.form.get("protocol") == "vless",
            is_tcp=request.form.get("network") == "tcp",
            protocol=request.form.get("protocol", "vless").strip().lower(),
            network=request.form.get("network", "tcp").strip().lower(),
            security=request.form.get("security", "none").strip().lower(),
            sni=request.form.get("sni", "-1").strip() or "-1",
            domain_name=request.form.get("domain_name", "-1").strip() or "-1",
            pub_key=request.form.get("pub_key", "-1").strip() or "-1",
            private_key=request.form.get("private_key", "-1").strip() or "-1",
            inbound_settings_json=request.form.get("inbound_settings_json", "").strip() or None,
            stream_settings_json=request.form.get("stream_settings_json", "").strip() or None,
            sniffing_json=request.form.get("sniffing_json", "").strip() or None,
            client_template_json=request.form.get("client_template_json", "").strip() or None,
        )
        db.add(server)
        db.flush()

        ok, login_session = authenticate(server.domain, server.username, server.password)
        if not ok:
            raise RuntimeError("احراز هویت سرور ناموفق بود.")

        inbound_mode = request.form.get("inbound_mode", "create")
        if inbound_mode == "existing":
            selected_inbound_id = normalize_tg_id(request.form.get("existing_inbound_id")) or server.inbound_id
            if not selected_inbound_id:
                raise RuntimeError("برای اتصال به inbound موجود، یک inbound را از لیست انتخاب کنید.")
            ok, inbound = get_inbound_by_id(server.domain, login_session, selected_inbound_id)
            if not ok or not inbound:
                raise RuntimeError("inbound انتخاب‌شده روی پنل 3x-ui پیدا نشد.")
            apply_existing_inbound(server, inbound)
        else:
            if server.port < 1:
                raise RuntimeError("برای ساخت inbound جدید، پورت inbound را وارد کنید.")
            for raw_json in (
                server.inbound_settings_json,
                server.stream_settings_json,
                server.sniffing_json,
                server.client_template_json,
            ):
                if raw_json:
                    json.loads(raw_json)
            ok, inbound = add_inbound(server, login_session)
            if not ok:
                raise RuntimeError("ساخت inbound روی سرور ناموفق بود.")
            server.inbound_id = inbound["id"]
            server.port = inbound.get("port", server.port)

        subscriptions = db.query(Subscription).all()
        for subscription in subscriptions:
            ok, client = add_client_to_inbound(server.domain, login_session, server.inbound_id, subscription.is_active, server)
            if not ok:
                raise RuntimeError("ساخت کلاینت برای یکی از کانفیگ‌های موجود ناموفق بود.")
            email = f"{server.country}_{subscription.name}"
            _, inbound_info = get_inbound_by_id(server.domain, login_session, server.inbound_id)
            link = generate_link_from_inbound(server, inbound_info, client["client_uuid"], email)
            db.add(
                Config(
                    server_id=server.id,
                    client_uuid=client["client_uuid"],
                    client_email=client["client_email"],
                    link=link,
                    subscription=subscription,
                )
            )
            subscription.links = f"{subscription.links}, {link}" if subscription.links else link
            created_clients.append(client["client_uuid"])

        db.commit()
        flash("سرور ثبت شد و برای کانفیگ‌های موجود هم کلاینت ساخته شد.", "success")
    except Exception as exc:
        db.rollback()
        if "server" in locals() and "login_session" in locals():
            for client_uuid in created_clients:
                try:
                    delete_client(server.domain, login_session, server.inbound_id, client_uuid)
                except Exception:
                    pass
        flash(str(exc) or "خطا در ثبت سرور.", "error")
    finally:
        db.close()
    return redirect(url_for("admin", tab="servers"))


@app.post("/admin/servers/discover-inbounds")
@login_required
@admin_required
def admin_discover_inbounds():
    domain = request.form.get("domain", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not domain or not username or not password:
        return jsonify({"ok": False, "message": "آدرس پنل، یوزرنیم و پسورد را وارد کنید."}), 400
    ok, login_session = authenticate(domain, username, password)
    if not ok:
        return jsonify({"ok": False, "message": "احراز هویت 3x-ui ناموفق بود."}), 400
    ok, inbounds = get_all_inbounds(domain, login_session)
    if not ok:
        return jsonify({"ok": False, "message": "خواندن inboundها از 3x-ui ناموفق بود."}), 400
    return jsonify({"ok": True, "inbounds": [inbound_label(item) for item in inbounds]})


@app.post("/admin/servers/replace")
@login_required
@admin_required
def admin_replace_server():
    old_server_id = normalize_tg_id(request.form.get("old_server_id")) or 0
    cleanup_old_inbound = request.form.get("cleanup_old_inbound") == "1"
    ok, message = replace_server_with_new(old_server_id, build_server_from_form(request.form), cleanup_old_inbound)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="servers"))


@app.post("/admin/servers/<int:server_id>/delete")
@login_required
@admin_required
def admin_delete_server(server_id: int):
    db = Session()
    try:
        server = db.query(Server).get(server_id)
        if not server:
            flash("سرور پیدا نشد.", "error")
        else:
            ok, login_session = authenticate(server.domain, server.username, server.password)
            subscriptions = db.query(Subscription).all()
            for subscription in subscriptions:
                config = db.query(Config).filter_by(server_id=server.id, subscription_id=subscription.id).first()
                if not config:
                    continue
                if ok:
                    traffic_ok, traffic = get_client_traffic(server.domain, login_session, config.client_email)
                    if traffic_ok:
                        aux_config = (
                            db.query(Config)
                            .filter(Config.subscription_id == subscription.id, Config.server_id != server.id)
                            .first()
                        )
                        if aux_config:
                            aux_config.up = (aux_config.up or 0) + traffic[0]
                            aux_config.down = (aux_config.down or 0) + traffic[1]
                if subscription.links:
                    subscription.links = subscription.links.replace(config.link, "").replace(", ,", ",").strip(", ")
                db.delete(config)
            if ok and server.inbound_id:
                delete_inbound(server.domain, login_session, server.inbound_id)
            db.delete(server)
            db.commit()
            flash("سرور حذف شد و کانفیگ‌های وابسته از دیتابیس پاک شدند.", "success")
    except Exception as exc:
        db.rollback()
        flash(str(exc) or "حذف سرور به دلیل وابستگی‌ها انجام نشد.", "error")
    finally:
        db.close()
    return redirect(url_for("admin", tab="servers"))


@app.post("/admin/servers/backup")
@login_required
@admin_required
def admin_backup_servers():
    backups, failed = collect_real_server_backups()
    if not backups:
        flash("فایل بکاپی دریافت نشد." + (f" ناموفق: {', '.join(failed)}" if failed else ""), "error")
        return redirect(url_for("admin", tab="payments"))
    if len(backups) == 1:
        backup_path, _, _ = backups[0]
        return send_file(
            backup_path,
            as_attachment=True,
            download_name=backup_path.name,
            mimetype="application/octet-stream",
            max_age=0,
        )
    zip_path = Path(tempfile.gettempdir()) / f"xui_server_backups_{secrets.token_hex(6)}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for backup_path, folder_name, _ in backups:
            archive.write(backup_path, f"{folder_name}/{backup_path.name}")
    return send_file(
        zip_path,
        as_attachment=True,
        download_name="xui_server_backups.zip",
        mimetype="application/zip",
        max_age=0,
    )


@app.post("/admin/servers/restore-backup")
@login_required
@admin_required
def admin_restore_server_backup():
    backup_file = request.files.get("backup_file")
    if not backup_file or not backup_file.filename:
        flash("فایل بکاپ انتخاب نشده است.", "error")
        return redirect(url_for("admin", tab="payments"))
    ok, message = restore_server_backup_upload(backup_file)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="payments"))


@app.post("/admin/broadcast")
@login_required
@admin_required
def admin_broadcast():
    message_text = request.form.get("message", "").strip()
    if not message_text:
        flash("متن پیام همگانی خالی است.", "error")
        return redirect(url_for("admin", tab="payments"))
    ok, message = broadcast_message_to_users(message_text)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="payments"))


@app.post("/admin/message-user")
@login_required
@admin_required
def admin_message_user():
    tg_id = normalize_tg_id(request.form.get("tg_id"))
    message_text = request.form.get("message", "").strip()
    if not tg_id or not message_text:
        flash("آیدی عددی و متن پیام را وارد کنید.", "error")
        return redirect(url_for("admin", tab="payments"))
    ok, message = send_message_to_user(tg_id, message_text)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="payments"))


@app.post("/admin/stats")
@login_required
@admin_required
def admin_stats():
    tg_id = normalize_tg_id(request.form.get("tg_id"))
    month_year = request.form.get("month_year", "")
    if not tg_id or "|" not in month_year:
        flash("کاربر و ماه گزارش معتبر نیست.", "error")
        return redirect(url_for("admin", tab="reports"))
    month, year = month_year.split("|", 1)
    stats = user_stats_for_month(tg_id, month, year)
    if not stats:
        flash("برای این کاربر در ماه انتخاب‌شده آماری پیدا نشد.", "error")
        return redirect(url_for("admin", tab="reports"))
    return redirect(url_for("admin", tab="reports", stats_tg_id=tg_id, stats_month_year=month_year))


@app.post("/admin/bot-status")
@login_required
@admin_required
def admin_bot_status():
    enabled = request.form.get("enabled") == "1"
    set_bot_sales_enabled(enabled)
    flash("فروش و عملیات ساخت/تمدید روشن شد." if enabled else "فروش و عملیات ساخت/تمدید خاموش شد.", "success")
    return redirect(url_for("admin", tab="settings"))


@app.post("/admin/self-balance")
@login_required
@admin_required
def admin_self_balance():
    actor = current_user()
    gigabytes = normalize_tg_id(request.form.get("gigabytes")) or 0
    if gigabytes < 1:
        flash("حجم افزایش موجودی معتبر نیست.", "error")
        return redirect(url_for("admin", tab="payments"))
    ok, message = add_balance(actor.tg_id, gigabytes)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="payments"))


@app.post("/admin/admins/add")
@login_required
@admin_required
def admin_add_admin():
    admin_tg_id = normalize_tg_id(request.form.get("admin_tg_id"))
    if not admin_tg_id:
        flash("چت‌آیدی ادمین معتبر نیست.", "error")
        return redirect(url_for("admin", tab="users"))
    main_admins = list(dict.fromkeys(map(int, settings.get("main_admin_chat_ids", []))))
    admins = list(dict.fromkeys(map(int, settings.get("admin_chat_ids", []))))
    if admin_tg_id in main_admins or admin_tg_id in admins:
        flash("این چت‌آیدی همین حالا دسترسی ادمین دارد.", "error")
        return redirect(url_for("admin", tab="users"))
    admins.append(admin_tg_id)
    settings["admin_chat_ids"] = admins
    save_settings(settings)
    flash("ادمین جدید اضافه شد.", "success")
    return redirect(url_for("admin", tab="users"))


@app.post("/admin/admins/remove")
@login_required
@admin_required
def admin_remove_admin():
    admin_tg_id = normalize_tg_id(request.form.get("admin_tg_id"))
    if not admin_tg_id:
        flash("چت‌آیدی ادمین معتبر نیست.", "error")
        return redirect(url_for("admin", tab="users"))
    main_admins = set(map(int, settings.get("main_admin_chat_ids", [])))
    if admin_tg_id in main_admins:
        flash("ادمین اصلی از این بخش قابل حذف نیست.", "error")
        return redirect(url_for("admin", tab="users"))
    admins = list(dict.fromkeys(map(int, settings.get("admin_chat_ids", []))))
    if admin_tg_id not in admins:
        flash("این چت‌آیدی در لیست ادمین‌ها نیست.", "error")
        return redirect(url_for("admin", tab="users"))
    settings["admin_chat_ids"] = [item for item in admins if item != admin_tg_id]
    save_settings(settings)
    flash("ادمین حذف شد.", "success")
    return redirect(url_for("admin", tab="users"))


@app.post("/admin/settings")
@login_required
@admin_required
def admin_settings():
    for key in ("bot_domain", "support_link", "telegram_proxy_url", "card_num", "payment_channel_chat_id", "xui_two_factor_code"):
        if key in request.form:
            settings[key] = request.form.get(key, settings.get(key, "")).strip()
    if any(key in request.form for key in ("crypto_wallet_bnb", "crypto_wallet_trx", "crypto_wallet_usdt_trc20", "crypto_wallet_usdt_bep20")):
        wallets = settings.get("crypto_wallets") or {}
        settings["crypto_wallets"] = {
            "bnb": request.form.get("crypto_wallet_bnb", wallets.get("bnb", "")).strip(),
            "trx": request.form.get("crypto_wallet_trx", wallets.get("trx", "")).strip(),
            "usdt_trc20": request.form.get("crypto_wallet_usdt_trc20", wallets.get("usdt_trc20", "")).strip(),
            "usdt_bep20": request.form.get("crypto_wallet_usdt_bep20", wallets.get("usdt_bep20", "")).strip(),
        }
    if "referral_percent" in request.form:
        settings["referral_percent"] = normalize_tg_id(request.form.get("referral_percent")) or 0
    if "referral_rate" in request.form:
        settings["referral_rate"] = normalize_tg_id(request.form.get("referral_rate")) or 0
    if "admin_chat_ids" in request.form:
        settings["admin_chat_ids"] = parse_int_list(request.form.get("admin_chat_ids", ""))
    if "channels" in request.form:
        settings["channels"] = [item.strip() for item in request.form.get("channels", "").splitlines() if item.strip()]
    if "pricing_mode" in request.form:
        settings["pricing_mode"] = "fixed" if request.form.get("pricing_mode") == "fixed" else "range"
    if "ranges" in request.form:
        settings["ranges"] = parse_int_list(request.form.get("ranges", ""))
    if "prices" in request.form:
        settings["prices"] = parse_int_list(request.form.get("prices", ""))
    if "fixed_prices" in request.form:
        settings["fixed_prices"] = parse_fixed_prices(request.form.get("fixed_prices", ""))
    save_settings(settings)
    flash("تنظیمات پنل ذخیره شد.", "success")
    return redirect(url_for("admin", tab=request.form.get("admin_tab", "settings")))


@app.post("/admin/telegram-proxy-config")
@login_required
@admin_required
def admin_telegram_proxy_config():
    raw_text = request.form.get("telegram_xray_config_json", "").strip()
    if not raw_text:
        flash("کانفیگ JSON پروکسی تلگرام وارد نشده است.", "error")
        return redirect(url_for("admin", tab="settings"))
    ok, message = apply_telegram_proxy_config(raw_text)
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin", tab="settings"))


@app.post("/admin/web-banner")
@login_required
@admin_required
def admin_web_banner():
    banner = request.files.get("web_banner")
    if not banner or not banner.filename:
        flash("تصویر بنر انتخاب نشده است.", "error")
        return redirect(url_for("admin", tab="settings"))
    filename = banner.filename.lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    suffix = Path(filename).suffix
    if suffix not in allowed:
        flash("فرمت تصویر بنر معتبر نیست.", "error")
        return redirect(url_for("admin", tab="settings"))
    banner_dir = BASE_DIR / "static" / "web"
    banner_dir.mkdir(parents=True, exist_ok=True)
    target = banner_dir / f"dashboard_banner{suffix}"
    banner.save(target)
    settings["web_banner_path"] = f"web/{target.name}"
    save_settings(settings)
    flash("بنر سراسری پنل ذخیره شد.", "success")
    return redirect(url_for("admin", tab="settings"))


@app.errorhandler(Exception)
def handle_error(exc):
    app.logger.error(traceback.format_exc())
    return render_template("web_panel_error.html", error=exc), 500


if __name__ == "__main__":
    app.run(
        host=os.environ.get("WEB_PANEL_HOST", "0.0.0.0"),
        port=int(os.environ.get("WEB_PANEL_PORT", 5050)),
        debug=True,
    )
