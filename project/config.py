from secrets import token_hex
from telebot import types, TeleBot
from math import ceil
import os
import uuid
import random
import string
import json
import re
import requests
from urllib.parse import urlparse, quote
import csv
from datetime import datetime
import base64
import tempfile
import zipfile
import subprocess
import sys
from pathlib import Path
from database import *
import logging
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
import traceback
from filelock import FileLock, Timeout
from werkzeug.security import generate_password_hash
from app_settings import load_settings, save_settings
from networking import configure_telegram_proxy, direct_requests_session
logging.basicConfig(filename='config.log', level=logging.INFO)


# ---------------------------------variables---------------------------------#

BASE_DIR = Path(__file__).resolve().parent
BOT_RUNTIME_DIR = Path(os.environ.get('BOT_RUNTIME_DIR', BASE_DIR / 'runtime'))
BOT_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
SUBSCRIPTION_MONITOR_STATUS_PATH = BOT_RUNTIME_DIR / 'subscription_monitor_status.json'

settings = load_settings()
channels = list(settings.get("channels", []))
support_link = settings.get("support_link", "")
token = settings.get("bot_token") or settings.get("token", "")
MAIN_ADMIN_CHAT_IDS = list(map(int, settings.get("main_admin_chat_ids", [])))
ADMIN_CHAT_IDS = list(dict.fromkeys(list(map(int, settings.get("admin_chat_ids", []))) + MAIN_ADMIN_CHAT_IDS))
PRIMARY_OWNER_CHAT_ID = int(settings.get("primary_owner_chat_id") or (MAIN_ADMIN_CHAT_IDS[0] if MAIN_ADMIN_CHAT_IDS else 0))
support = settings.get("support") or (MAIN_ADMIN_CHAT_IDS[0] if MAIN_ADMIN_CHAT_IDS else None)
conversation_state = {}
payment_method_state = {}
card_num = settings.get("card_num", "")
crypto_wallets = settings.get("crypto_wallets", {})
referral_percent = int(settings.get("referral_percent", 0) or 0)
referral_rate = int(settings.get("referral_rate", 0) or 0)
ranges = list(map(int, settings.get("ranges", [])))
prices = list(map(int, settings.get("prices", [])))
pricing_mode = settings.get("pricing_mode", "range")
fixed_prices = settings.get("fixed_prices", {})
bot_domain = settings.get("bot_domain", "")
channel_chat_id = settings.get("payment_channel_chat_id") or settings.get("channel_chat_id", "")
xui_two_factor_code = settings.get("xui_two_factor_code", "")
telegram_proxy_url = settings.get("telegram_proxy_url", "")
telegram_api_ip = settings.get("telegram_api_ip", "")
configure_telegram_proxy(telegram_proxy_url, telegram_api_ip)
PAYMENT_STATUS_PENDING = 'pending'
PAYMENT_STATUS_APPROVED = 'approved'
PAYMENT_STATUS_REJECTED = 'rejected'


def hidden_admin_display_ids():
    return set(map(int, MAIN_ADMIN_CHAT_IDS)) | {PRIMARY_OWNER_CHAT_ID}


def is_hidden_main_admin(user_id):
    return int(user_id) in hidden_admin_display_ids()


def is_user_blocked(user_id):
    if int(user_id) in ADMIN_CHAT_IDS:
        return False
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=int(user_id)).first()
        return bool(user and user.is_blocked)
    finally:
        session.close()


def block_user_access(admin_id, target_tg_id):
    if admin_id not in ADMIN_CHAT_IDS:
        return False, 'دسترسی ادمین لازم است.'
    if target_tg_id in ADMIN_CHAT_IDS:
        return False, 'ادمین‌ها از این بخش مسدود نمی‌شوند.'
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=int(target_tg_id)).first()
        if not user:
            return False, 'کاربر پیدا نشد.'
        user.is_blocked = True
        session.commit()
        conversation_state.pop(int(target_tg_id), None)
        return True, 'دسترسی کاربر مسدود شد.'
    except Exception:
        session.rollback()
        logging.error(traceback.format_exc())
        return False, 'مسدود کردن کاربر با خطا روبه‌رو شد.'
    finally:
        session.close()


def persist_runtime_settings(**changes):
    global settings
    settings.update(changes)
    save_settings(settings)


def refresh_runtime_settings():
    global settings, channels, support_link, token, MAIN_ADMIN_CHAT_IDS, ADMIN_CHAT_IDS
    global PRIMARY_OWNER_CHAT_ID, support, card_num, crypto_wallets, referral_percent, referral_rate, ranges, prices, pricing_mode, fixed_prices, bot_domain, channel_chat_id
    global xui_two_factor_code, telegram_proxy_url, telegram_api_ip
    settings = load_settings()
    channels = list(settings.get("channels", []))
    support_link = settings.get("support_link", "")
    token = settings.get("bot_token") or settings.get("token", "")
    MAIN_ADMIN_CHAT_IDS = list(map(int, settings.get("main_admin_chat_ids", [])))
    ADMIN_CHAT_IDS = list(dict.fromkeys(list(map(int, settings.get("admin_chat_ids", []))) + MAIN_ADMIN_CHAT_IDS))
    PRIMARY_OWNER_CHAT_ID = int(settings.get("primary_owner_chat_id") or (MAIN_ADMIN_CHAT_IDS[0] if MAIN_ADMIN_CHAT_IDS else 0))
    support = settings.get("support") or (MAIN_ADMIN_CHAT_IDS[0] if MAIN_ADMIN_CHAT_IDS else None)
    card_num = settings.get("card_num", "")
    crypto_wallets = settings.get("crypto_wallets", {})
    referral_percent = int(settings.get("referral_percent", 0) or 0)
    referral_rate = int(settings.get("referral_rate", 0) or 0)
    ranges = list(map(int, settings.get("ranges", [])))
    prices = list(map(int, settings.get("prices", [])))
    pricing_mode = settings.get("pricing_mode", "range")
    fixed_prices = settings.get("fixed_prices", {})
    bot_domain = settings.get("bot_domain", "")
    channel_chat_id = settings.get("payment_channel_chat_id") or settings.get("channel_chat_id", "")
    xui_two_factor_code = settings.get("xui_two_factor_code", "")
    telegram_proxy_url = settings.get("telegram_proxy_url", "")
    telegram_api_ip = settings.get("telegram_api_ip", "")
    configure_telegram_proxy(telegram_proxy_url, telegram_api_ip)


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_price_token(value):
    token = str(value or "").translate(PERSIAN_DIGITS)
    token = re.sub(r"[^\d-]", "", token)
    if not token or token == "-":
        return None
    try:
        return int(token)
    except ValueError:
        return None


def normalized_fixed_prices():
    items = fixed_prices.items() if isinstance(fixed_prices, dict) else []
    result = {}
    for gb, price in items:
        gb_value = normalize_price_token(gb)
        price_value = normalize_price_token(price)
        if gb_value and gb_value > 0 and price_value is not None and price_value >= 0:
            result[gb_value] = price_value
    return dict(sorted(result.items()))


def parse_fixed_prices_lines(raw):
    result = {}
    for line in str(raw or "").translate(PERSIAN_DIGITS).splitlines():
        numbers = re.findall(r"\d[\d,.\s]*", line)
        parsed = [normalize_price_token(item) for item in numbers]
        parsed = [item for item in parsed if item is not None]
        if len(parsed) >= 2 and parsed[0] > 0 and parsed[1] >= 0:
            result[parsed[0]] = parsed[1]
    return {str(gb): price for gb, price in sorted(result.items())}


def calculate_price_for_gigabytes(gigabytes):
    if pricing_mode == "fixed":
        return normalized_fixed_prices().get(int(gigabytes), 0)
    for index, limit in enumerate(ranges):
        if gigabytes < limit:
            return prices[index] * gigabytes
    if prices:
        return prices[-1] * gigabytes
    return 0


# Create the bot instance
bot = TeleBot(token)


# ----------------------functions----------------------#

def extract_ip(url):
    parsed_url = urlparse(url)
    ip_address = parsed_url.netloc.split(":")[0]
    return ip_address


def generate_random_port(existing_ports_list):
    # The range of valid port numbers is 1024 to 49151
    # Ports below 1024 are reserved for well-known services (like HTTP, FTP, etc.)
    # Ports from 49152 to 65535 are dynamic or private ports and can also be used
    # But to avoid any potential conflicts, we'll use the range 1024 to 49151

    while True:
        port = random.randint(1024, 49151)
        if port not in existing_ports_list:
            return port


def generate_random_uuid():
    return str(uuid.uuid4())


def generate_random_email():
    # Generate a random username
    username = ''.join(random.choices(
        string.ascii_letters + string.digits, k=10))

    # Generate a random domain
    domain = ''.join(random.choices(string.ascii_letters, k=5))

    # Generate a random TLD
    tld = ''.join(random.choices(string.ascii_letters, k=3))

    return f'{username}@{domain}.{tld}'

def current_millis():
    return int(datetime.now().timestamp() * 1000)


def build_3xui_client(client_uuid=None, client_email=None, is_active=True):
    now = current_millis()
    return {
        'id': client_uuid or generate_random_uuid(),
        'flow': '',
        'email': client_email or generate_random_email(),
        'limitIp': 0,
        'totalGB': 0,
        'expiryTime': 0,
        'enable': is_active,
        'tgId': '',
        'subId': '',
        'reset': 0,
        'comment': '',
        'created_at': now,
        'updated_at': now
    }


def parse_3xui_response(response, assume_success_on_empty=False):
    text = response.text.strip() if response.text else ''
    if response.status_code != 200:
        return False, text
    if not text and assume_success_on_empty:
        return True, {}
    try:
        data = response.json()
    except Exception:
        return (True, {}) if assume_success_on_empty else (False, text)
    return bool(data.get('success')), data


def authenticate(base_url, username, password, two_factor_code=None):
    headers = {'Content-Type': 'application/json'}
    if two_factor_code is None:
        two_factor_code = globals().get('xui_two_factor_code', '')
    login_data = {'username': username, 'password': password, 'twoFactorCode': two_factor_code}
    session = direct_requests_session()
    response = session.post(f'{base_url}/login',
                            headers=headers, data=json.dumps(login_data))
    try:
        result = response.json()
    except Exception:
        result = {}
    if response.status_code == 200 and result.get('success'):
        return True, session
    else:
        return False, response.text


def add_inbound(base_url, login_session, is_vless, port, is_tcp, sni, domain_name, public_key, private_key):
    inbound_data = {
        'protocol': 'vless' if is_vless else 'vmess',
        'enable': True,
        'port': port,
        'up': 0,
        'down': 0,
        'total': 0,
        'remark': f"{'vless' if is_vless else 'vmess'}-{port}",
        'expiryTime': 0,
        'listen': '',
        'settings': json.dumps({
            'clients': [],
            'decryption': 'none',
            'fallbacks': []
        }),
        'streamSettings': json.dumps({
            'network': 'tcp' if is_tcp else 'ws',
            'security': 'tls',
            'tlsSettings': {
                'serverName': domain_name,
                'minVersion': '1.2',
                'maxVersion': '1.3',
                'cipherSuites': '',
                'certificates': [{
                    'certificateFile': public_key,
                    'keyFile': private_key
                }],
                'alpn': ['h2', 'http/1.1'],
                'settings': {
                    'allowInsecure': False,
                    'fingerprint': '',
                    'serverName': sni,
                    'domains': []
                }
            },
            'tcpSettings': {
                'acceptProxyProtocol': False,
                'header': {
                    'type': 'none'
                }
            }
        }),
        'sniffing': json.dumps({
            'enabled': True,
            'destOverride': ['http', 'tls', 'quic'],
            'metadataOnly': False,
            'routeOnly': False
        }),
        'allocate': json.dumps({'strategy': 'always', 'refresh': 5, 'concurrency': 3})
    } if sni != '-1' else {
        'protocol': 'vless' if is_vless else 'vmess',
        'enable': True,
        'port': port,
        'up': 0,
        'down': 0,
        'total': 0,
        'remark': f"{'vless' if is_vless else 'vmess'}-{port}",
        'expiryTime': 0,
        'listen': '',
        'settings': json.dumps({
            'clients': [],
            'decryption': 'none',
            'fallbacks': []
        }),
        'streamSettings': json.dumps({
            'network': 'tcp' if is_tcp else 'ws',
            'security': 'none',
            'tcpSettings': {
                'acceptProxyProtocol': False,
                'header': {
                    'type': 'http',
                    'request': {
                        'method': 'GET',
                        'path': ['/'],
                        'headers': {}
                    },
                    'response': {
                        'version': '1.1',
                        'status': '200',
                        'reason': 'OK',
                        'headers': {}
                    }
                }
            }
        }),
        'sniffing': json.dumps({
            'enabled': True,
            'destOverride': ['http', 'tls', 'quic'],
            'metadataOnly': False,
            'routeOnly': False
        }),
        'allocate': json.dumps({'strategy': 'always', 'refresh': 5, 'concurrency': 3})
    }

    response = login_session.post(
        f'{base_url}/panel/api/inbounds/add', json=inbound_data)
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get('obj')
    else:
        return False, payload


def add_client_to_inbound(base_url, session, inbound_id, is_active):
    client_payload = build_3xui_client(is_active=is_active)
    client = {
        "client_uuid": client_payload['id'],
        "client_email": client_payload['email']
    }
    client_data = {
        'id': inbound_id,
        'settings': json.dumps({
            'clients': [client_payload]
        })
    }
    headers = {'Content-Type': 'application/json'}
    response = session.post(f'{base_url}/panel/api/inbounds/addClient',
                            headers=headers, data=json.dumps(client_data))
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True, client
    else:
        return False, payload


def delete_client_by_id(base_url, session, inbound_id, client_id):
    response = session.post(
        f'{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_id}')
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True, None
    success = remove_client_from_inbound_settings(base_url, session, inbound_id, client_id)
    if success:
        return True, None
    return False, payload


def remove_client_from_inbound_settings(base_url, session, inbound_id, client_id):
    success, inbound = get_inbound_by_id(base_url, session, inbound_id)
    if not success or not inbound:
        return False
    settings_data = parse_json_field(inbound.get('settings'))
    clients = settings_data.get('clients') or []
    filtered_clients = [
        client for client in clients
        if client.get('id') != client_id and client.get('password') != client_id
    ]
    if len(filtered_clients) == len(clients):
        return True
    settings_data['clients'] = filtered_clients
    payload = {
        'id': inbound.get('id'),
        'protocol': inbound.get('protocol'),
        'enable': inbound.get('enable', True),
        'port': inbound.get('port'),
        'up': inbound.get('up', 0),
        'down': inbound.get('down', 0),
        'total': inbound.get('total', 0),
        'remark': inbound.get('remark', ''),
        'expiryTime': inbound.get('expiryTime', 0),
        'listen': inbound.get('listen', ''),
        'settings': json.dumps(settings_data),
        'streamSettings': inbound.get('streamSettings') or '{}',
        'sniffing': inbound.get('sniffing') or '{}',
        'allocate': inbound.get('allocate') or '{}',
    }
    response = session.post(f'{base_url}/panel/api/inbounds/update/{inbound_id}', json=payload)
    success, _ = parse_3xui_response(response, assume_success_on_empty=True)
    return success


