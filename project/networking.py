from __future__ import annotations

import requests
import socket
from telebot import apihelper
from urllib.parse import urlparse


_ORIGINAL_SESSION_REQUEST = requests.sessions.Session.request
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_TELEGRAM_PROXY_URL = ""
_TELEGRAM_API_IP = ""
_REQUEST_PATCHED = False
_DNS_PATCHED = False


def _telegram_request_with_proxy(self, method, url, **kwargs):
    host = urlparse(str(url)).hostname
    if host == "api.telegram.org" and _TELEGRAM_PROXY_URL:
        kwargs["proxies"] = {
            "http": _TELEGRAM_PROXY_URL,
            "https": _TELEGRAM_PROXY_URL,
        }
    return _ORIGINAL_SESSION_REQUEST(self, method, url, **kwargs)


def _telegram_getaddrinfo(host, port, *args, **kwargs):
    if host == "api.telegram.org" and _TELEGRAM_API_IP:
        host = _TELEGRAM_API_IP
    return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)


def configure_telegram_proxy(proxy_url: str | None, api_ip: str | None = None) -> None:
    global _TELEGRAM_PROXY_URL, _TELEGRAM_API_IP, _REQUEST_PATCHED, _DNS_PATCHED
    proxy_url = (proxy_url or "").strip()
    api_ip = (api_ip or "").strip()
    _TELEGRAM_PROXY_URL = proxy_url
    _TELEGRAM_API_IP = api_ip
    if proxy_url:
        apihelper.proxy = {
            "http": proxy_url,
            "https": proxy_url,
        }
        if not _REQUEST_PATCHED:
            requests.sessions.Session.request = _telegram_request_with_proxy
            _REQUEST_PATCHED = True
    else:
        apihelper.proxy = None
    if not _DNS_PATCHED:
        socket.getaddrinfo = _telegram_getaddrinfo
        _DNS_PATCHED = True


def direct_requests_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    return session
