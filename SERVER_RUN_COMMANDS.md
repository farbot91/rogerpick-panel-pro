# دستورات راه‌اندازی پروژه روی سرور

مسیر پروژه روی سرور:

```bash
/offline_ubuntu24_bundle
```

## راه‌اندازی کامل از صفر

### روش ساده با صفحه وب Setup

اگر می‌خواهید تنظیمات حساس را بدون ویرایش دستی فایل‌ها وارد کنید، این دستور را بزنید:

```bash
cd /offline_ubuntu24_bundle
chmod +x setup.sh
./setup.sh
```

بعد در مرورگر باز کنید:

```text
http://SERVER_IP:8000
```

در صفحه setup این موارد را وارد کنید:

- توکن ربات تلگرام
- آیدی عددی ادمین اصلی
- پسورد ورود ادمین پنل
- کانفیگ JSON پروکسی Xray برای ارتباط تلگرام

بعد از ذخیره، دکمه `Start Setup` را بزنید تا نصب آفلاین، نصب Xray، تنظیم پروکسی تلگرام و اجرای سرویس‌ها انجام شود.

وقتی setup موفق شد، دکمه `Finish و بستن setup` را بزنید. این کار خود صفحه setup را متوقف می‌کند و فایل‌های setup را از روی سرور حذف می‌کند.

### روش دستی با ترمینال

این دستور را وقتی بزن که دایرکتوری پروژه را تازه روی سرور گذاشتی یا می‌خواهی نصب آفلاین کامل دوباره انجام شود:

```bash
cd /offline_ubuntu24_bundle && \
chmod +x install_offline.sh bootstrap_offline.sh scripts/*.sh && \
python3 - <<'PY'
from pathlib import Path

p = Path("install_offline.sh")
s = p.read_text()

old = '''if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    VIRTUALENV_WHEEL="$(ls "$WHEEL_DIR"/virtualenv-*.whl | head -n 1)"
    "$PYTHON_BIN" "$VIRTUALENV_WHEEL" "$VENV_DIR" --no-download --extra-search-dir "$WHEEL_DIR"
fi'''

new = '''if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    rm -rf "$VENV_DIR"
    WHEEL_PATHS="$(printf ":%s" "$WHEEL_DIR"/*.whl)"
    PYTHONPATH="${WHEEL_PATHS#:}" "$PYTHON_BIN" -m virtualenv "$VENV_DIR" --no-download --extra-search-dir "$WHEEL_DIR"
fi'''

if old in s:
    p.write_text(s.replace(old, new))
    print("install_offline.sh patched")
else:
    print("install_offline.sh already patched")
PY
./scripts/stop_all.sh
./scripts/install_xray_offline.sh
./install_offline.sh
./scripts/start_xray.sh
./scripts/set_telegram_proxy.sh socks5h://127.0.0.1:9050
./scripts/start_all.sh
./scripts/status.sh
sleep 3
tail -n 40 project/logs/bot.err.log
tail -n 40 project/logs/web_panel.err.log
```

## ری‌استارت سریع

این دستور را وقتی بزن که پروژه قبلا نصب شده و فقط می‌خواهی سرویس‌ها دوباره بالا بیایند:

```bash
cd /offline_ubuntu24_bundle && \
./scripts/stop_all.sh && \
./scripts/start_xray.sh && \
./scripts/set_telegram_proxy.sh socks5h://127.0.0.1:9050 && \
./scripts/start_all.sh && \
./scripts/status.sh
```

## تست اتصال تلگرام

```bash
cd /offline_ubuntu24_bundle

TOKEN=$(python3 - <<'PY'
import json
print(json.load(open('/offline_ubuntu24_bundle/project/web_panel_settings.json'))['bot_token'])
PY
)

curl --max-time 20 --socks5-hostname 127.0.0.1:9050 \
  "https://api.telegram.org/bot$TOKEN/getMe"
```

اگر خروجی شامل `"ok":true` بود، اتصال تلگرام از مسیر پروکسی سالم است.

## لاگ‌ها

```bash
cd /offline_ubuntu24_bundle

tail -n 80 project/logs/bot.err.log
tail -n 80 project/logs/web_panel.err.log
tail -n 80 project/logs/xray.err.log
```

هشدار Flask با متن `This is a development server` خطای اجرای پروژه نیست.