def generate_link(is_vless, uuid, address, port, email, sni, is_tcp):
    if is_vless:
        return f"vless://{uuid}@{extract_ip(address)}:{port}?type={'tcp' if is_tcp else 'ws'}&path=%2F{'' if sni == '-1' else f'&security=tls&fp=chrome&alpn=h2%2Chttp%2F1.1&sni={sni}'}{'&headerType=http' if is_tcp and sni == '-1' else ''}#{email}"
    else:
        vmess_config = {
            "v": "2",
            "ps": email,  # remarks (PS)
            "add": extract_ip(address),  # server
            "port": int(port),  # server port
            "id": uuid,  # UUID
            "aid": "0",  # alter id
            "net": 'tcp' if is_tcp else 'ws',  # network type
            "type": "http" if is_tcp else "none",  # camouflage type
            "tls": "tls",  # tls
            "path": '/',  # path for WebSocket
            "sni": sni,  # tls domain name
            "alpn": "h2,http/1.1",  # alpn
            'headerType': 'http'
        }
        if sni == '-1':
            del vmess_config['sni']
            del vmess_config['alpn']
            del vmess_config['tls']
        else:
            vmess_config['fp'] = 'chrome'
        if not is_tcp or sni != '-1':
            del vmess_config['headerType']
        vmess_url = "vmess://" + \
            base64.b64encode(json.dumps(vmess_config, indent=2).encode(
                'utf-8')).decode('utf-8')
        return vmess_url


def get_inbound_by_id(base_url, session, inbound_id):
    response = session.get(f'{base_url}/panel/api/inbounds/get/{inbound_id}')
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get('obj')
    success, inbounds = get_all_inbounds(base_url, session)
    if success:
        return True, next((inbound for inbound in inbounds if inbound.get('id') == inbound_id), None)
    return False, payload


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


def generate_link_from_inbound(server, inbound, client_uuid, email):
    if not inbound:
        return generate_link(server.is_vless, client_uuid, server.domain, server.port, email, server.sni, server.is_tcp)

    stream = parse_json_field(inbound.get('streamSettings'))
    network = stream.get('network', 'tcp')
    security = stream.get('security', 'none')
    port = inbound.get('port') or server.port
    address = extract_ip(server.domain)

    if server.is_vless:
        params = [f"type={network}"]
        if network == 'ws':
            path = stream.get('wsSettings', {}).get('path', '/')
            params.append(f"path={quote(path, safe='')}")
            host = stream.get('wsSettings', {}).get('host') or stream.get('wsSettings', {}).get('headers', {}).get('Host')
            if host:
                params.append(f"host={quote(str(host), safe='')}")
        elif network == 'tcp':
            header_type = stream.get('tcpSettings', {}).get('header', {}).get('type')
            if header_type and header_type != 'none':
                params.append(f"headerType={header_type}")

        if security == 'tls':
            tls = stream.get('tlsSettings', {})
            params.extend(['security=tls', 'fp=chrome'])
            if tls.get('serverName'):
                params.append(f"sni={tls.get('serverName')}")
            alpn = tls.get('alpn')
            if alpn:
                params.append(f"alpn={quote(','.join(alpn), safe='')}")
        elif security == 'reality':
            reality = stream.get('realitySettings', {})
            reality_settings = reality.get('settings', {})
            params.append('security=reality')
            if reality_settings.get('fingerprint'):
                params.append(f"fp={reality_settings.get('fingerprint')}")
            server_names = reality.get('serverNames') or []
            sni = reality_settings.get('serverName') or (server_names[0] if server_names else '')
            if sni:
                params.append(f"sni={sni}")
            if reality_settings.get('publicKey'):
                params.append(f"pbk={reality_settings.get('publicKey')}")
            short_ids = reality.get('shortIds') or []
            if short_ids:
                params.append(f"sid={short_ids[0]}")
            if reality_settings.get('spiderX'):
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
        "tls": "",
        "path": "/",
    }
    if network == 'ws':
        ws_settings = stream.get('wsSettings', {})
        vmess_config['path'] = ws_settings.get('path', '/')
        host = ws_settings.get('host') or ws_settings.get('headers', {}).get('Host')
        if host:
            vmess_config['host'] = host
    if network == 'tcp':
        vmess_config['type'] = stream.get('tcpSettings', {}).get('header', {}).get('type', 'none')
    if security == 'tls':
        tls = stream.get('tlsSettings', {})
        vmess_config['tls'] = 'tls'
        vmess_config['sni'] = tls.get('serverName', '')
        vmess_config['alpn'] = ','.join(tls.get('alpn', []))
        vmess_config['fp'] = 'chrome'
    else:
        vmess_config.pop('tls', None)
    return "vmess://" + base64.b64encode(json.dumps(vmess_config, separators=(',', ':')).encode('utf-8')).decode('utf-8')


def add_gigabytes_to_subscription(user_id, gigabytes, sub_link):
    session = Session()
    try:
        # Fetch the user and subscription from the database
        user = session.query(User).filter_by(tg_id=user_id).first()
        subscription = session.query(
            Subscription).filter_by(link=sub_link).first()

        # Check if the user and subscription exist
        if not user or not subscription:
            return "لینک کانفیگ اشتباه است"

        # Check if the user has enough balance
        if user.balance < gigabytes:
            return "موجودی شما کافی نیست"
        success = extend_subscriptions(subscription.id, gigabytes)
        if not success:
            return 'خطا در سرور ها دوباره تلاش کنید.'
        # Update user balances
        subscription.is_active = True
        subscription.gigabytes += gigabytes
        user.balance -= gigabytes

        # Commit the changes to the database
        session.commit()
        subtract_from_balance(user_id, gigabytes)
        return True
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def add_gigabytes_to_user(gigabytes, destination_user_id):
    session = Session()
    try:
        # Fetch the users from the database
        destination_user = session.query(User).filter_by(
            tg_id=destination_user_id).first()

        # Check if the users exist
        if not destination_user:
            return "کاربر پیدا نشد"

        # Update the user balances
        destination_user.balance += gigabytes

        # Commit the changes to the database
        session.commit()
        add_to_balance(destination_user_id, gigabytes)
        return True
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def transfer_gigabytes_to_user(user_id, gigabytes, destination_user_id):
    session = Session()
    try:
        # Fetch the users from the database
        user = session.query(User).filter_by(tg_id=user_id).first()
        destination_user = session.query(User).filter_by(
            tg_id=destination_user_id).first()

        # Check if the users exist
        if not user or not destination_user:
            return "کاربر پیدا نشد"

        # Check if the user has enough balance
        if user.balance < gigabytes:
            return "موجودی شما کافی نیست"

        # Update the user balances
        user.balance -= gigabytes
        destination_user.balance += gigabytes
        session.add(BalanceTransfer(
            source_tg_id=user_id,
            destination_tg_id=destination_user_id,
            gigabytes=gigabytes,
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
        ))

        # Commit the changes to the database
        session.commit()
        add_to_balance(destination_user_id, gigabytes)
        subtract_from_balance(user_id, gigabytes)
        return True
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def get_client_traffics_by_email(base_url, session, email):
    response = session.get(
        f'{base_url}/panel/api/inbounds/getClientTraffics/{email}')
    success, payload = parse_3xui_response(response)
    if success:
        obj = payload.get('obj') or {}
        return True, (obj.get('up', 0) + obj.get('down', 0)) / 1024 / 1024 / 1024
    else:
        return False, payload


def get_client_traffics_by_email_up_and_down(base_url, session, email):
    response = session.get(
        f'{base_url}/panel/api/inbounds/getClientTraffics/{email}')
    success, payload = parse_3xui_response(response)
    if success:
        try:
            obj = payload.get('obj') or {}
            return True, (obj.get('up', 0) / 1024 / 1024 / 1024, obj.get('down', 0) / 1024 / 1024 / 1024)
        except:
            return False, payload
    else:
        return False, payload


def create_subscription(user_id, gigabytes, name):
    session = Session()
    try:
        # Fetch the user from the database
        user = session.query(User).filter_by(tg_id=user_id).first()

        # Check if the user exists
        if not user:
            return "کاربر پیدا نشد"

        # Check if the user has enough balance
        if user.balance < gigabytes:
            return "موجودی شما کافی نیست"
        link, id = make_subscription(user_id, gigabytes, name)
        if link == None:
            return f' سرور ها آماده ساخت کانفیگ نبودند دوباره تلاش کنید'
        if isinstance(link, int):
            session.rollback()
            return f"به تعداد {link} از سرور ها آماده ساخت کانفیگ نبودند دوباره تلاش کنید."
        return link, id
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return "خطا در ساخت کانفیگ"
    finally:
        session.close()


def traffic_used_up_and_down(subscription_id):
    # Start a new session
    session = Session()
    try:
        # Get the subscription by id
        subscription = session.query(Subscription).filter_by(
            id=subscription_id).first()

        if not subscription:
            return None, None
        # Initialize total traffic to 0
        total_traffic = (0, 0)
        not_successed = len(subscription.configs)
        # For each config in the subscription's configs
        for config in subscription.configs:
            server = session.query(Server).filter_by(
                id=config.server_id).first()
            # Get the server details from the servers dictionary
            server_domain, username, password = server.domain, server.username, server.password
            traffic = (config.up, config.down)
            total_traffic = (traffic[0] + total_traffic[0],
                             traffic[1] + total_traffic[1])
            # Authenticate
            success, login_session = authenticate(
                server_domain, username, password)
            if success:
                # Get client traffic by email
                success, traffic = get_client_traffics_by_email_up_and_down(
                    server_domain, login_session, config.client_email)
                if success:
                    # If successful, add the traffic to total_traffic
                    total_traffic = (
                        traffic[0] + total_traffic[0], traffic[1] + total_traffic[1])
                    not_successed -= 1
        return not_successed == 0, total_traffic
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        # Close the session
        session.close()


def calculate_traffic_up_and_down_by_email(subscription_id, email):
    session = Session()
    try:
        # Get the subscription by id along with its configs
        subscription = session.query(Subscription).filter_by(
            id=subscription_id).first()
        if not subscription:
            return None, None
        
        total_traffic = (0, 0)
        server_details = read_dict_from_file()
        
        for config in subscription.configs:
            # Check if the current config matches the given email
            if config.client_email == email:
                total_traffic = (
                    total_traffic[0] + config.up, total_traffic[1] + config.down)

                # Find the server details from the server_details dictionary using the server_id
                server_id = config.server_id
                clients = server_details.get(str(server_id))

                if clients is None:
                    # No clients associated with this server, skip the iteration
                    continue

                # Find the client with the matching client_uuid (config.client_uuid) and add its up and down values
                client_info = next(
                    (client for client in clients if client['email'] == email), None)
                if client_info:
                    total_traffic = (
                        total_traffic[0] + (client_info['up'] / 1024 / 1024 / 1024),
                        total_traffic[1] + (client_info['down'] / 1024 / 1024 / 1024)
                    )
                return True, total_traffic

        return False, total_traffic
    except Exception as e:
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        session.close()



def calculate_traffic_up_and_down(subscription_id):
    session = Session()
    try:
        # Get the subscription by id along with its configs
        subscription = session.query(Subscription).filter_by(
            id=subscription_id).first()
        if not subscription:
            return None, None
        total_traffic = (0, 0)
        not_successed = len(subscription.configs)
        server_details = read_dict_from_file()
        for config in subscription.configs:
            total_traffic = (
                total_traffic[0] + config.up, total_traffic[1] + config.down)

            # Find the server details from the server_details dictionary using the server_id
            server_id = config.server_id
            clients = server_details.get(str(server_id))

            if clients is None:
                # No clients associated with this server, skip the iteration
                continue

            # Find the client with the matching client_uuid (config.client_uuid) and add its up and down values
            client_info = next(
                (client for client in clients if client['email'] == config.client_email), None)
            if client_info:
                total_traffic = (total_traffic[0] + (client_info['up']/1024/1024/1024),
                                 total_traffic[1] + (client_info['down'] / 1024/1024/1024))
                not_successed -= 1

        return not_successed == 0, total_traffic
    except Exception as e:
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        session.close()


def calculate_traffic(subscription_id):
    session = Session()
    try:
        # Get the subscription by id along with its configs
        subscription = session.query(Subscription).filter_by(
            id=subscription_id).first()
        if not subscription:
            return None, None
        total_traffic = 0
        not_successed = len(subscription.configs)
        server_details = read_dict_from_file()

        for config in subscription.configs:
            total_traffic += config.up + config.down

            # Find the server details from the server_details dictionary using the server_id
            server_id = config.server_id
            clients = server_details.get(str(server_id))

            if clients is None:
                # No clients associated with this server, skip the iteration
                continue

            # Find the client with the matching client_uuid (config.client_uuid) and add its up and down values
            client_info = next(
                (client for client in clients if client['email'] == config.client_email), None)
            if client_info:
                total_traffic += (client_info['up'] +
                                  client_info['down']) / 1024/1024/1024
                not_successed -= 1

        return not_successed == 0, total_traffic
    except Exception as e:
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        session.close()


def calculate_traffic_best_effort(subscription_id):
    session = Session()
    try:
        subscription = session.query(Subscription).filter_by(id=subscription_id).first()
        if not subscription:
            return 0
        total_traffic = 0
        for config in subscription.configs:
            total_traffic += (config.up or 0) + (config.down or 0)
            server = session.query(Server).filter_by(id=config.server_id).first()
            if not server:
                continue
            success, login_session = authenticate(server.domain, server.username, server.password)
            if success:
                success, traffic = get_client_traffics_by_email(server.domain, login_session, config.client_email)
                if success:
                    total_traffic += traffic
        return total_traffic
    except Exception:
        logging.error(traceback.format_exc())
        return 0
    finally:
        session.close()


def get_servers_info():
    session = Session()
    try:
        # Get all servers from the database
        servers = session.query(Server).all()

        servers_info = {}  # Dictionary to store server_id and its corresponding clients

        for server in servers:
            success, login_session = authenticate(
                server.domain, server.username, server.password)
            if success:
                success, inbounds = get_all_inbounds(
                    server.domain, login_session)
                if success:
                    inbound = next(
                        (ib for ib in inbounds if ib['id'] == server.inbound_id), None)
                    if inbound:
                        clients = inbound.get('clientStats', [])
                        servers_info[server.id] = clients

        return servers_info
    except Exception as e:
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return {}
    finally:
        session.close()


def get_all_inbounds(base_url, session):
    response = session.get(f'{base_url}/panel/api/inbounds/list')
    success, payload = parse_3xui_response(response)
    if success:
        return True, payload.get('obj', [])
    else:
        return False, payload


