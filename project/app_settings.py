from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.environ.get("WEB_PANEL_SETTINGS", BASE_DIR / "web_panel_settings.json"))
EXAMPLE_SETTINGS_PATH = BASE_DIR / "web_panel_settings.example.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def default_settings() -> dict[str, Any]:
    return _read_json(EXAMPLE_SETTINGS_PATH)


def load_settings() -> dict[str, Any]:
    settings = default_settings()
    settings.update(_read_json(SETTINGS_PATH))

    env_map = {
        "WEB_PANEL_SECRET": "panel_secret",
        "BOT_DOMAIN": "bot_domain",
        "BOT_TOKEN": "bot_token",
        "SUPPORT_LINK": "support_link",
        "CARD_NUM": "card_num",
        "ADMIN_WEB_PASSWORD": "admin_web_password",
        "ADMIN_WEB_PASSWORD_HASH": "admin_web_password_hash",
        "XUI_TWO_FACTOR_CODE": "xui_two_factor_code",
        "PAYMENT_CHANNEL_CHAT_ID": "payment_channel_chat_id",
        "TELEGRAM_PROXY_URL": "telegram_proxy_url",
        "PROXYCHAIN_URL": "telegram_proxy_url",
    }
    for env_name, key in env_map.items():
        if os.environ.get(env_name):
            settings[key] = os.environ[env_name]
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_settings(**changes: Any) -> dict[str, Any]:
    settings = load_settings()
    settings.update(changes)
    save_settings(settings)
    return settings