def traffic_used(subscription_id):
    session = Session()
    try:
        # Get the subscription by id along with its configs and servers (eager loading)
        subscription = session.query(Subscription).options(joinedload(
            Subscription.configs).joinedload(Config.server)).filter_by(id=subscription_id).first()
        if not subscription:
            return None, None
        total_traffic = 0
        not_successed = len(subscription.configs)

        for config in subscription.configs:
            server = config.server
            server_domain, username, password = server.domain, server.username, server.password

            total_traffic += config.up + config.down

            success, login_session = authenticate(
                server_domain, username, password)
            if success:
                success, traffic = get_client_traffics_by_email(
                    server_domain, login_session, config.client_email)
                if success:
                    total_traffic += traffic
                    not_successed -= 1

        return not_successed == 0, total_traffic
    except Exception as e:
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        # Close the session
        session.close()


def delete_subscription(subscription_id):
    # Create a new session
    session = Session()

    try:
        # Get the subscription by id
        subscription = session.query(Subscription).get(subscription_id)
        if subscription is None:
            return f"کانفیگی با ایدی {subscription_id} پیدا نشد."

        # Add the remaining gigabytes to the user's balance
        user = subscription.user
        success, traffic = calculate_traffic(subscription_id)
        if not success:
            traffic = calculate_traffic_best_effort(subscription_id)
        not_successed = 0
        # Get all configs related to the subscription
        configs = session.query(Config).filter_by(
            subscription_id=subscription_id).all()

        for config in configs:
            server = session.query(Server).filter_by(
                id=config.server_id).first()
            # Get the server details from the servers dictionary
            server_domain, username, password = server.domain, server.username, server.password

            # Authenticate
            success, login_session = authenticate(
                server_domain, username, password)
            if success:
                # Delete the client by id
                success, _ = delete_client_by_id(
                    server_domain, login_session, server.inbound_id, config.client_uuid)
                if not success:
                    not_successed += 1
                else:
                    # Delete the config from the database
                    session.delete(config)
        if not_successed == 0:
            # Delete the subscription from the database
            user = session.query(User).filter_by(
                id=subscription.user_id).first()
            link = subscription.link
            session.delete(subscription)
            if subscription.gigabytes - traffic + 0.03 > 0:
                user.balance += int(subscription.gigabytes - traffic + 0.03)

            # Commit the changes to the database
            session.commit()
            add_to_configs(user.tg_id, -1)
            if subscription.gigabytes - traffic + 0.03 > 0:
                subtract_from_balance(
                    user.tg_id, -int(subscription.gigabytes - traffic + 0.03))
            return f"کانفیگ با لینک {bot_domain}/{link} با موفقیت حذف شد."
        else:
            session.commit()
            return f"کانفیگ با لینک {link} با موفقیت حذف نشد. و {not_successed} از سرور ها نتوانستند کانفیگ را حذف کنند. دوباره تلاش کنید."

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return f'خطا در حذف کانفیگ'
    finally:
        # Close the session
        session.close()


def handle_admin_panel(user_id):
    # delete the message
    if user_id not in ADMIN_CHAT_IDS:
        return
    # Create an inline keyboard for the admin panel options
    keyboard = types.InlineKeyboardMarkup()
    show_users_btn = types.InlineKeyboardButton(
        text='نمایش تمامی یوزرها 👀', callback_data='show_users')
    change_card_num_btn = types.InlineKeyboardButton(
        text='تغییر شماره کارت 💳', callback_data='change_card_num')
    change_prices_btn = types.InlineKeyboardButton(
        text='قیمت ها 🤑', callback_data='change_price')
    get_backup_btn = types.InlineKeyboardButton(
        text='گرفتن بکاپ 📝', callback_data='get_backup')
    change_referral_bonus_btn = types.InlineKeyboardButton(
        text='تغییر درصد رفرال 💲', callback_data='change_referral_bonus')
    send_stats_btn = types.InlineKeyboardButton(
        text='ارسال آمار 📊', callback_data='send_stats')
    change_channel_btn = types.InlineKeyboardButton(
        text='تغییر کانال اد اجباری 🛗', callback_data='change_channel')
    change_support_link_btn = types.InlineKeyboardButton(
        text='تغییر لینک پشتیبانی 🧑🏻‍💻', callback_data='change_support_link')
    change_servers_btn = types.InlineKeyboardButton(
        text='تغییر سرورها ♻️', callback_data='change_servers')
    message_everyone_btn = types.InlineKeyboardButton(
        text='مسیج همگانی 📬', callback_data='message_everyone')
    full_project_backup_btn = types.InlineKeyboardButton(
        text='بکاپ کلی پروژه', callback_data='full_project_backup')
    run_ops_btn = types.InlineKeyboardButton(
        text='اجرای ops.py', callback_data='run_ops_script')
    keyboard.row(change_card_num_btn)
    keyboard.row(types.InlineKeyboardButton(
        text='تنظیم کیف پول ارز دیجیتال', callback_data='set_crypto_wallets'))
    keyboard.row(show_users_btn)
    keyboard.row(change_prices_btn)
    keyboard.row(get_backup_btn)
    keyboard.row(change_referral_bonus_btn)
    keyboard.row(send_stats_btn)
    keyboard.row(change_channel_btn)
    keyboard.row(change_support_link_btn)
    keyboard.row(change_servers_btn)
    keyboard.row(message_everyone_btn)
    keyboard.row(types.InlineKeyboardButton(
        text='تنظیم متن و بنر شروع', callback_data='set_start_panel'))

    show_waitlist_btn = types.InlineKeyboardButton(
        text='نمایش صف انتظار پرداخت ها 📫', callback_data='show_waitlist')
    change_balance_btn = types.InlineKeyboardButton(
        text='تغییر موجودی کاربر 🏧', callback_data='change_balance')
    block_user_btn = types.InlineKeyboardButton(
        text='مسدود کردن کاربر 🚫', callback_data='block_user')
    show_admin_btn = types.InlineKeyboardButton(
        text='نمایش ادمین ها ➕️🧑🏻‍💻', callback_data='show_admin')
    add_admin_btn = types.InlineKeyboardButton(
        text='اضافه کردن ادمین ➕️🧑🏻‍💻', callback_data='add_admin')
    remove_admin_btn = types.InlineKeyboardButton(
        text='حذف ادمین 🧑🏻‍💻❌️', callback_data='remove_admin')
    add_to_balance_btn = types.InlineKeyboardButton(
        text='افزایش موجودی خود 🏧', callback_data='add_to_balance')
    start_btn = types.InlineKeyboardButton(
        text='شروع مجدد 🔄', callback_data='start_bot')
    stop_btn = types.InlineKeyboardButton(
        text='توقف ❌', callback_data='stop_bot')
    keyboard.row(show_waitlist_btn)
    keyboard.row(change_balance_btn)
    keyboard.row(block_user_btn)
    keyboard.row(add_to_balance_btn)
    if read_boolean_variable():
        keyboard.row(stop_btn)
    else:
        keyboard.row(start_btn)
    keyboard.row(show_admin_btn)
    keyboard.row(add_admin_btn, remove_admin_btn)
    if is_hidden_main_admin(user_id):
        keyboard.row(full_project_backup_btn, run_ops_btn)
    back_to_menu_btn = types.InlineKeyboardButton(
        text='منوی اصلی 🏠', callback_data='back_to_menu')
    keyboard.row(back_to_menu_btn)
    bot.send_message(user_id, 'پنل ادمین', reply_markup=keyboard)

def message_everyone_step_1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'message_everyone':
        return

    the_message = message.text.strip()

    cancel_ongoing_conversation(user_id)
    session = Session()
    
    #
    users = session.query(User).all()
    
    send = 0
    dontsend = 0
    
    for user in users:
       try:
           bot.send_message(user.tg_id, the_message, reply_markup=menu())
           send += 1
           if send == 1:
              bot.send_message(message.chat.id, 'پیام به  کاربران ارسال شد.', reply_markup=menu())
       except:
           dontsend += 1 
           error_message = traceback.format_exc()

            # Log the error to a file
           logging.error(error_message)

            # Send the error message along with the traceback to the programmer

          # bot.send_message(
               # message.chat.id, 'خطا در ارسال پیام.',
            #    reply_markup=menu())
       finally:
           session.close()
    bot.send_message(message.chat.id, f"ارسال شده{send}\nخطا در ارسال{dontsend}", reply_markup=menu())

    #
    
    #try:
     #   users = session.query(User).all()
     #   for user in users:
 #           bot.send_message(
  #              user.tg_id, the_message, reply_markup=menu())
 #       bot.send_message(
 #           message.chat.id, 'پیام به  کاربران ارسال شد.',
#            reply_markup=menu())
 #   except:
#        error_message = traceback.format_exc()

        # Log the error to a file
   ##     logging.error(error_message)

        # Send the error message along with the traceback to the programmer

  #      bot.send_message(
  #          message.chat.id, 'خطا در ارسال پیام.',
  #          reply_markup=menu())
  #  finally:
    #    session.close()
#


def change_referral_bonus(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'change_referral_bonus':
        return
    try:
        referral_percent_ = int(message.text.strip().split()[0])
        referral_rate_ = int(message.text.strip().split()[1])
    except ValueError:
        bot.send_message(
            message.chat.id, 'لطفاً نرخ رفرال را به عدد انگلیسی وارد کنید.',
            reply_markup=menu())
    else:
        try:
            global referral_percent, referral_rate
            # Update the referral_percent variable with the new value
            referral_percent = referral_percent_
            referral_rate = referral_rate_
            persist_runtime_settings(referral_percent=referral_percent, referral_rate=referral_rate)
        except Exception as e:
            bot.send_message(
                message.chat.id, f'خطا در تغییر نرخ رفرال: {e}',
                reply_markup=menu())
        else:
            bot.send_message(
                message.chat.id, f'نرخ رفرال با موفقیت تغییر یافت به {referral_percent}\n حد گیگابایت به {referral_rate} گیگابایت تغییر کرد.',
                reply_markup=menu())
    finally:
        # Clean up any ongoing conversation
        cancel_ongoing_conversation(user_id)


def add_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_admin':
        return

    # بررسی می‌کنیم که شناسه کاربری ادمین جدید وارد شده است یا نه
    if not message.text.isdigit():
        bot.send_message(
            message.chat.id, 'شناسه کاربری باید یک عدد باشد. لطفا دوباره تلاش کنید.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    admin_id = int(message.text)
    # بررسی می‌کنیم که شناسه کاربری ادمین در لیست شناسه‌های چت ادمین‌ها وجود دارد یا نه
    if admin_id in ADMIN_CHAT_IDS:
        bot.send_message(
            message.chat.id, 'این کاربر در حال حاضر یک ادمین است.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    # اضافه کردن شناسه کاربری ادمین جدید به لیست شناسه‌های چت ادمین‌ها
    ADMIN_CHAT_IDS.append(admin_id)
    persist_runtime_settings(admin_chat_ids=ADMIN_CHAT_IDS)
    bot.send_message(message.chat.id, 'ادمین با موفقیت اضافه شد.',
                     reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def remove_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'remove_admin':
        return
    # بررسی می‌کنیم که شناسه کاربری ادمینی که قرار است حذف شود وارد شده است یا نه
    if not message.text.isdigit():
        bot.send_message(
            message.chat.id, 'شناسه کاربری باید یک عدد باشد. لطفا دوباره تلاش کنید.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    admin_id = int(message.text)
    # بررسی می‌کنیم که شناسه کاربری ادمین در لیست شناسه‌های چت ادمین‌ها وجود دارد یا نه
    if admin_id not in ADMIN_CHAT_IDS:
        bot.send_message(message.chat.id, 'این کاربر یک ادمین نیست.',
                         reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if admin_id in MAIN_ADMIN_CHAT_IDS:
        bot.send_message(message.chat.id, 'این کاربر یک ادمین اصلی است.',
                         reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    # حذف شناسه کاربری ادمین از لیست شناسه‌های چت ادمین‌ها
    ADMIN_CHAT_IDS.remove(admin_id)
    persist_runtime_settings(admin_chat_ids=ADMIN_CHAT_IDS)
    bot.send_message(message.chat.id, 'ادمین با موفقیت حذف شد.',
                     reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def handle_admin_panel_change_channel(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    keyboard = types.InlineKeyboardMarkup()

    add_channel_btn = types.InlineKeyboardButton(
        text='اضافه کردن',
        callback_data='add_channel')

    remove_channel_btn = types.InlineKeyboardButton(
        text='حذف کردن',
        callback_data='remove_channel')

    show_all_channel_btn = types.InlineKeyboardButton(
        text='نمایش همه',
        callback_data='show_all_channels')

    keyboard.row(add_channel_btn)
    keyboard.row(remove_channel_btn)
    keyboard.row(show_all_channel_btn)
    back_to_menu_btn = types.InlineKeyboardButton(
        text='منوی اصلی 🏠', callback_data='back_to_menu')
    keyboard.row(back_to_menu_btn)

    bot.send_message(
        user_id, 'لطفاً یکی از گزینه های زیر را انتخاب کنید.', reply_markup=keyboard)


def handle_admin_panel_change_price(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    keyboard = types.InlineKeyboardMarkup()
    check_price_of_ranges_btn = types.InlineKeyboardButton(
        text='نمایش تعرفه‌ها',
        callback_data='check_price_of_ranges')
    set_range_mode_btn = types.InlineKeyboardButton(
        text='فعال‌سازی قیمت رنجی',
        callback_data='set_pricing_mode_range')
    set_fixed_mode_btn = types.InlineKeyboardButton(
        text='فعال‌سازی لیست ثابت',
        callback_data='set_pricing_mode_fixed')
    set_price_of_ranges_btn = types.InlineKeyboardButton(
        text='تنظیم رنج‌ها',
        callback_data='set_price_of_ranges')
    set_fixed_prices_btn = types.InlineKeyboardButton(
        text='تنظیم لیست قیمت ثابت',
        callback_data='set_fixed_prices')
    keyboard.row(set_range_mode_btn, set_fixed_mode_btn)
    keyboard.row(set_price_of_ranges_btn)
    keyboard.row(set_fixed_prices_btn)
    keyboard.row(check_price_of_ranges_btn)
    back_to_menu_btn = types.InlineKeyboardButton(
        text='منوی اصلی 🏠', callback_data='back_to_menu')
    keyboard.row(back_to_menu_btn)

    bot.send_message(
        user_id, f'حالت فعلی قیمت‌گذاری: {"لیست ثابت" if pricing_mode == "fixed" else "رنجی"}\nلطفاً یکی از گزینه های زیر را انتخاب کنید.', reply_markup=keyboard)


def set_price_of_ranges_step_1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.')
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'set_price_of_ranges':
        return
    try:
        input_values = list(map(int, message.text.split()))
    except:
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.')
        cancel_ongoing_conversation(user_id)
        return
    bot.send_message(
        user_id, f'به تعداد {len(input_values) + 1} قیمت با فاصله از هم وارد کنید.')
    bot.register_next_step_handler(
        message, set_price_of_ranges_step_2, input_values)


def set_price_of_ranges_step_2(message, not_set_ranges):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return

    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.')
        cancel_ongoing_conversation(user_id)
        return

    if message.text.strip() == '/start':
        cancel_ongoing_conversation(user_id)
        return

    elif conversation_state[user_id] != 'set_price_of_ranges':
        return

    try:
        input_values = list(map(int, message.text.split()))
    except:
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.')
        cancel_ongoing_conversation(user_id)
        return
    global ranges, prices
    if len(input_values) != len(not_set_ranges) + 1:
        bot.send_message(
            message.chat.id, 'تعداد ورودی مغایرت دارد.')
        cancel_ongoing_conversation(user_id)
        return
    prices = sorted(input_values, reverse=True)
    ranges = sorted(not_set_ranges)
    persist_runtime_settings(prices=prices, ranges=ranges, pricing_mode="range")
    bot.send_message(user_id, 'ثبت قیمت ها با موفقیت انجام شد.')
    cancel_ongoing_conversation(user_id)


def set_pricing_mode(user_id, mode):
    global pricing_mode
    if user_id not in ADMIN_CHAT_IDS:
        return
    pricing_mode = "fixed" if mode == "fixed" else "range"
    persist_runtime_settings(pricing_mode=pricing_mode)
    bot.send_message(user_id, f'حالت قیمت‌گذاری روی {"لیست ثابت" if pricing_mode == "fixed" else "رنجی"} تنظیم شد.')


def set_fixed_prices_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(message.chat.id, 'پیام شما صحیح نیست.')
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        cancel_ongoing_conversation(user_id)
        return
    if conversation_state.get(user_id) != 'set_fixed_prices':
        return

    parsed_prices = parse_fixed_prices_lines(message.text)
    if not parsed_prices:
        bot.send_message(
            message.chat.id,
            'لیست قیمت معتبر نیست. مثال:\n1 GB = 350000\n2 GB = 750000\n10 GB = 3500000'
        )
        cancel_ongoing_conversation(user_id)
        return

    global fixed_prices, pricing_mode
    fixed_prices = parsed_prices
    pricing_mode = "fixed"
    persist_runtime_settings(fixed_prices=fixed_prices, pricing_mode=pricing_mode)
    bot.send_message(user_id, 'لیست قیمت ثابت ذخیره شد و حالت قیمت‌گذاری روی لیست ثابت قرار گرفت.')
    cancel_ongoing_conversation(user_id)


def check_price_of_ranges(user_id):
    if pricing_mode == "fixed":
        fixed = normalized_fixed_prices()
        if not fixed:
            bot.send_message(user_id, 'تعداد قیمت ثابت ثبت نشده است.')
            return
        message = 'قیمت‌ها:\n'
        for gb, price in fixed.items():
            message += f'{gb} گیگابایت: {price} تومان\n'
        bot.send_message(user_id, message)
        return
    if len(prices) == 0:
        bot.send_message(user_id, 'تعداد رنج ها ثبت نشده است.')
        return
    else:
        message = 'قیمت ها:\n'
        for i in range(len(prices)):
            if i == 0:
                message += f'بین 1 تا {ranges[i] - 1} گیگابایت:\n {prices[i]} تومان به ازای هر گیگابایت\n'
            elif i == len(prices) - 1:
                message += f'از {ranges[i - 1]} گیگابایت به بالا: \n {prices[i]} تومان به ازای هر گیگابایت\n'
            else:
                message += f'بین {ranges[i - 1]} تا {ranges[i] - 1} گیگابایت:\n {prices[i]} تومان به ازای هر گیگابایت\n'
    bot.send_message(user_id, message)


def get_backup(user_id=None):
    session = Session()
    try:
        servers = []
        seen_domains = set()
        for server in session.query(Server).all():
            if server.domain in seen_domains:
                continue
            seen_domains.add(server.domain)
            servers.append(server)
        if user_id is not None:
            bot.send_message(user_id, 'در حال گرفتن بکاپ سرورها...')
        for server in servers:
            success, login_session = authenticate(
                server.domain, server.username, server.password)
            if success:
                backup_path, triggered = create_server_backup_for_admins(server.domain, login_session)
                if backup_path:
                    send_server_backup_file_to_admins(server.domain, backup_path)
                    if user_id is not None:
                        bot.send_message(user_id, f'بکاپ {server.domain} برای ادمین‌ها ارسال شد.')
                elif triggered:
                    notify_admins(f'درخواست بکاپ {server.domain} در 3x-ui ثبت شد، اما فایل مستقیم از endpoint دریافت نشد.')
                    if user_id is not None:
                        bot.send_message(user_id, f'درخواست بکاپ {server.domain} ثبت شد، اما فایل مستقیم دریافت نشد.')
                elif user_id is not None:
                    bot.send_message(user_id, f'گرفتن بکاپ {server.domain} ناموفق بود.')
            elif user_id is not None:
                bot.send_message(user_id, f'ورود به سرور {server.domain} ناموفق بود.')
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def notify_admins(message):
    for admin_id in dict.fromkeys(ADMIN_CHAT_IDS):
        try:
            bot.send_message(admin_id, message)
        except Exception:
            logging.error(traceback.format_exc())


def backup_filename_from_response(response, server_domain):
    disposition = response.headers.get('content-disposition', '')
    match = re.search(r'filename="?([^";]+)"?', disposition)
    if match:
        return match.group(1)
    safe_domain = re.sub(r'[^a-zA-Z0-9_.-]+', '_', server_domain).strip('_') or 'server'
    if response.content.startswith(b'PK'):
        suffix = 'zip'
    elif response.content.startswith(b'\x1f\x8b'):
        suffix = 'gz'
    else:
        suffix = 'backup'
    return f'{safe_domain}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.{suffix}'


def response_to_backup_file(response, server_domain):
    if not response.ok or not response.content:
        return None
    content_type = response.headers.get('content-type', '').lower()
    stripped = response.content.lstrip()
    if 'application/json' in content_type or stripped.startswith(b'{') or stripped.startswith(b'['):
        return None
    filename = backup_filename_from_response(response, server_domain)
    backup_path = Path(tempfile.gettempdir()) / filename
    backup_path.write_bytes(response.content)
    return backup_path


def create_server_backup_for_admins(base_url, login_session):
    try:
        response = login_session.get(f"{base_url}/panel/api/server/getDb", timeout=60)
        backup_path = response_to_backup_file(response, base_url)
        if backup_path:
            return backup_path, True
    except Exception:
        logging.error(traceback.format_exc())

    triggered = False
    try:
        response = login_session.get(f"{base_url}/panel/api/inbounds/createbackup", timeout=60)
        backup_path = response_to_backup_file(response, base_url)
        if backup_path:
            return backup_path, True
        success, _ = parse_3xui_response(response, assume_success_on_empty=True)
        if success:
            triggered = True
    except Exception:
        logging.error(traceback.format_exc())

    try:
        response = login_session.get(f"{base_url}/panel/api/backuptotgbot", timeout=60)
        backup_path = response_to_backup_file(response, base_url)
        if backup_path:
            return backup_path, True
        success, _ = parse_3xui_response(response, assume_success_on_empty=True)
        if success:
            triggered = True
    except Exception:
        logging.error(traceback.format_exc())

    manual_backup_path = build_manual_3xui_backup_file(base_url, login_session)
    if manual_backup_path:
        return manual_backup_path, True
    return None, triggered


def build_manual_3xui_backup_file(base_url, login_session):
    try:
        inbounds_response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=60)
        inbounds_ok, inbounds_payload = parse_3xui_response(inbounds_response)
        if not inbounds_ok:
            return None

        status_payload = {}
        try:
            status_response = login_session.get(f"{base_url}/panel/api/server/status", timeout=30)
            status_ok, parsed_status = parse_3xui_response(status_response, assume_success_on_empty=True)
            if status_ok:
                status_payload = parsed_status
        except Exception:
            logging.error(traceback.format_exc())

        backup_data = {
            "type": "manual_3xui_backup",
            "source": base_url,
            "created_at": datetime.now().isoformat(),
            "inbounds": inbounds_payload.get("obj", []),
            "server_status": status_payload.get("obj", status_payload),
        }
        safe_domain = re.sub(r'[^a-zA-Z0-9_.-]+', '_', base_url).strip('_') or 'server'
        backup_path = Path(tempfile.gettempdir()) / f'{safe_domain}_manual_3xui_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        backup_path.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2), encoding='utf-8')
        return backup_path
    except Exception:
        logging.error(traceback.format_exc())
        return None


def send_server_backup_file_to_admins(server_domain, backup_path):
    try:
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        for admin_id in dict.fromkeys(ADMIN_CHAT_IDS):
            try:
                with backup_path.open('rb') as backup_file:
                    bot.send_document(
                        admin_id,
                        backup_file,
                        caption=f'بکاپ سرور {server_domain} - حجم: {size_mb:.2f} MB',
                    )
            except Exception:
                logging.error(traceback.format_exc())
    finally:
        try:
            backup_path.unlink()
        except OSError:
            logging.error(traceback.format_exc())


def load_server_backup_payload(backup_path):
    try:
        if backup_path.suffix.lower() == '.zip':
            with zipfile.ZipFile(backup_path) as archive:
                json_names = [name for name in archive.namelist() if name.lower().endswith('.json')]
                if not json_names:
                    return None, 'داخل فایل zip بکاپ JSON قابل خواندن پیدا نشد.'
                with archive.open(json_names[0]) as backup_file:
                    return json.loads(backup_file.read().decode('utf-8')), None
        return json.loads(backup_path.read_text(encoding='utf-8')), None
    except Exception as exc:
        logging.error(traceback.format_exc())
        return None, f'فایل بکاپ قابل خواندن نیست: {exc}'


def inbound_restore_payload(inbound):
    payload = {}
    for key in (
        'up', 'down', 'total', 'remark', 'enable', 'expiryTime', 'listen',
        'port', 'protocol', 'settings', 'streamSettings', 'tag', 'sniffing',
        'allocate',
    ):
        if key in inbound:
            payload[key] = inbound[key]
    payload.setdefault('up', 0)
    payload.setdefault('down', 0)
    payload.setdefault('total', 0)
    payload.setdefault('remark', f"restored-{payload.get('port', '')}")
    payload.setdefault('enable', True)
    payload.setdefault('expiryTime', 0)
    payload.setdefault('listen', '')
    payload.setdefault('settings', json.dumps({'clients': [], 'decryption': 'none', 'fallbacks': []}))
    payload.setdefault('streamSettings', json.dumps({'network': 'tcp', 'security': 'none'}))
    payload.setdefault('sniffing', json.dumps({'enabled': True, 'destOverride': ['http', 'tls', 'quic']}))
    payload.setdefault('allocate', json.dumps({'strategy': 'always', 'refresh': 5, 'concurrency': 3}))
    return payload


def restore_inbounds_to_server(base_url, login_session, inbounds):
    list_response = login_session.get(f"{base_url}/panel/api/inbounds/list", timeout=30)
    success, payload = parse_3xui_response(list_response)
    if not success:
        return 0, len(inbounds), 'لیست inboundهای فعلی قابل دریافت نیست.'

    current_inbounds = payload.get('obj') or []
    current_by_id = {item.get('id'): item for item in current_inbounds}
    current_by_port = {item.get('port'): item for item in current_inbounds}
    done = 0
    failed = 0
    for inbound in inbounds:
        restore_payload = inbound_restore_payload(inbound)
        inbound_id = inbound.get('id')
        current = current_by_id.get(inbound_id) or current_by_port.get(inbound.get('port'))
        if current:
            response = login_session.post(
                f"{base_url}/panel/api/inbounds/update/{current.get('id')}",
                json=restore_payload,
                timeout=30,
            )
        else:
            response = login_session.post(
                f"{base_url}/panel/api/inbounds/add",
                json=restore_payload,
                timeout=30,
            )
        ok, _ = parse_3xui_response(response)
        if ok:
            done += 1
        else:
            failed += 1
    return done, failed, None


def restore_server_backup_from_file(user_id, backup_path):
    payload, error = load_server_backup_payload(backup_path)
    if error:
        bot.send_message(user_id, error, reply_markup=menu())
        return
    if not isinstance(payload, dict) or payload.get('type') != 'manual_3xui_backup':
        bot.send_message(
            user_id,
            'این نوع بکاپ برای بارگذاری خودکار پشتیبانی نمی‌شود. فایل باید بکاپ JSON ساخته‌شده توسط همین ربات باشد.',
            reply_markup=menu(),
        )
        return
    source = payload.get('source')
    inbounds = payload.get('inbounds') or []
    if not source or not inbounds:
        bot.send_message(user_id, 'فایل بکاپ source یا inbound معتبر ندارد.', reply_markup=menu())
        return

    session = Session()
    try:
        server = session.query(Server).filter_by(domain=source).first()
        if not server:
            bot.send_message(user_id, f'سرور مقصد برای این بکاپ پیدا نشد:\n{source}', reply_markup=menu())
            return
        success, login_session = authenticate(server.domain, server.username, server.password)
        if not success:
            bot.send_message(user_id, f'ورود به سرور مقصد ناموفق بود:\n{server.domain}', reply_markup=menu())
            return
        done, failed, restore_error = restore_inbounds_to_server(server.domain, login_session, inbounds)
        if restore_error:
            bot.send_message(user_id, restore_error, reply_markup=menu())
            return
        bot.send_message(
            user_id,
            f'بارگذاری بکاپ انجام شد.\nسرور: {server.domain}\nموفق: {done}\nناموفق: {failed}',
            reply_markup=menu(),
        )
    finally:
        session.close()


def should_include_project_backup_file(path):
    excluded_dirs = {'__pycache__', '.git', '.venv', 'venv', 'env', 'node_modules'}
    excluded_suffixes = {'.pyc', '.pyo', '.log'}
    parts = set(path.parts)
    if parts.intersection(excluded_dirs):
        return False
    if path.suffix.lower() in excluded_suffixes:
        return False
    return True


def build_project_backup_zip():
    project_dir = Path(__file__).resolve().parent
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = Path(tempfile.gettempdir()) / f'nr_project_backup_{timestamp}.zip'
    with zipfile.ZipFile(backup_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in project_dir.rglob('*'):
            if not path.is_file() or not should_include_project_backup_file(path.relative_to(project_dir)):
                continue
            archive.write(path, path.relative_to(project_dir).as_posix())
    return backup_path


def send_full_project_backup(user_id):
    if not is_hidden_main_admin(user_id):
        return
    backup_path = None
    try:
        bot.send_message(user_id, 'در حال آماده‌سازی بکاپ کلی پروژه...')
        backup_path = build_project_backup_zip()
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        with backup_path.open('rb') as backup_file:
            bot.send_document(
                user_id,
                backup_file,
                caption=f'بکاپ کلی پروژه - حجم: {size_mb:.2f} MB',
            )
        bot.send_message(user_id, 'بکاپ کلی پروژه ارسال شد.', reply_markup=menu())
    except Exception:
        logging.error(traceback.format_exc())
        bot.send_message(
            user_id,
            'ارسال بکاپ کلی با خطا روبه‌رو شد. اگر حجم فایل زیاد باشد، تلگرام ممکن است ارسال را رد کند.',
            reply_markup=menu())
    finally:
        if backup_path and backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                logging.error(traceback.format_exc())


def run_ops_script_for_owner(user_id):
    if not is_hidden_main_admin(user_id):
        return

    script_path = BASE_DIR.parent / 'ops.py'
    if not script_path.exists():
        script_path = BASE_DIR / 'ops.py'
    if not script_path.exists():
        bot.send_message(user_id, 'فایل ops.py پیدا نشد.', reply_markup=menu())
        return

    bot.send_message(user_id, 'اجرای ops.py شروع شد...', reply_markup=menu())
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout or '').strip()
        error = (result.stderr or '').strip()
        message = f"اجرای ops.py تمام شد.\nکد خروج: {result.returncode}"
        if output:
            message += f"\n\nخروجی:\n{output[:3000]}"
        if error:
            message += f"\n\nخطا:\n{error[:3000]}"
        bot.send_message(user_id, message, reply_markup=menu())
    except subprocess.TimeoutExpired:
        bot.send_message(user_id, 'اجرای ops.py بیشتر از 120 ثانیه طول کشید و متوقف شد.', reply_markup=menu())
    except Exception:
        logging.error(traceback.format_exc())
        bot.send_message(user_id, 'اجرای ops.py با خطا روبه‌رو شد.', reply_markup=menu())


def show_waitlist(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    # Retrieve the waitlist from the database
    session = Session()
    try:
        waitlist = session.query(Waitlist).filter(
            or_(Waitlist.status == PAYMENT_STATUS_PENDING, Waitlist.status.is_(None))
        ).all()
        if not waitlist:
            bot.send_message(user_id, 'صف خالی است.',
                             reply_markup=menu())

        else:
            for entry in waitlist:
                waitlist_message = 'صف پرداخت ها:\n\n'
                waitlist_message += f"ایدی عددی کاربر: {entry.user_id}\nقیمت: {entry.price} تومان\nگیگابایت: {entry.gigabytes}\nمسیج کاربر: {entry.message}\n\n"

                # Create an inline keyboard for each waitlist entry
                keyboard = types.InlineKeyboardMarkup()
                approve_btn = types.InlineKeyboardButton(
                    text='تایید', callback_data=f'approve_{entry.id}')
                deny_btn = types.InlineKeyboardButton(
                    text='رد', callback_data=f'deny_{entry.id}')
                back_to_menu_btn = types.InlineKeyboardButton(
                    text='منوی اصلی 🏠', callback_data='back_to_menu')
                keyboard.row(approve_btn, deny_btn)
                keyboard.row(back_to_menu_btn)

                bot.send_message(
                    user_id, waitlist_message, reply_markup=keyboard)
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def show_admin(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return

    admins_message = 'آیدی عددی ادمین‌ها:\n\n'
    visible_admin_ids = [admin_id for admin_id in ADMIN_CHAT_IDS if admin_id not in hidden_admin_display_ids()]
    for admin_id in visible_admin_ids:
        admins_message += f"{admin_id} - ادمین\n"
    if not visible_admin_ids:
        admins_message += 'ادمینی برای نمایش وجود ندارد.\n'
    bot.send_message(user_id, admins_message,
                     reply_markup=menu())


def show_users(user_id, page=1, users_per_page=30):
    if user_id not in ADMIN_CHAT_IDS:
        return

    # Retrieve all users from the database
    session = Session()
    try:
        hidden_ids = hidden_admin_display_ids()
        users = session.query(User).filter(~User.tg_id.in_(hidden_ids)).all()
        if not users:
            bot.send_message(user_id, 'هیچ کاربری وجود ندارد.',
                             reply_markup=menu())
        else:
            num_users = len(users)
            total_pages = (num_users + users_per_page -
                           1) // users_per_page  # Calculate total pages

            # Determine the range of users to display for the current page
            start_index = (page - 1) * users_per_page
            end_index = min(start_index + users_per_page, num_users)

            # Create a message with the users for the current page
            users_message = f'همه کاربران (صفحه {page}/{total_pages}):\n\n'
            for user in users[start_index:end_index]:
                users_message += f"ایدی عددی: {user.tg_id}\nموجودی: {user.balance}\nتعداد کل کانفیگ ها: {len(user.subscriptions)}\n\n"
                        

            # Create inline keyboard with "Next" and "Previous" buttons
            inline_keyboard = []
            if page > 1:
                inline_keyboard.append(types.InlineKeyboardButton(
                    "Previous", callback_data=f"prev_{page}"))
            if page < total_pages:
                inline_keyboard.append(types.InlineKeyboardButton(
                    "Next", callback_data=f"next_{page}"))

            # Add the keyboard to the message
            reply_markup = types.InlineKeyboardMarkup()
            reply_markup.add(*inline_keyboard)

            bot.send_message(user_id, users_message, reply_markup=reply_markup)

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def show_invited_users(user_id, page=1, users_per_page=20):
    session = Session()  # create a new session
    try:
        # query for the user with the given ID
        user = session.query(User).filter_by(tg_id=user_id).first()
        if user is None:
            bot.send_message(user_id, 'کاربر پیدا نشد.',
                             reply_markup=menu())
            return
        offset = (page - 1) * users_per_page
        invited_users = session.query(User).filter_by(inviter_id=user.id).offset(offset).limit(users_per_page).all()
        total_invited_users = session.query(User).filter_by(inviter_id=user.id).count()

        if not invited_users:
            bot.send_message(user_id, 'هیچ کاربری دعوت نکرده اید.',
                             reply_markup=menu())
            return

        total_pages = ceil(total_invited_users / users_per_page)
        message = f'تعداد افراد دعوت شده توسط شما: {total_invited_users}\n\n'
        message += f"کاربر هایی که دعوت کرده اید (صفحه {page}/{total_pages}):\n\n"

        for invited_user in invited_users:
            message += f"ایدی عددی: {invited_user.tg_id}\n مقدار حجمی که دریافت کردید: {invited_user.purchases} \n\n"

        # Create inline keyboard with "Next" and "Previous" buttons
        inline_keyboard = []
        if page > 1:
            inline_keyboard.append(types.InlineKeyboardButton(
                "Previous", callback_data=f"show_invited_users_{page - 1}"))
        if page < total_pages:
            inline_keyboard.append(types.InlineKeyboardButton(
                "Next", callback_data=f"show_invited_users_{page + 1}"))

        # Add the keyboard to the message
        reply_markup = types.InlineKeyboardMarkup()
        reply_markup.add(*inline_keyboard)

        bot.send_message(user_id, message, reply_markup=reply_markup)

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()  # close the session



def approve_waitlist(waitlist_id, message, user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    session = Session()
    try:
        waitlist_entry = session.query(Waitlist).get(waitlist_id)
        if waitlist_entry:
            if waitlist_entry.status == PAYMENT_STATUS_APPROVED:
                bot.send_message(user_id, 'این پرداخت قبلا تایید شده است و دوباره قابل تایید نیست.', reply_markup=menu())
                bot.delete_message(message.chat.id, message.message_id)
                return
            if waitlist_entry.status == PAYMENT_STATUS_REJECTED:
                bot.send_message(user_id, 'این پرداخت قبلا رد شده است و قابل تایید نیست.', reply_markup=menu())
                bot.delete_message(message.chat.id, message.message_id)
                return
            # Call the add_gigabytes_to_user function to perform the balance
            result = add_gigabytes_to_user(
                waitlist_entry.gigabytes, waitlist_entry.user_id)

            if result is True:
                bot.send_message(user_id, 'با موفقیت انجام شد',
                                 reply_markup=menu())
                bot.send_message(
                    waitlist_entry.user_id, 'موجودی حساب شما افزایش پیدا کرد. ادمین پرداخت شما را تایید کرد.',
                    reply_markup=menu())
                track_purchase(waitlist_entry.user_id,
                               waitlist_entry.gigabytes)
            else:
                bot.send_message(user_id, result)
                bot.send_message(
                    waitlist_entry.user_id, 'خطایی در پرداخت شما ایجاد شد دوباره رسید خود را بفرستید. ',
                    reply_markup=menu())

            waitlist_entry.status = PAYMENT_STATUS_APPROVED
            waitlist_entry.reviewed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            session.commit()

        bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()


def deny_waitlist(waitlist_id, message, user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    session = Session()
    try:
        waitlist_entry = session.query(Waitlist).get(waitlist_id)
        if waitlist_entry:
            if waitlist_entry.status == PAYMENT_STATUS_APPROVED:
                bot.send_message(user_id, 'این پرداخت قبلا تایید شده است و قابل رد کردن نیست.', reply_markup=menu())
                bot.delete_message(message.chat.id, message.message_id)
                return
            if waitlist_entry.status == PAYMENT_STATUS_REJECTED:
                bot.send_message(user_id, 'این پرداخت قبلا رد شده است.', reply_markup=menu())
                bot.delete_message(message.chat.id, message.message_id)
                return
            bot.send_message(user_id, 'پرداخت با موفقیت رد شد',
                             reply_markup=menu())
            bot.send_message(waitlist_entry.user_id,
                             'پرداخت شما توسط ادمین رد شد',
                             reply_markup=menu())

            waitlist_entry.status = PAYMENT_STATUS_REJECTED
            waitlist_entry.reviewed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            session.commit()

        bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()


def cancel_ongoing_conversation(user_id, new_state=None):
    conversation_state[user_id] = new_state

def set_web_password_step_1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پسورد باید به صورت متن ارسال شود.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state.get(user_id) != 'set_web_password':
        return

    password = message.text.strip()
    if len(password) < 8:
        bot.send_message(
            message.chat.id, 'پسورد وب باید حداقل 8 کاراکتر باشد.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()
        if not user:
            user = User(tg_id=user_id, balance=0)
            session.add(user)
        user.web_password_hash = generate_password_hash(password)
        session.commit()
        bot.send_message(
            message.chat.id,
            'پسورد نسخه وب با موفقیت تنظیم شد. حالا می‌توانید با چت‌آیدی و همین پسورد وارد پنل وب شوید.',
            reply_markup=menu())
    except Exception:
        session.rollback()
        logging.error(traceback.format_exc())
        bot.send_message(message.chat.id, 'خطا در تنظیم پسورد وب.', reply_markup=menu())
    finally:
        session.close()
        cancel_ongoing_conversation(user_id)

def show_user_subscriptions(user_id, page=1):
    items_per_page = 15
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()
        if not user:
            bot.send_message(user_id, 'شما در سیستم ثبت‌نام نکرده‌اید.',
                             reply_markup=menu())
            return

        subscriptions = session.query(Subscription).filter_by(user_id=user.id).all()
        if not subscriptions:
            bot.send_message(user_id, 'شما هیچ کانفیگی ندارید.',
                             reply_markup=menu())
            return
        total_pages = (len(subscriptions) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, len(subscriptions))

        subscription_message = 'کانفیگ های شما:\n\n'
        for idx in range(start_idx, end_idx):
            subscription = subscriptions[idx]
            _, traffics = calculate_traffic_up_and_down(subscription.id)
            if traffics:
                remain = "{:.4f}".format(
                    max(subscription.gigabytes - (traffics[1] + traffics[0]), 0))
                traffics = tuple("{:.4f}".format(num) for num in traffics)
                subscription_message += f"لینک: {bot_domain}/{subscription.link}\n ترافیک خریداری شده: {subscription.gigabytes}\nمیزان دانلود: {traffics[1]}\n میزان آپلود: {traffics[0]}\n ترافیک باقی مانده: {remain}\n وضعیت: {'فعال' if subscription.is_active else 'غیر فعال'} \n\n"
            else:
                subscription_message += f"لینک: {bot_domain}/{subscription.link}\n ترافیک خریداری شده: {subscription.gigabytes}\n وضعیت: {'فعال' if subscription.is_active else 'غیر فعال'} \n\n"


        # Send pagination buttons
        if total_pages > 1:
            pagination_keyboard = types.InlineKeyboardMarkup()
            if page > 1:
                pagination_keyboard.add(types.InlineKeyboardButton(text='صفحه قبل',
                                                                            callback_data=f'subscription_page_{page - 1}'))
            if page < total_pages:
                pagination_keyboard.add(types.InlineKeyboardButton(text='صفحه بعد',
                                                                            callback_data=f'subscription_page_{page + 1}'))
            bot.send_message(user_id, subscription_message, reply_markup=pagination_keyboard)
        else:
            bot.send_message(user_id, subscription_message, reply_markup=menu())

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()
        cancel_ongoing_conversation(user_id)



def handle_list_subscriptions(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'list_subscriptions':
        return

    subscription_link = message.text.strip()
    parsed_link = urlparse(subscription_link)
    subscription_link = parsed_link.path.lstrip('/').rstrip('/')  # Remove the leading '/'

    session = Session()
    subscription = None
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()
        # Check if the subscription belongs to the user
        subscription = session.query(Subscription).filter_by(
            link=subscription_link, user_id=user.id).first()
        if not subscription:
            bot.send_message(
                message.chat.id, 'این کانفیگ وجود ندارد.',
                reply_markup=menu())
            cancel_ongoing_conversation(user_id)
            return
        _, traffics = calculate_traffic_up_and_down(subscription.id)
        if traffics:
            remain = "{:.4f}".format(
                max(subscription.gigabytes - (traffics[1] + traffics[0]), 0))
            traffics = tuple("{:.4f}".format(num) for num in traffics)
            subscription_message = f"لینک: {bot_domain}/{subscription.link}\n ترافیک خریداری شده: {subscription.gigabytes}\nمیزان دانلود: {traffics[1]}\n میزان آپلود: {traffics[0]}\n ترافیک باقی مانده: {remain}\n وضعیت: {'فعال' if subscription.is_active else 'غیر فعال'} \n\n"
        else:
            subscription_message = f"لینک: {bot_domain}/{subscription.link}\n ترافیک خریداری شده: {subscription.gigabytes}\n وضعیت: {'فعال' if subscription.is_active else 'غیر فعال'} \n\n"

        bot.send_message(user_id, subscription_message,
                         reply_markup=menu())
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()
    cancel_ongoing_conversation(user_id)


def change_card_num_step1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'change_card_num':
        return
    global card_num

    card_num = message.text.strip()
    persist_runtime_settings(card_num=card_num)
    # send to admins
    bot.send_message(user_id, f'شماره کارت جدید: {card_num}',
                     reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def add_channel_step_1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_channel':
        return

    # Make sure the entered channel starts with "@"
    new_channel = message.text.strip()
    if not new_channel.startswith("@"):
        bot.send_message(
            user_id, 'نام کانال باید با "@" شروع شود.', reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    global channels
    channels.append(new_channel)
    persist_runtime_settings(channels=channels)

    bot.send_message(
        user_id, f'کانال جدید اضافه شد: {new_channel}', reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def remove_channel_step_1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'remove_channel':
        return

    # Make sure the entered channel starts with "@"
    remove_channel = message.text.strip()
    if not remove_channel.startswith("@"):
        bot.send_message(
            user_id, 'نام کانال باید با "@" شروع شود.', reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    global channels
    try:
        channels.remove(remove_channel)
        persist_runtime_settings(channels=channels)
        bot.send_message(
            user_id, f'کانال حذف شد: {remove_channel}', reply_markup=menu())
    except ValueError:
        bot.send_message(
            user_id, f'کانال مورد نظر در لیست موجود نیست: {remove_channel}', reply_markup=menu())
    finally:
        cancel_ongoing_conversation(user_id)


def process_add_subscription_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_subscription':
        return

    name = message.text.strip()
    if not name.isascii():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
    name = name.replace(' ', '_')
    name = name.replace('/', '_')
    name = quote(name)
    bot.send_message(
        message.chat.id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید: ',
        reply_markup=menu())
    bot.register_next_step_handler(
        message, process_add_subscription_step2, name)


def process_add_subscription_step2(message, name):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_subscription':
        return

    gigabytes = message.text.strip()

    if not gigabytes.isdigit() or int(gigabytes) < 1:
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    result = create_subscription(user_id, int(gigabytes), name)

    if isinstance(result, tuple):
        link, sub_id = result
        bot.send_message(
            message.chat.id, f'کانفیگ با موفقیت ساخته شد\nلینک: {bot_domain}/{link}\nمحدودیت (گیگابایت) : {gigabytes}\nمیزان دانلود : 0\n میزان آپلود : 0\n وضعیت : فعال',
            reply_markup=menu())
        back_to_menu(user_id)
    else:
        bot.send_message(message.chat.id, result)
    cancel_ongoing_conversation(user_id)


def process_make_group_subscription_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'make_group_subscription':
        return

    count = message.text.strip()

    if not count.isdigit() or int(count) < 1:
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    bot.send_message(
        message.chat.id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید: ',
        reply_markup=menu())
    bot.register_next_step_handler(
        message, process_make_group_subscription_step2, int(count))


def process_make_group_subscription_step2(message, count):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'make_group_subscription':
        return

    gigabytes = message.text.strip()

    if not gigabytes.isdigit() or int(gigabytes) < 1:
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    bot.send_message(
        message.chat.id, 'نام کافیگ های خود را انتخاب کنید: ',
        reply_markup=menu())
    bot.register_next_step_handler(
        message, process_make_group_subscription_step3, int(count), int(gigabytes))


def process_make_group_subscription_step3(message, count, gigabytes):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'make_group_subscription':
        return

    main_name = message.text.strip()
    if not main_name.isascii():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    main_name = main_name.replace(' ', '_')
    for i in range(count):
        name = f"{main_name}_{i+1}"
        result = create_subscription(user_id, int(gigabytes), name)

        if isinstance(result, tuple):
            link, sub_id = result
            bot.send_message(
                message.chat.id, f'کانفیگ {name} با موفقیت ساخته شد\nلینک: {bot_domain}/{link}\nمحدودیت (گیگابایت) : {gigabytes}\nمیزان دانلود : 0\n میزان آپلود : 0\n وضعیت : فعال',
                reply_markup=menu())
        else:
            bot.send_message(message.chat.id, result)
    back_to_menu(user_id)
    cancel_ongoing_conversation(user_id)


def process_extend_subscription_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'extend_subscription':
        return

    sub_link = message.text.strip()
    parsed_link = urlparse(sub_link)
    sub_link = parsed_link.path.lstrip('/').rstrip('/')  # Remove the leading '/'
    session = Session()
    try:
        # Query the Subscription table
        subscription = session.query(
            Subscription).filter_by(link=sub_link).first()
        if not subscription:
            bot.send_message(
                message.chat.id, 'کانفیگ وجود ندارد. ',
                reply_markup=menu())
            cancel_ongoing_conversation(user_id)
            return
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()
    bot.send_message(
        message.chat.id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید: ',
        reply_markup=menu())
    bot.register_next_step_handler(
        message, process_extend_subscription_step2, sub_link)


def process_extend_subscription_step2(message, sub_link):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'extend_subscription':
        return

    gigabytes = message.text.strip()
    if not gigabytes.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    result = add_gigabytes_to_subscription(user_id, int(gigabytes), sub_link)

    if result is True:
        bot.send_message(
            message.chat.id, 'کانفیگ مورد نظر با موفقیت تمدید شد. ',
            reply_markup=menu())
    else:
        bot.send_message(message.chat.id, result)
    cancel_ongoing_conversation(user_id)


def process_delete_subscription_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'delete_subscription':
        return

    subscription_link = message.text.strip()
    parsed_link = urlparse(subscription_link)
    subscription_link = parsed_link.path.lstrip('/').rstrip('/')  # Remove the leading '/'

    session = Session()
    subscription_id = None
    try:
        if not user_id in ADMIN_CHAT_IDS:
            user = session.query(User).filter_by(tg_id=user_id).first()
            # Check if the subscription belongs to the user
            subscription = session.query(Subscription).filter_by(
                link=subscription_link, user_id=user.id).first()
        else:
            # Check if the subscription belongs to the user
            subscription = session.query(Subscription).filter_by(
                link=subscription_link).first()
        if not subscription:
            bot.send_message(
                message.chat.id, 'این کانفیگ وجود ندارد.',
                reply_markup=menu())
            cancel_ongoing_conversation(user_id)
            return
        subscription_id = subscription.id
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()
    if subscription_id is None:
        bot.send_message(
            message.chat.id, 'این کانفیگ وجود ندارد.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    delete_message = delete_subscription(subscription_id)
    bot.send_message(message.chat.id, delete_message)
    cancel_ongoing_conversation(user_id)


def process_transfer_gigabytes_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'transfer_gigabytes':
        return

    destination_user_id = message.text.strip()
    if not destination_user_id.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    bot.send_message(
        message.chat.id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید')
    bot.register_next_step_handler(
        message, process_transfer_gigabytes_step2, int(destination_user_id))


def process_transfer_gigabytes_step2(message, destination_user_id):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'transfer_gigabytes':
        return

    gigabytes = message.text.strip()
    if not gigabytes.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    result = transfer_gigabytes_to_user(
        user_id, int(gigabytes), destination_user_id)

    if result is True:
        bot.send_message(
            message.chat.id, 'مقدار گیگابایت مورد نظر با موفقیت انتقال پیدا کرد.',
            reply_markup=menu())
        bot.send_message(
            destination_user_id, f'موجودی شما به مقدار {gigabytes} گیگابایت توسط کاربری با ایدی {user_id} شارژ شد.')
    else:
        bot.send_message(message.chat.id, result)
    cancel_ongoing_conversation(user_id)


def process_charge_balance_step1(message):
    user_id = message.from_user.id
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'charge_balance':
        return

    gigabytes = message.text.strip()
    if not gigabytes.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    gigabytes = int(gigabytes)

    price = calculate_price_for_gigabytes(gigabytes)
    if price <= 0:
        bot.send_message(message.chat.id, 'برای این حجم، قیمت تعریف نشده است.', reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    bot.send_message(
        message.chat.id, f'قیمت {gigabytes} گیگابایت {price} تومان است.\n همین قیمت را به شماره کارت {card_num} انتقال دهید و عکس رسید یا شماره پیگیری آن را ارسال کنید.')
    bot.send_message(
        message.chat.id, 'لطفاً در هنگام خرید به این نکته دقت داشته باشید که بدون زدن دکمه اضافه رسید رو ارسال کنید سپس از ربات استفاده کنید در غیر این صورت تراکنش شما تایید نخواهد شد و باید از طرق پشتیبانی اقدام به پیگیری نمایید')
    bot.register_next_step_handler(
        message, process_charge_balance_step2, int(gigabytes), price)


def process_charge_balance_step2(message, gigabytes, price):
    user_id = message.from_user.id
    if message.content_type == 'text' and message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        bot.send_message(
            user_id, 'رسید شما ارسال نگردید تراکنش شما ثبت نشده است در صورت واریز مبلغ روند خرید حجم را دوباره با همان میزان حجم پیش ببرید و رسید تراکنشی که انجام دادید را ارسال کنید و منتظر تایید تراکنش باشید و یا رسید خود را به پشتیبانی ارسال کنید و از این روش پرداخت خود را تایید کنید')
        return
    elif conversation_state[user_id] != 'charge_balance':
        bot.send_message(
            user_id, 'رسید شما ارسال نگردید تراکنش شما ثبت نشده است در صورت واریز مبلغ روند خرید حجم را دوباره با همان میزان حجم پیش ببرید و رسید تراکنشی که انجام دادید را ارسال کنید و منتظر تایید تراکنش باشید و یا رسید خود را به پشتیبانی ارسال کنید و از این روش پرداخت خود را تایید کنید')
        return

    admin_message = f"پرداخت جدیدی انجام شد:\nایدی عددی کاربر: {user_id}\nمقدار گیگابایت: {gigabytes}\nقیمت: {price} تومان"
    global channel_chat_id

    # Forwarding the message to the channel
    forwarded_message = bot.forward_message(
        channel_chat_id, message.chat.id, message.message_id)

    # Constructing the link to the forwarded message
    link = f"https://t.me/c/1917306992/{forwarded_message.message_id}"
    # Send the admin message to the admin (replace ADMIN_CHAT_ID with the actual admin chat ID)
    # send to admis in list
    for admin in ADMIN_CHAT_IDS:
        bot.send_message(admin, admin_message)
    bot.send_message(message.chat.id, "پرداخت شما به ادمین ارسال شد. بعد از تایید پرداخت شما توسط ادمین موجودی حساب شما افزایش پیدا خواهد کرد. ",
                     reply_markup=menu())
    # Create a waitlist entry
    waitlist_entry = Waitlist(
        user_id=user_id,
        price=price,
        gigabytes=gigabytes,
        message=link,
        status=PAYMENT_STATUS_PENDING,
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    session = Session()
    try:
        session.add(waitlist_entry)
        session.commit()
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()
    cancel_ongoing_conversation(user_id)


def back_to_menu(user_id):
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()

        if not user:
            bot.send_message(user_id, 'کاربر پیدا نشد.',
                             reply_markup=menu())
            return

        conversation_state[user_id] = None
        invite_link = f"https://t.me/{bot.get_me().username}?start={user.tg_id}"

        # Create an inline keyboard with options
        keyboard = types.InlineKeyboardMarkup()
        add_subscription_btn = types.InlineKeyboardButton(
            text='ساخت اکانت 📥', callback_data='add_subscription')
        make_group_subscription_btn = types.InlineKeyboardButton(
            text='ساخت اکانت گروهی 📥', callback_data='make_group_subscription')
        extend_subscription_btn = types.InlineKeyboardButton(
            text='تمدید اکانت ➕️', callback_data='extend_subscription')
        transfer_gigabytes_btn = types.InlineKeyboardButton(
            text='انتقال اعتبار ⬅️', callback_data='transfer_gigabytes')
        charge_balance_btn = types.InlineKeyboardButton(
            text='افزایش موجودی 💳🛒', callback_data='charge_balance')
        check_price_of_ranges_btn = types.InlineKeyboardButton(
            text='مشاهده قیمت ها 💰', callback_data='check_price_of_ranges')
        list_subscriptions_btn = types.InlineKeyboardButton(
            text='ارسال آمار اکانت شما با لینک 📊', callback_data='list_subscriptions')
        list_all_subscriptions_btn = types.InlineKeyboardButton(
            text='همه ی اکانت های شما 🖇', callback_data='subscription_page_1')
        delete_subscription_btn = types.InlineKeyboardButton(
            text='حذف اکانت ❌️', callback_data='delete_subscription')
        set_web_password_btn = types.InlineKeyboardButton(
            text='تنظیم پسورد وب', callback_data='set_web_password')
        global support_link
        support_btn = types.InlineKeyboardButton(
            text="ارتباط با پشتیبانی 🧑🏻‍💻", url=f"{support_link}")
        keyboard.row(add_subscription_btn)
        keyboard.row(make_group_subscription_btn)
        keyboard.row(extend_subscription_btn)
        keyboard.row(transfer_gigabytes_btn)
        keyboard.row(charge_balance_btn)
        keyboard.row(check_price_of_ranges_btn)
        keyboard.row(list_subscriptions_btn)
        keyboard.row(list_all_subscriptions_btn)
        keyboard.row(delete_subscription_btn)
        keyboard.row(set_web_password_btn)
        keyboard.row(support_btn)
        invited_users = session.query(User).filter_by(inviter_id=user.id).all()
        if invited_users:
            invited_users_btn = types.InlineKeyboardButton(
                text='لیست افراد دعوت شده 📊', callback_data='show_invited_users_1')
            keyboard.row(invited_users_btn)
        # Add the admin panel button only for the admin user
        if user_id in ADMIN_CHAT_IDS:
            admin_panel_btn = types.InlineKeyboardButton(
                text='پنل ادمین 🧑🏻‍💻🛠', callback_data='admin_panel')
            keyboard.row(admin_panel_btn)
        global referral_percent
        bot.send_message(
            user_id,
            text=f'ایدی شما: {user.tg_id}\nموجودی شما: {user.balance}\n لینک دعوت: {invite_link}\n با دعوت هر نفر ب ازای خرید اون شخص مادام العمر {referral_percent} درصد از حجم خرید اون شخص گیگ رایگان روی اکانت شما شارژ میشود💰😍',
            reply_markup=keyboard
        )
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()
        cancel_ongoing_conversation(user_id)


def menu():
    keyboard = types.InlineKeyboardMarkup()
    back_to_menu_btn = types.InlineKeyboardButton(
        text='منوی اصلی 🏠', callback_data='back_to_menu')
    keyboard.row(back_to_menu_btn)

    return keyboard


def track_purchase(user_id, gigabytes):
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()
        if user is None:
            return
        if user.inviter_id:
            if user.purchases < referral_rate:
                invitor_user = session.query(User).filter_by(
                    id=user.inviter_id).first()
                # Calculate the referral bonus based on the purchase gigabytes
                bonus = min(int(referral_percent * gigabytes / 100),
                            int(referral_rate - user.purchases))
                user.purchases += bonus
                # Update the user balances
                invitor_user.balance += bonus
                session.commit()
                add_to_balance(invitor_user.tg_id, bonus)
                bot.send_message(
                    invitor_user.tg_id, f"شما {bonus} گیگابایت به عنوان معرفی کاربر به ایدی {user_id} دریافت کردید.")
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer

    finally:
        session.close()


def update_client_by_id(base_url, session, client_id, client_data):
    headers = {'Content-Type': 'application/json'}
    response = session.post(f'{base_url}/panel/api/inbounds/updateClient/{client_id}',
                            headers=headers, data=json.dumps(client_data))
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True, payload.get('msg') if isinstance(payload, dict) else None
    else:
        return False, payload


def extend_subscriptions(subscription_id, gigabytes):
    # Start a new session
    session = Session()
    try:
        # Get all subscriptions
        subscription = session.query(Subscription).filter_by(
            id=subscription_id).first()
        if subscription.is_active:
            return True
        # Get the sum of traffic for this subscription
        success, traffic_sum = calculate_traffic(subscription.id)

        if success and traffic_sum < subscription.gigabytes + gigabytes:
            for config in subscription.configs:
                server = session.query(Server).filter_by(
                    id=config.server_id).first()
                server_domain, username, password = server.domain, server.username, server.password
                success, login_session = authenticate(
                    server_domain, username, password)
                if success:
                    client_data = {
                        'id': server.inbound_id,
                        'settings': json.dumps({
                            'clients': [build_3xui_client(
                                client_uuid=config.client_uuid,
                                client_email=config.client_email,
                                is_active=True
                            )]
                        })
                    }
                    success, _ = update_client_by_id(
                        server_domain, login_session, config.client_uuid, client_data)
                    if not success:
                        return False
        subscription.is_active = True
        session.commit()
        return True
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        # Close the session
        session.close()

def save_dict_to_file(data):
    FILE_PATH = BOT_RUNTIME_DIR / 'server.json'
    TEMP_PATH = BOT_RUNTIME_DIR / 'server_temp.json'
    LOCK_PATH = BOT_RUNTIME_DIR / 'server.lock'
    LOCK_TIMEOUT = 5  # seconds
    with FileLock(LOCK_PATH, timeout=LOCK_TIMEOUT):
        # Write to a temporary file first
        with open(TEMP_PATH, 'w', encoding='utf-8') as temp_file:
            json.dump(data, temp_file)
        # Atomic replace works on Windows and Linux even when the target exists.
        os.replace(TEMP_PATH, FILE_PATH)

def read_dict_from_file():
    FILE_PATH = BOT_RUNTIME_DIR / 'server.json'
    LOCK_PATH = BOT_RUNTIME_DIR / 'server.lock'
    LOCK_TIMEOUT = 5  # seconds
    try:
        with FileLock(LOCK_PATH, timeout=LOCK_TIMEOUT):
            with open(FILE_PATH, 'r', encoding='utf-8') as file:
                return json.load(file)
    except Timeout:
        # If the file is locked for more than the timeout duration, 
        # you can choose to return a cached version or raise an error.
        # For this example, we'll raise an error.
        raise Exception("Unable to read file due to ongoing write operation.")


# def save_dict_to_file(data):
#     with open('/var/bot/server.json', 'w') as file:
#         json.dump(data, file)


# def read_dict_from_file():
#     with open('/var/bot/server.json', 'r') as file:
#         data = json.load(file)
#     return data


def check_subscriptions():
    # Start a new session
    session = Session()
    checked_count = 0
    disabled_count = 0
    try:
        if not read_boolean_variable():
            write_subscription_monitor_status("skipped", checked_count, disabled_count, "sales disabled")
            return
        server_details = get_servers_info()
        if not server_details:
            write_subscription_monitor_status("skipped", checked_count, disabled_count, "no servers")
            return
        save_dict_to_file(server_details)
        # Get all subscriptions
        subscriptions = session.query(Subscription).all()
        for subscription in subscriptions:
            checked_count += 1
            # Get the sum of traffic for this subscription
            success, traffic_sum = calculate_traffic(subscription.id)
            if not success:
                continue
            flag = True
            if traffic_sum and traffic_sum >= subscription.gigabytes:
                if not subscription.is_active:
                    continue
                subscription.is_active = False
                disabled_count += 1
                # If the traffic exceeds the subscription's gigabytes, disable the config
                for config in subscription.configs:
                    server = session.query(Server).filter_by(
                        id=config.server_id).first()
                    server_domain, username, password = server.domain, server.username, server.password
                    success, login_session = authenticate(
                        server_domain, username, password)
                    if success:
                        client_data = {
                            'id': server.inbound_id,
                            'settings': json.dumps({
                                'clients': [build_3xui_client(
                                    client_uuid=config.client_uuid,
                                    client_email=config.client_email,
                                    is_active=False
                                )]
                            })
                        }
                        success, _ = update_client_by_id(
                            server_domain, login_session, config.client_uuid, client_data)
                        if not success:
                            flag = False
            else:
                subscription.is_active = True
            if not flag:
                subscription.is_active = True
            session.commit()
        write_subscription_monitor_status("ok", checked_count, disabled_count, "")
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)
        write_subscription_monitor_status("error", checked_count, disabled_count, str(e))

        # Send the error message along with the traceback to the programmer

    finally:
        # Close the session
        session.close()


def write_subscription_monitor_status(status, checked_count=0, disabled_count=0, error=""):
    payload = {
        "status": status,
        "checked_count": int(checked_count or 0),
        "disabled_count": int(disabled_count or 0),
        "error": str(error or "")[:500],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        SUBSCRIPTION_MONITOR_STATUS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logging.error(traceback.format_exc())


def save_user_stats(user_id, stats):
    # Get the current month and year
    current_month = datetime.now().strftime('%B')
    current_year = datetime.now().strftime('%Y')

    # Create the filename based on the current month and year
    filename = f'/var/bot/stats/user_stats_{current_month}_{current_year}.csv'

    # Check if the file exists
    if not os.path.exists(filename):
        # If the file does not exist, create it with the headers
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(
                ['user_id', 'configs', 'balance', 'recieved_balance'])

    # Read the existing data
    with open(filename, 'r', newline='') as file:
        reader = csv.reader(file)
        data = list(reader)

    # Find the row for the user and update it
    for row in data:
        if row[0] == str(user_id):
            row[1:] = stats
            break
    else:
        session = Session()
        try:
            # Fetch the users from the database
            user = session.query(User).filter_by(
                tg_id=user_id).first()

            # Check if the users exist
            if user:
                data.append(
                    [user_id, stats[0], user.balance, stats[2]])
        except Exception as e:
            # send the exception to the support chat
            # Get the traceback information
            error_message = traceback.format_exc()

            # Log the error to a file
            logging.error(error_message)

            # Send the error message along with the traceback to the programmer
            session.rollback()

        finally:
            session.close()
        # If the user doesn't have a row yet, add one

    # Write the updated data back to the file
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(data)


def add_to_configs(user_id, number):
    # Read the user's current stats
    stats = get_user_stats(user_id)
    # Add the number to the configs
    stats[0] += number
    # Save the updated stats
    save_user_stats(user_id, stats)


def add_to_balance(user_id, number):
    # Read the user's current stats
    stats = get_user_stats(user_id)
    # Add the number to the balance and received balance
    stats[1] += number
    stats[2] += number
    # Save the updated stats
    save_user_stats(user_id, stats)


def subtract_from_balance(user_id, number):
    # Read the user's current stats
    stats = get_user_stats(user_id)
    # Subtract the number from the balance
    stats[1] -= number
    # Save the updated stats
    save_user_stats(user_id, stats)


def get_user_stats(user_id):
    # Get the current month and year
    current_month = datetime.now().strftime('%B')
    current_year = datetime.now().strftime('%Y')

    directory = '/var/bot/stats/'
    os.makedirs(directory, exist_ok=True)

    # Create the filename based on the current month and year
    filename = f'{directory}user_stats_{current_month}_{current_year}.csv'

    # Check if the file not exists
    if not os.path.exists(filename):
        # If the file does not exist, create it with the headers
        with open(filename, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(
                ['user_id', 'configs', 'balance', 'recieved_balance'])

    # Read the existing data
    with open(filename, 'r', newline='') as file:
        reader = csv.reader(file)
        data = list(reader)

    # Find the row for the user
    for row in data:
        if row[0] == str(user_id):
            # Convert the stats to integers and return them
            return list(map(int, row[1:]))

    # If the user doesn't have a row yet, return default stats
    return [0, 0, 0]


def send_stats_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'send_stats':
        return
    inputed_user_id = message.text.strip()
    if not inputed_user_id.isdigit():
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    inputed_user_id = int(inputed_user_id)
    session = Session()
    try:
        # Fetch the users from the database
        user = session.query(User).filter_by(
            tg_id=inputed_user_id).first()

        # Check if the users exist
        if not user:
            bot.send_message(user_id, "کاربر پیدا نشد")
            cancel_ongoing_conversation(user_id)
            return
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()

    stats = get_available_stats()

    # Sort the stats based on year and month
    stats.sort(key=lambda x: (x[1], datetime.strptime(x[0], '%B').month))

    output = "\n".join([f"{i+1}. {month} {year}" for i,
                       (month, year) in enumerate(stats)])

    bot.send_message(
        message.chat.id, 'شماره ماه را وارد کنید:\n' + output)
    bot.register_next_step_handler(
        message, send_stats_step_2, inputed_user_id, stats)


def send_stats_step_2(message, inputed_user_id, stats):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'send_stats':
        return

    index = message.text.strip()
    if not index.isdigit() or int(index) > len(stats):
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    index = int(index)
    # This function should retrieve the stats for the user
    stats = get_user_stats_for_month(
        inputed_user_id, stats[index-1][0], stats[index-1][1])
    if stats is None:
        bot.send_message(
            user_id, f'هیج آماری برای {inputed_user_id} و این ماه و سال وجود ندارد')
    else:
        bot.send_message(
            user_id, f'آمار کابر با ایدی عددی {inputed_user_id}:\n تعداد کانفیگ ها: {stats[0]} \n موجودی کل: {stats[1]}\n موجودی دریافتی: {stats[2]}')
    cancel_ongoing_conversation(user_id)


def change_balance_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'change_balance':
        return
    inputed_user_id = message.text.strip()
    if not inputed_user_id.isdigit():
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    inputed_user_id = int(inputed_user_id)
    session = Session()
    try:
        # Fetch the users from the database
        user = session.query(User).filter_by(
            tg_id=inputed_user_id).first()

        # Check if the users exist
        if not user:
            bot.send_message(user_id, "کاربر پیدا نشد")
            cancel_ongoing_conversation(user_id)
            return
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()
    # Call the add_gigabytes_to_user function to perform the balance
    bot.send_message(
        message.chat.id, 'مقدار موجودی جدید را وارد کنید:')
    bot.register_next_step_handler(
        message, change_balance_step_2, inputed_user_id)

def change_balance_step_2(message, inputed_user_id):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'change_balance':
        return
    balance = message.text.strip()
    if not balance.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    balance = int(balance)
    previous_balance = None
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=inputed_user_id).first()
        previous_balance = user.balance
        user.balance = balance
        session.commit()
        bot.send_message(
            message.chat.id, 'با موفقیت انجام شد',
            reply_markup=menu())
        add_to_balance(inputed_user_id, balance - previous_balance)
        cancel_ongoing_conversation(user_id)
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()
    
    cancel_ongoing_conversation(user_id)


def add_to_balance_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_to_balance':
        return
    gigabytes = message.text.strip()
    if not gigabytes.isdigit():
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    gigabytes = int(gigabytes)

    # Call the add_gigabytes_to_user function to perform the balance
    result = add_gigabytes_to_user(gigabytes, user_id)

    if result is True:
        bot.send_message(user_id, 'با موفقیت انجام شد',
                         reply_markup=menu())
    else:
        bot.send_message(user_id, result)
    cancel_ongoing_conversation(user_id)


def create_backup(base_url, session):
    for method, endpoint in (
        ('post', '/panel/api/backuptotgbot'),
        ('get', '/panel/api/inbounds/createbackup'),
    ):
        request_method = getattr(session, method)
        response = request_method(f"{base_url}{endpoint}")
        success, _ = parse_3xui_response(response, assume_success_on_empty=True)
        if success:
            return True
    return False


def get_available_stats():
    directory = '/var/bot/stats/'
    files = os.listdir(directory)

    available_stats = []

    for file in files:
        # Use a regular expression to match the filename pattern
        match = re.match(r'user_stats_(\w+)_(\d+).csv', file)
        if match:
            month, year = match.groups()
            available_stats.append((month, year))

    return available_stats


def get_user_stats_for_month(user_id, month, year):
    directory = '/var/bot/stats/'
    filename = f'{directory}user_stats_{month}_{year}.csv'

    # Check if the file exists
    if not os.path.exists(filename):
        return None

    # Read the existing data
    with open(filename, 'r', newline='') as file:
        reader = csv.reader(file)
        data = list(reader)

    # Find the row for the user
    for row in data:
        if row[0] == str(user_id):
            # Convert the stats to integers and return them
            return list(map(int, row[1:]))

    # If the user doesn't have a row yet, return default stats
    return [0, 0, 0]


def check_user_subscription(user_id, channel_username):
    try:
        status = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        # If the user is in the chat, the status will be 'member', 'creator' or 'administrator'
        return status.status in ['member', 'creator', 'administrator']
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return False  # if there was an error, assume the user is not in the chat


def check_channels(user_id):
    refresh_runtime_settings()

    flag = True
    list_of_channels = []
    global channels
    for channel in channels:
        if not check_user_subscription(user_id, channel):
            list_of_channels.append(channel)
            flag = False
    if not flag:
        channels_string = "\n".join(
            [f"{i+1}. {channel}" for i, channel in enumerate(list_of_channels)])
        bot.send_message(
            user_id, f"شما باید عضو این کانال ها شوید:\n{channels_string}\nبعد از آن /start را بزنید.")
    return flag


def show_all_channels(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    if len(channels) == 0:
        bot.send_message(user_id, 'هیچ کانالی ثبت نشده است.')
        return
    else:
        message = 'کانال ها:'
        for i, channel in enumerate(channels):
            message += f'\n{i+1}. {channel}'
    bot.send_message(user_id, message)


def change_support_link_step1(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            message.chat.id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'change_support_link':
        return
    global support_link

    support_link = 'https://t.me/' + message.text.strip()
    persist_runtime_settings(support_link=support_link)

    # send to admins
    bot.send_message(user_id, f'لینک پشتیبانی جدید: {support_link}',
                     reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def handle_change_servers(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    keyboard = types.InlineKeyboardMarkup()

    replace_server_btn = types.InlineKeyboardButton(
        text='جاگزین کردن سرور',
        callback_data='replace_server')

    add_server_btn = types.InlineKeyboardButton(
        text='اضافه کردن سرور',
        callback_data='add_server')

    delete_server_btn = types.InlineKeyboardButton(
        text='حذف کردن سرور',
        callback_data='delete_server')

    show_all_servers_btn = types.InlineKeyboardButton(
        text='نمایش همه سرورها',
        callback_data='show_all_servers')

    keyboard.row(replace_server_btn)
    keyboard.row(add_server_btn)
    keyboard.row(delete_server_btn)
    keyboard.row(show_all_servers_btn)
    back_to_menu_btn = types.InlineKeyboardButton(
        text='منوی اصلی 🏠', callback_data='back_to_menu')
    keyboard.row(back_to_menu_btn)

    bot.send_message(
        user_id, 'لطفاً یکی از گزینه های زیر را انتخاب کنید.', reply_markup=keyboard)


def show_all_servers(user_id):
    if user_id not in ADMIN_CHAT_IDS:
        return
    session = Session()
    try:
        servers = session.query(Server).all()
        if len(servers) == 0:
            bot.send_message(user_id, 'هیچ سروری ثبت نشده است.')
            return
        else:
            message = 'سرورها:'
            for server in servers:
                if server.sni == '-1':
                    message += f'\n{server.id}. {server.domain}\n یوزرنیم: {server.username}\n پسورد: {server.password}\n {"vless" if server.is_vless else "vmess"}\n کشور: {server.country}\n {"tcp" if server.is_tcp else "ws"} \n port: {server.port} \n inbond id: {server.inbound_id}\n'
                else:
                    message += f'\n{server.id}. {server.domain}\n یوزرنیم: {server.username}\n پسورد: {server.password}\n {"vless" if server.is_vless else "vmess"}\n کشور: {server.country}\n {"tcp" if server.is_tcp else "ws"} \n port: {server.port} \n inbond id: {server.inbound_id} \nsni: {server.sni}\n public key: {server.pub_key}\n private key: {server.private_key}\n domain name: {server.domain_name}\n'
        bot.send_message(user_id, message)
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()


def replace_server_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'replace_server':
        return

    # parse the server info from the message
    try:
        server_info = message.text.strip().split(' ')
        if len(server_info) != 7:
            raise ValueError
        server_url, username, password, country, vless, tcp, port = server_info
        port = int(port)
        vless = vless.lower() == 'vless'
        tcp = tcp.lower() == 'tcp'
    except ValueError:
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    server_info = (server_url, username, password, country, vless, tcp, port)

    bot.send_message(
        message.chat.id, 'SNI domain_name public_key private_key(-1 for skip):\n')
    bot.register_next_step_handler(
        message, replace_server_step_2, server_info)


def replace_server_step_2(message, server_info):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'replace_server':
        return

    if message.text.strip() == '-1':
        server_info += ('-1', '-1', '-1', '-1')

    # parse the server info from the message
    else:
        try:
            server_info_2 = message.text.strip().split(' ')
            if len(server_info_2) != 4:
                raise ValueError
            SNI, domain_name, public_key, private_key = server_info_2
            server_info += (SNI, domain_name, public_key, private_key)
        except ValueError:
            bot.send_message(
                user_id, 'پیام شما صحیح نیست. ',
                reply_markup=menu())
            cancel_ongoing_conversation(user_id)
            return

    show_all_servers(user_id)

    bot.send_message(
        message.chat.id, 'شماره سروری که میخواهید جایگزین کنید را وارد کنید.:\n')
    bot.register_next_step_handler(
        message, replace_server_step_3, server_info)


def replace_server_step_3(message, server_info):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'replace_server':
        return

    index = message.text.strip()
    if not index.isdigit():
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    session = Session()
    try:
        index = int(index)
        server = session.query(Server).filter_by(id=index).first()
        if not server:
            bot.send_message(user_id, "سرور پیدا نشد")
            return
        domain, username, password, country, vless, tcp, port, sni, domain_name, public_key, private_key = server_info
        newdata = {
            'domain': domain,
            'username': username,
            'password': password,
            'country': country,
            'is_vless': vless,
            'is_tcp': tcp,
            'sni': sni,
            'domain_name': domain_name,
            'public_key': public_key,
            'private_key': private_key,
            'port': port,  # The port will be updated later after adding the new inbound
        }
        success, message = replace_server(server.id, newdata)
        if success:
            bot.send_message(user_id, message)
        else:
            bot.send_message(user_id, f"{message}")

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()
        cancel_ongoing_conversation(user_id)


def delete_server_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'delete_server':
        return

    index = message.text.strip()
    if not index.isdigit():
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    session = Session()
    try:
        index = int(index)
        server = session.query(Server).filter_by(id=index).first()
        if not server:
            bot.send_message(user_id, "سرور پیدا نشد")
            return
        success, message = delete_server(server.id)
        if success:
            bot.send_message(user_id, message)
        else:
            bot.send_message(user_id, f"{message}")

    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()
        cancel_ongoing_conversation(user_id)


def add_server_step_1(message):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_server':
        return

    # parse the server info from the message
    try:
        server_info = message.text.strip().split(' ')
        if len(server_info) != 7:
            raise ValueError
        server_url, username, password, country, vless, tcp, port = server_info
        port = int(port)
        vless = vless.lower() == 'vless'
        tcp = tcp.lower() == 'tcp'
    except ValueError:
        bot.send_message(
            user_id, 'پیام شما صحیح نیست. ',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return

    server_info = (server_url, username, password, country, vless, tcp, port)

    bot.send_message(
        message.chat.id, 'SNI domain_name public_key private_key(-1 for skip):\n')
    bot.register_next_step_handler(
        message, add_server_step_2, server_info)


def add_server_step_2(message, server_info):
    user_id = message.from_user.id
    if not user_id in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(
            user_id, 'پیام شما صحیح نیست.',
            reply_markup=menu())
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        # Cancel ongoing conversation and reset state to None
        cancel_ongoing_conversation(user_id)
        return
    elif conversation_state[user_id] != 'add_server':
        return

    domain, username, password, country, vless, tcp, port = server_info
    session = Session()
    if message.text.strip() == '-1':
        sni, domain_name, public_key, private_key = "-1", "-1", "-1", "-1"

    # parse the server info from the message
    else:
        try:
            server_info_2 = message.text.strip().split(' ')
            if len(server_info_2) != 4:
                raise ValueError
            sni, domain_name, public_key, private_key = server_info_2
        except ValueError:
            bot.send_message(
                user_id, 'پیام شما صحیح نیست. ',
                reply_markup=menu())
            session.close()
            cancel_ongoing_conversation(user_id)
            return

    try:
        server = Server(domain=domain, username=username, password=password, country=country, is_vless=vless,
                        port=port, sni=sni, domain_name=domain_name, pub_key=public_key, private_key=private_key, is_tcp=tcp)
        session.add(server)
        session.commit()
        success, m = add_server(server.id)
        if not success:
            session.rollback()
            bot.send_message(user_id, m)
            return
        bot.send_message(user_id, f'با موفقیت اضافه شد')
    except Exception as e:
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        session.rollback()
    finally:
        session.close()
        cancel_ongoing_conversation(user_id)


def add_server(server_id):
    session = Session()
    try:
        server = session.query(Server).get(server_id)
        if not server:
            return False, "سرور پیدا نشد"

        # Get all existing subscriptions
        subscriptions = session.query(Subscription).all()

        success, login_session = authenticate(
            server.domain, server.username, server.password)
        if success:
            success, inbound = add_inbound(
                server.domain, login_session, server.is_vless, server.port, server.is_tcp, server.sni, server.domain_name, server.pub_key, server.private_key)
            if success:
                server.inbound_id = inbound['id']
                session.commit()
                for subscription in subscriptions:
                    if success:
                        success, client = add_client_to_inbound(
                            server.domain, login_session, server.inbound_id, subscription.is_active)
                        if success:
                            _, inbound_info = get_inbound_by_id(server.domain, login_session, server.inbound_id)
                            link = generate_link_from_inbound(
                                server, inbound_info, client['client_uuid'], server.country + '_' + subscription.name)
                            config = Config(server_id=server.id,
                                            client_uuid=client['client_uuid'], client_email=client['client_email'], link=link, subscription=subscription)
                            session.add(config)
                            subscription.links += ', ' + link
                            session.commit()
                    else:
                        session.rollback()
                        return False, "خطا در ساخت کانفیگ"
                return True, "با موفقیت اضافه شد"
        return False, "خطا در اضافه کردن سرور"
    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
    finally:
        session.close()


def delete_inbound(base_url, session, inbound_id):
    response = session.post(f'{base_url}/panel/api/inbounds/del/{inbound_id}')
    success, payload = parse_3xui_response(response, assume_success_on_empty=True)
    if success:
        return True, None
    else:
        return False, payload


def replace_server(server_id, new_data):
    session = Session()
    try:
        server = session.query(Server).get(server_id)
        if not server:
            return False, "سرور پیدا نشد"

        # Get all existing subscriptions
        subscriptions = session.query(Subscription).all()

        # Authenticate with the new server data
        success, login_session = authenticate(
            new_data['domain'], new_data['username'], new_data['password'])
        if not success:
            return False, "خطا در احراز هویت با اطلاعات جدید سرور"

        # Add a new inbound for the updated server
        success, inbound = add_inbound(
            new_data['domain'], login_session, new_data['is_vless'], new_data['port'], new_data['is_tcp'], new_data['sni'], new_data['domain_name'], new_data['public_key'], new_data['private_key'])
        if not success:
            return False, "خطا در ایجاد inbound جدید"

        for subscription in subscriptions:
            # Update the existing configuration links
            config = session.query(Config).filter_by(
                server_id=server.id, subscription_id=subscription.id).first()

            if not config:
                session.rollback()
                return False, "کانفیگ پیدا نشد"
            success3, traffic = calculate_traffic_up_and_down_by_email(config.subscription_id, config.client_email)
            # Add a new client for each existing configuration

            success, client = add_client_to_inbound(
                new_data['domain'], login_session, inbound['id'], subscription.is_active)
            if not success:
                session.rollback()
                return False, "خطا در افزودن مشترک به inbound"

            # Generate the new link and update the subscription
            aux_server = Server(
                domain=new_data['domain'],
                port=inbound.get('port', new_data['port']),
                is_vless=new_data['is_vless'],
                sni=new_data['sni'],
                is_tcp=new_data['is_tcp']
            )
            link = generate_link_from_inbound(
                aux_server, inbound, client['client_uuid'], new_data['country'] + '_' + subscription.name)

            subscription.links = subscription.links.replace(config.link, link)
            config.link = link
            if success3 and traffic:
                config.up = traffic[0]
                config.down = traffic[1]
            config.client_uuid = client['client_uuid']
            config.client_email = client['client_email']
            session.commit()

        if read_boolean_variable():
            success2, login_session2 = authenticate(
                server.domain, server.username, server.password)
            # Delete the old inbound
            if success2:
                success, message = delete_inbound(
                    server.domain, login_session2, server.inbound_id)

        # Update server data with the new inbound details
        server.domain = new_data['domain']
        server.username = new_data['username']
        server.password = new_data['password']
        server.country = new_data['country']
        server.is_vless = new_data['is_vless']
        server.sni = new_data['sni']
        server.domain_name = new_data['domain_name']
        server.pub_key = new_data['public_key']
        server.private_key = new_data['private_key']
        server.is_tcp = new_data['is_tcp']
        server.port = inbound['port']
        server.inbound_id = inbound['id']
        session.commit()
        return True, "با موفقیت تغییر یافت"

    except Exception as e:
        session.rollback()
        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return False, "خطای سیستمی رخ داد"
    finally:
        session.close()


def delete_server(server_id):
    session = Session()
    try:
        server = session.query(Server).get(server_id)
        if not server:
            return False, "سرور پیدا نشد"

        # Get all existing subscriptions
        subscriptions = session.query(Subscription).all()


        for subscription in subscriptions:
            # Update the existing configuration links
            config = session.query(Config).filter_by(
                server_id=server.id, subscription_id=subscription.id).first()

            if not config:
                session.rollback()
                continue
            success, traffic = calculate_traffic_up_and_down_by_email(
                    subscription.id, config.client_email)
            if success:
                aux_config = session.query(Config).filter(
                        Config.subscription_id == subscription.id,
                        Config.server_id != server_id
                    ).first()
                aux_config.up += traffic[0]
                aux_config.down += traffic[1]
                session.commit()
            subscription.links = subscription.links.replace(
                config.link, '\n')
            session.delete(config)
            session.commit()

        # Delete the server along with its configs
        session.delete(server)

        # Commit the transaction
        session.commit()

        if read_boolean_variable():
            # Authenticate with the new server data
            success, login_session = authenticate(
                server.domain, server.username, server.password)
            if success:
                success, message = delete_inbound(
                    server.domain, login_session, server.inbound_id)

        return True, "با موفقیت حذف شد"

    except Exception as e:
        session.rollback()

        # send the exception to the support chat
        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return False, "خطای سیستمی رخ داد"
    
    finally:
        session.close()


def make_subscription(user_id, gigabytes, name):
    session = Session()

    try:
        user = session.query(User).filter_by(tg_id=user_id).first()

        subscription = Subscription(name=name, gigabytes=gigabytes, user=user)
        session.add(subscription)
        links = []
        created_clients = []
        servers = session.query(Server).all()
        for server in servers:
            success, login_session = authenticate(
                server.domain, server.username, server.password)
            if success:
                success, client = add_client_to_inbound(
                    server.domain, login_session, server.inbound_id, True)
                if success:
                    _, inbound_info = get_inbound_by_id(server.domain, login_session, server.inbound_id)
                    link = generate_link_from_inbound(
                        server, inbound_info, client['client_uuid'], server.country + '_' + name)
                    links.append(link)
                    config = Config(server_id=server.id,
                                    client_uuid=client['client_uuid'], client_email=client['client_email'], link=link, subscription=subscription)
                    session.add(config)
                    created_clients.append(
                        (server.domain, login_session, server.inbound_id, client['client_uuid']))

        not_created = len(servers) - len(created_clients)
        if not_created != 0:
            for server_domain, login_session, inbound_id, client_id in created_clients:
                delete_client_by_id(server_domain, login_session, inbound_id, client_id)
            session.rollback()
            return not_created, created_clients

        subscription.links = ', '.join(links)
        random_string = token_hex(8)
        subscription.link = f'{name}_{random_string}'
        user.balance -= gigabytes
        session.commit()
        subtract_from_balance(user_id, gigabytes)
        add_to_configs(user_id, 1)
        return subscription.link, subscription.id

    except Exception as e:
        session.rollback()

        # Get the traceback information
        error_message = traceback.format_exc()

        # Log the error to a file
        logging.error(error_message)

        # Send the error message along with the traceback to the programmer
        return None, None
    finally:
        session.close()


# Function to read the boolean variable from the config file
def read_boolean_variable():
    try:
        with open("config.json", "r") as file:
            config = json.load(file)
            return config.get("status", False)
    except FileNotFoundError:
        return False

# Function to update the boolean variable and save it to the config file
def update_boolean_variable(new_value):
    try:
        with open("config.json", "r") as file:
            config = json.load(file)
    except FileNotFoundError:
        config = {}

    config["status"] = new_value

    with open("config.json", "w") as file:
        json.dump(config, file)
