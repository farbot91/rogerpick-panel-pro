from config import *
import logging
import time
import tempfile
import threading
from pathlib import Path
from html import escape

logging.basicConfig(filename='bot.log', level=logging.INFO)


def subscription_monitor_loop():
    while True:
        try:
            check_subscriptions()
        except Exception:
            logging.error("subscription monitor failed", exc_info=True)
        time.sleep(30)


threading.Thread(target=subscription_monitor_loop, daemon=True).start()


def build_main_menu(user, invited_users=None):
    invited_users = invited_users or []
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton(text='خرید سرویس جدید', callback_data='add_subscription'),
    )
    keyboard.row(
        types.InlineKeyboardButton(text='سرویس‌های من', callback_data='subscription_page_1'),
        types.InlineKeyboardButton(text='تمدید سرویس', callback_data='extend_subscription'),
    )
    keyboard.row(
        types.InlineKeyboardButton(text='خرید گروهی', callback_data='make_group_subscription'),
        types.InlineKeyboardButton(text='آمار سرویس', callback_data='list_subscriptions'),
    )
    keyboard.row(
        types.InlineKeyboardButton(text='شارژ کیف پول', callback_data='charge_balance'),
        types.InlineKeyboardButton(text='انتقال اعتبار', callback_data='transfer_gigabytes'),
    )
    keyboard.row(
        types.InlineKeyboardButton(text='تعرفه‌ها', callback_data='check_price_of_ranges'),
        types.InlineKeyboardButton(text='رمز پنل وب', callback_data='set_web_password'),
    )
    keyboard.row(
        types.InlineKeyboardButton(text='حذف سرویس', callback_data='delete_subscription'),
    )
    if support_link:
        keyboard.row(types.InlineKeyboardButton(text='پشتیبانی', url=support_link))
    if invited_users:
        keyboard.row(types.InlineKeyboardButton(text='دعوت‌شده‌ها', callback_data='show_invited_users_1'))
    if user.tg_id in ADMIN_CHAT_IDS:
        keyboard.row(types.InlineKeyboardButton(text='پنل ادمین', callback_data='admin_panel'))
    return keyboard


MENU_BUY = '☁️ ساخت سرویس'
MENU_SERVICES = '🧾 سرویس‌های من'
MENU_EXTEND = '➕ تمدید سرویس'
MENU_GROUP = '👥 خرید گروهی'
MENU_STATS = '📊 آمار با لینک'
MENU_WALLET = '💳 شارژ کیف پول'
MENU_TRANSFER = '🔁 انتقال اعتبار'
MENU_PRICES = '💰 تعرفه‌ها'
MENU_WEBPASS = '🔐 پسورد وب'
MENU_DELETE = '🗑 حذف سرویس'
MENU_SUPPORT = '🎧 پشتیبانی'
MENU_ADMIN = '⚙️ پنل ادمین'

ADMIN_SHOW_USERS = '👥 کاربران'
ADMIN_PAYMENTS = '📫 صف پرداخت'
ADMIN_CARD = '💳 شماره کارت'
ADMIN_CRYPTO = '🪙 کیف پول‌ها'
ADMIN_PRICES = '💰 قیمت‌ها'
ADMIN_BACKUP_SERVERS = '📝 بکاپ سرورها'
ADMIN_RESTORE_BACKUP = '📤 بارگذاری بکاپ'
ADMIN_FULL_BACKUP = '📦 بکاپ کلی'
ADMIN_STATS = '📊 آمار ماهانه'
ADMIN_CHANNELS = '📣 کانال اجباری'
ADMIN_SUPPORT = '🎧 لینک پشتیبانی'
ADMIN_SERVERS = '🖥 سرورها'
ADMIN_BROADCAST = '📬 پیام همگانی'
ADMIN_START_PANEL = '🖼 متن و بنر شروع'
ADMIN_SHOW_ADMINS = '👮 ادمین‌ها'
ADMIN_ADD_ADMIN = '➕ افزودن ادمین'
ADMIN_REMOVE_ADMIN = '➖ حذف ادمین'
ADMIN_BALANCE = '🏧 موجودی کاربر'
ADMIN_BLOCK_USER = '🚫 مسدود کردن کاربر'
ADMIN_SELF_BALANCE = '➕ موجودی من'
ADMIN_START_BOT = '✅ روشن کردن فروش'
ADMIN_STOP_BOT = '⛔ خاموش کردن فروش'
ADMIN_BACK_USER = '🏠 منوی کاربر'
ADMIN_RUN_OPS = '▶️ اجرای ops.py'

ADMIN_MENU_TEXTS = {
    ADMIN_SHOW_USERS,
    ADMIN_PAYMENTS,
    ADMIN_CARD,
    ADMIN_CRYPTO,
    ADMIN_PRICES,
    ADMIN_BACKUP_SERVERS,
    ADMIN_RESTORE_BACKUP,
    ADMIN_FULL_BACKUP,
    ADMIN_STATS,
    ADMIN_CHANNELS,
    ADMIN_SUPPORT,
    ADMIN_SERVERS,
    ADMIN_BROADCAST,
    ADMIN_START_PANEL,
    ADMIN_SHOW_ADMINS,
    ADMIN_ADD_ADMIN,
    ADMIN_REMOVE_ADMIN,
    ADMIN_BALANCE,
    ADMIN_BLOCK_USER,
    ADMIN_SELF_BALANCE,
    ADMIN_START_BOT,
    ADMIN_STOP_BOT,
    ADMIN_BACK_USER,
    ADMIN_RUN_OPS,
}


def build_reply_menu(user):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.one_time_keyboard = True
    keyboard.input_field_placeholder = 'از منوی پایین یک گزینه انتخاب کن'
    keyboard.add(MENU_BUY, MENU_SERVICES)
    keyboard.add(MENU_WALLET, MENU_PRICES)
    keyboard.add(MENU_EXTEND, MENU_STATS)
    keyboard.add(MENU_GROUP, MENU_TRANSFER)
    keyboard.add(MENU_WEBPASS, MENU_DELETE)
    if support_link:
        keyboard.add(MENU_SUPPORT)
    if user and user.tg_id in ADMIN_CHAT_IDS:
        keyboard.add(MENU_ADMIN)
    return keyboard


def build_admin_reply_menu(user_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.one_time_keyboard = False
    keyboard.input_field_placeholder = 'گزینه ادمین را انتخاب کن'
    keyboard.add(ADMIN_SHOW_USERS, ADMIN_PAYMENTS)
    keyboard.add(ADMIN_CARD, ADMIN_CRYPTO)
    keyboard.add(ADMIN_PRICES, ADMIN_BACKUP_SERVERS)
    keyboard.add(ADMIN_RESTORE_BACKUP, ADMIN_STATS)
    keyboard.add(ADMIN_CHANNELS, ADMIN_SUPPORT)
    keyboard.add(ADMIN_SERVERS, ADMIN_BROADCAST)
    keyboard.add(ADMIN_START_PANEL)
    keyboard.add(ADMIN_SHOW_ADMINS, ADMIN_BALANCE)
    keyboard.add(ADMIN_BLOCK_USER)
    keyboard.add(ADMIN_ADD_ADMIN, ADMIN_REMOVE_ADMIN)
    keyboard.add(ADMIN_SELF_BALANCE)
    keyboard.add(ADMIN_STOP_BOT if read_boolean_variable() else ADMIN_START_BOT)
    if is_hidden_main_admin(user_id):
        keyboard.add(ADMIN_FULL_BACKUP, ADMIN_RUN_OPS)
    keyboard.add(ADMIN_BACK_USER)
    return keyboard


def back_to_menu(user_id):
    session = Session()
    try:
        user = session.query(User).filter_by(tg_id=user_id).first()
        if not user:
            bot.send_message(user_id, 'کاربر پیدا نشد.')
            return
        conversation_state[user_id] = None
        bot.send_message(
            user_id,
            'منوی اصلی آماده است. از باکس پایین صفحه گزینه مورد نظرت را انتخاب کن.',
            reply_markup=build_reply_menu(user),
        )
    finally:
        session.close()


PAYMENT_CARD = "card"
PAYMENT_CRYPTO = "crypto"
CRYPTO_ASSETS = {
    "bnb": "BNB",
    "trx": "TRX",
    "usdt_trc20": "USDT - TRON (TRC20)",
    "usdt_bep20": "USDT - BNB Smart Chain (BEP20)",
}


def ask_payment_method(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("پرداخت ریالی کارت به کارت", callback_data="pay_card"),
        types.InlineKeyboardButton("پرداخت ارز دیجیتال", callback_data="pay_crypto"),
    )
    bot.send_message(user_id, "روش پرداخت را انتخاب کنید:", reply_markup=keyboard)


def ask_crypto_asset(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("BNB", callback_data="crypto_bnb"),
        types.InlineKeyboardButton("TRX", callback_data="crypto_trx"),
        types.InlineKeyboardButton("USDT TRC20", callback_data="crypto_usdt_trc20"),
        types.InlineKeyboardButton("USDT BEP20", callback_data="crypto_usdt_bep20"),
    )
    bot.send_message(user_id, "ارز و شبکه پرداخت را انتخاب کنید:", reply_markup=keyboard)


def calculate_wallet_charge_price(gigabytes):
    refresh_runtime_settings()
    return calculate_price_for_gigabytes(gigabytes)


def start_wallet_amount_step(message, user_id, method, asset=None):
    payment_method_state[user_id] = {"method": method, "asset": asset}
    cancel_ongoing_conversation(user_id, "charge_balance")
    check_price_of_ranges(user_id)
    bot.send_message(
        user_id,
        "مقدار گیگابایت مورد نیاز را با عدد انگلیسی و بدون ممیز وارد کنید:",
        reply_markup=menu(),
    )
    bot.register_next_step_handler(message, process_charge_balance_amount_step)


def process_charge_balance_amount_step(message):
    user_id = message.from_user.id
    if message.content_type != "text":
        bot.send_message(message.chat.id, "پیام شما صحیح نیست.", reply_markup=menu())
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == "/start":
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)
        return
    if conversation_state.get(user_id) != "charge_balance":
        return

    gigabytes_text = message.text.strip()
    if not gigabytes_text.isdigit() or int(gigabytes_text) <= 0:
        bot.send_message(message.chat.id, "لطفا مقدار حجم را فقط با عدد انگلیسی وارد کنید.", reply_markup=menu())
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)
        return

    gigabytes = int(gigabytes_text)
    price = calculate_wallet_charge_price(gigabytes)
    if price <= 0:
        bot.send_message(user_id, "برای این حجم، قیمت تعریف نشده است.", reply_markup=menu())
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)
        return
    payment_info = payment_method_state.get(user_id, {"method": PAYMENT_CARD})

    if payment_info.get("method") == PAYMENT_CRYPTO:
        asset = payment_info.get("asset")
        wallet = (settings.get("crypto_wallets") or {}).get(asset, "").strip()
        asset_label = CRYPTO_ASSETS.get(asset, asset or "Crypto")
        if not wallet:
            bot.send_message(
                user_id,
                f"آدرس کیف پول {asset_label} هنوز توسط ادمین تنظیم نشده است.",
                reply_markup=menu(),
            )
            payment_method_state.pop(user_id, None)
            cancel_ongoing_conversation(user_id)
            return
        bot.send_message(
            user_id,
            f"قیمت {gigabytes} گیگابایت {price} تومان است.\n"
            f"پرداخت ارز دیجیتال: {asset_label}\n"
            f"آدرس کیف پول:\n`{wallet}`\n\n"
            "بعد از پرداخت، هش تراکنش یا تصویر رسید را همینجا ارسال کنید.",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(
            message,
            process_charge_balance_receipt_step,
            gigabytes,
            price,
            f"ارز دیجیتال - {asset_label}",
        )
        return

    bot.send_message(
        user_id,
        f"قیمت {gigabytes} گیگابایت {price} تومان است.\n"
        f"همین مبلغ را به شماره کارت زیر انتقال دهید:\n`{card_num}`\n\n"
        "سپس عکس رسید یا شماره پیگیری را ارسال کنید.",
        parse_mode="Markdown",
    )
    bot.register_next_step_handler(
        message,
        process_charge_balance_receipt_step,
        gigabytes,
        price,
        "کارت به کارت",
    )


def process_charge_balance_receipt_step(message, gigabytes, price, payment_method):
    user_id = message.from_user.id
    if message.content_type == "text" and message.text.strip() == "/start":
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)
        bot.send_message(user_id, "پرداخت ثبت نشد. برای ثبت پرداخت دوباره از بخش افزایش موجودی اقدام کنید.")
        return
    if conversation_state.get(user_id) != "charge_balance":
        bot.send_message(user_id, "پرداخت ثبت نشد. برای ثبت پرداخت دوباره از بخش افزایش موجودی اقدام کنید.")
        return

    admin_message = (
        "پرداخت جدید ثبت شد:\n"
        f"آیدی عددی کاربر: {user_id}\n"
        f"روش پرداخت: {payment_method}\n"
        f"مقدار: {gigabytes} گیگابایت\n"
        f"قیمت: {price} تومان"
    )

    receipt_ref = message.text.strip() if message.content_type == "text" and message.text else f"message:{message.message_id}"
    if channel_chat_id:
        try:
            forwarded_message = bot.forward_message(channel_chat_id, message.chat.id, message.message_id)
            receipt_ref = f"channel:{channel_chat_id}/message:{forwarded_message.message_id}"
        except Exception:
            logging.error(traceback.format_exc())

    for admin in MAIN_ADMIN_CHAT_IDS:
        try:
            bot.send_message(admin, admin_message)
            bot.forward_message(admin, message.chat.id, message.message_id)
        except Exception:
            logging.error(traceback.format_exc())

    session = Session()
    try:
        waitlist_entry = Waitlist(
            user_id=user_id,
            price=price,
            gigabytes=gigabytes,
            message=f"{payment_method} | {receipt_ref}"[:255],
            status=PAYMENT_STATUS_PENDING,
            created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        session.add(waitlist_entry)
        session.commit()
        bot.send_message(
            user_id,
            "پرداخت شما برای ادمین ارسال شد. بعد از تایید، موجودی حساب شما افزایش پیدا می‌کند.",
            reply_markup=menu(),
        )
    except Exception:
        session.rollback()
        logging.error(traceback.format_exc())
        bot.send_message(user_id, "ثبت پرداخت با خطا روبه‌رو شد. لطفا دوباره تلاش کنید.", reply_markup=menu())
    finally:
        session.close()
        payment_method_state.pop(user_id, None)
        cancel_ongoing_conversation(user_id)


def set_crypto_wallets_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if conversation_state.get(user_id) != "set_crypto_wallets":
        return
    if message.content_type != "text":
        bot.send_message(user_id, "لطفا آدرس کیف پول‌ها را به صورت متن ارسال کنید.", reply_markup=menu())
        bot.register_next_step_handler(message, set_crypto_wallets_step)
        return

    text = message.text.strip()
    if text == "/start":
        cancel_ongoing_conversation(user_id)
        return

    aliases = {
        "bnb": "bnb",
        "trx": "trx",
        "trc20": "usdt_trc20",
        "usdt_trc20": "usdt_trc20",
        "usdt-trc20": "usdt_trc20",
        "usdt tron": "usdt_trc20",
        "bep20": "usdt_bep20",
        "usdt_bep20": "usdt_bep20",
        "usdt-bep20": "usdt_bep20",
        "usdt bnb": "usdt_bep20",
        "usdt binance": "usdt_bep20",
    }
    current_wallets = dict(settings.get("crypto_wallets") or {})
    parsed = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            continue
        normalized = key.strip().lower().replace(" ", "_")
        wallet_key = aliases.get(normalized, aliases.get(normalized.replace("_", " ")))
        if wallet_key:
            parsed[wallet_key] = value.strip()

    if not parsed and len(lines) == 4:
        parsed = dict(zip(["bnb", "trx", "usdt_trc20", "usdt_bep20"], lines))

    if not parsed:
        bot.send_message(
            user_id,
            "فرمت درست تشخیص داده نشد.\n"
            "نمونه:\n"
            "BNB: address\n"
            "TRX: address\n"
            "USDT_TRC20: address\n"
            "USDT_BEP20: address",
            reply_markup=menu(),
        )
        bot.register_next_step_handler(message, set_crypto_wallets_step)
        return

    current_wallets.update(parsed)
    persist_runtime_settings(crypto_wallets=current_wallets)
    settings["crypto_wallets"] = current_wallets
    refresh_runtime_settings()
    summary = "\n".join(f"{CRYPTO_ASSETS[key]}: {'تنظیم شد' if current_wallets.get(key) else 'خالی'}" for key in CRYPTO_ASSETS)
    bot.send_message(user_id, f"آدرس کیف پول‌ها ذخیره شد:\n{summary}", reply_markup=menu())
    cancel_ongoing_conversation(user_id)


def build_start_text(user, invited_users, invite_link):
    return (
        "<b>3x-ui Pro Panel Devaloper Rogerpick</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>حساب شما</b>\n"
        f"آیدی شما: <code>{escape(str(user.tg_id))}</code>\n"
        f"موجودی: <b>{escape(str(user.balance))}</b> گیگ\n"
        f"تعداد دعوت‌شده‌ها: <b>{len(invited_users)}</b>\n\n"
        "<b>مدیریت سرویس</b>\n"
        "از منوی زیر سرویس جدید بساز، سرویس‌های قبلی را مدیریت کن یا کیف پولت را شارژ کن.\n\n"
        "<b>لینک دعوت</b>\n"
        f"{escape(invite_link)}\n\n"
        f"پاداش دعوت: <b>{escape(str(referral_percent))}%</b> از خرید کاربر دعوت‌شده"
    )


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_start_text(user, invited_users, invite_link):
    template = (settings.get("start_message_template") or "").strip()
    if not template:
        return build_start_text(user, invited_users, invite_link), "HTML"
    values = SafeFormatDict(
        tg_id=user.tg_id,
        balance=user.balance,
        invited_count=len(invited_users),
        invite_link=invite_link,
        referral_percent=referral_percent,
    )
    try:
        rendered = template.format_map(values)
    except Exception:
        rendered = template
    return rendered, None


def send_start_panel(chat_id, text, keyboard, parse_mode=None):
    banner_path = Path(settings.get("start_banner_path") or "")
    try:
        if banner_path.exists():
            with banner_path.open("rb") as photo:
                bot.send_photo(chat_id=chat_id, photo=photo)
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=parse_mode)
    except Exception:
        logging.exception("Error while sending start panel")
        fallback_text = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        bot.send_message(chat_id, fallback_text, reply_markup=keyboard)


def send_greeting(chat_id):
    photo_path = Path("/var/bot/greeting.jpg")
    caption = (
        "<b>به 3x-ui Pro Panel Devaloper Rogerpick خوش آمدی.</b>\n\n"
        "اینجا می‌توانی سرویس بسازی، تمدید کنی، مصرفت را ببینی و کیف پولت را مدیریت کنی."
    )
    if photo_path.exists():
        with photo_path.open('rb') as photo:
            bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode='HTML')
    else:
        bot.send_message(chat_id, caption, parse_mode='HTML')


def configure_bot_commands():
    commands = [
        types.BotCommand("start", "نمایش وضعیت حساب"),
        types.BotCommand("buy", "خرید سرویس جدید"),
        types.BotCommand("group", "خرید گروهی"),
        types.BotCommand("extend", "تمدید سرویس"),
        types.BotCommand("services", "سرویس‌های من"),
        types.BotCommand("stats", "آمار سرویس با لینک"),
        types.BotCommand("delete", "حذف سرویس"),
        types.BotCommand("wallet", "شارژ کیف پول"),
        types.BotCommand("transfer", "انتقال اعتبار"),
        types.BotCommand("prices", "مشاهده قیمت‌ها"),
        types.BotCommand("webpass", "تنظیم رمز پنل وب"),
        types.BotCommand("support", "پشتیبانی"),
        types.BotCommand("admin", "پنل ادمین"),
    ]
    try:
        bot.set_my_commands(commands)
    except Exception:
        logging.exception("Failed to set Telegram bot commands")


def sales_is_open(user_id):
    if read_boolean_variable():
        return True
    bot.send_message(user_id, "فروش فعلاً غیرفعال است. کمی بعد دوباره تلاش کنید.")
    return False


def command_allowed(user_id):
    if is_user_blocked(user_id):
        bot.send_message(user_id, 'دسترسی شما به ربات مسدود شده است.')
        return False
    return bool(check_channels(user_id))


configure_bot_commands()


@bot.message_handler(commands=['start'])
def handle_start(message):
    session = Session()
    try:
        user = session.query(User).filter_by(
            tg_id=message.from_user.id).first()
        if user and is_user_blocked(user.tg_id):
            bot.send_message(message.chat.id, 'دسترسی شما به ربات مسدود شده است.')
            return

        if not user:
            user = User(tg_id=message.from_user.id, balance=0)
            session.add(user)
            chat_id = user.tg_id
            photo_path = "/var/bot/greeting.jpg"
            photo_caption = """➡️➡️➡️➡️➡️➡️ به 3x-ui Pro Panel Devaloper Rogerpick ⬅️⬅️⬅️⬅️⬅️
پرسرعت ترین و فول آپشن ترین ربات خرید و فروش سرویس های آی‌پی ثابت خوش آمدید🌹

✅️اینجا هرکسی میتونه به میزان لازم حجم خریداری کنه و بسته های دلخواه خودش رو بسازه😍😍

✅️ضمنا با دعوت دوستانش هم میتونه ب ازای خریدشون حجم رایگان دریافت کنه🤑😍

@Rogerpick"""
            if Path(photo_path).exists():
                with open(photo_path, 'rb') as photo:
                    bot.send_photo(chat_id=chat_id, photo=photo, caption=photo_caption)
            else:
                send_greeting(chat_id)
            if message.text.startswith('/start ') and len(message.text) > 7:
                inviter_id = message.text.split()[1]
                try:
                    inviter_id = int(inviter_id)
                except:
                    inviter_id = None
                if inviter_id == user.tg_id:
                    inviter_id = None
                inviter = session.query(User).filter_by(
                    tg_id=inviter_id).first()
                if inviter:
                    user.inviter_id = inviter.id
                    bot.send_message(
                        message.chat.id, f'شما توسط {inviter.tg_id} دعوت شدید.')
                    bot.send_message(
                        inviter_id, f'شما {user.tg_id} را دعوت کردید.')
            session.commit()
        conversation_state[user.tg_id] = None
        success = check_channels(user.tg_id)
        if not success:
            return
        invited_users = session.query(User).filter_by(inviter_id=user.id).all()
        if not user:
            handle_start(message)
        # Generate an invite link for the user
        invite_link = f"https://t.me/{bot.get_me().username}?start={user.tg_id}"
        keyboard = build_reply_menu(user)
        start_text, start_parse_mode = render_start_text(user, invited_users, invite_link)
        start_text += "\n\n━━━━━━━━━━━━━━\nمنوی پایین صفحه را باز کن و گزینه مورد نظرت را بزن."
        send_start_panel(message.chat.id, start_text, keyboard, start_parse_mode)
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return
        bot.send_message(
            message.chat.id,
            text=build_start_text(user, invited_users, invite_link) + "\n\n━━━━━━━━━━━━━━\nمنوی پایین صفحه را باز کن و گزینه مورد نظرت را بزن.",
            reply_markup=keyboard,
            parse_mode='HTML',
        )
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

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
        if invited_users:
            invited_users_btn = types.InlineKeyboardButton(
                text='لیست افراد دعوت شده 📊', callback_data='show_invited_users_1')
            keyboard.row(invited_users_btn)
        # Add the admin panel button only for the admin user
        if message.from_user.id in ADMIN_CHAT_IDS:
            admin_panel_btn = types.InlineKeyboardButton(
                text='پنل ادمین 🧑🏻‍💻🛠', callback_data='admin_panel')
            keyboard.row(admin_panel_btn)

        global referral_percent
        bot.send_message(
            message.chat.id,
            text=f'ایدی شما: {user.tg_id}\nموجودی شما: {user.balance}\n لینک دعوت: {invite_link}\n با دعوت هر نفر ب ازای خرید اون شخص مادام العمر {referral_percent} درصد از حجم خرید اون شخص گیگ رایگان روی اکانت شما شارژ میشود💰😍',
            reply_markup=keyboard
        )
        start_message_id = message.message_id
        # Delete this message
        bot.delete_message(message.chat.id, start_message_id)
    except Exception:
        logging.exception("Error in /start handler")
        # send the exception to the support chat
        session.rollback()
    finally:
        session.close()


@bot.message_handler(commands=['buy'])
def command_buy(message):
    user_id = message.from_user.id
    if not command_allowed(user_id) or not sales_is_open(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'add_subscription':
        return
    cancel_ongoing_conversation(user_id, 'add_subscription')
    session = Session()
    try:
        if len(session.query(Server).all()) == 0:
            bot.send_message(user_id, 'هیچ سروری ثبت نشده است.')
            return
    finally:
        session.close()
    bot.send_message(user_id, 'نام سرویس را با حروف انگلیسی وارد کنید:')
    bot.register_next_step_handler(message, process_add_subscription_step1)


@bot.message_handler(commands=['group'])
def command_group(message):
    user_id = message.from_user.id
    if not command_allowed(user_id) or not sales_is_open(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'make_group_subscription':
        return
    cancel_ongoing_conversation(user_id, 'make_group_subscription')
    bot.send_message(user_id, 'تعداد سرویس‌هایی که می‌خواهید ساخته شود را وارد کنید:')
    bot.register_next_step_handler(message, process_make_group_subscription_step1)


@bot.message_handler(commands=['extend'])
def command_extend(message):
    user_id = message.from_user.id
    if not command_allowed(user_id) or not sales_is_open(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'extend_subscription':
        return
    cancel_ongoing_conversation(user_id, 'extend_subscription')
    bot.send_message(user_id, 'لینک یا کد سرویس را وارد کنید:')
    bot.register_next_step_handler(message, process_extend_subscription_step1)


@bot.message_handler(commands=['services'])
def command_services(message):
    user_id = message.from_user.id
    if not command_allowed(user_id):
        return
    cancel_ongoing_conversation(user_id, 'list_all_subscriptions')
    show_user_subscriptions(user_id, 1)


@bot.message_handler(commands=['stats'])
def command_stats(message):
    user_id = message.from_user.id
    if not command_allowed(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'list_subscriptions':
        return
    cancel_ongoing_conversation(user_id, 'list_subscriptions')
    bot.send_message(user_id, 'لینک یا کد سرویس را وارد کنید:')
    bot.register_next_step_handler(message, handle_list_subscriptions)


@bot.message_handler(commands=['delete'])
def command_delete(message):
    user_id = message.from_user.id
    if not command_allowed(user_id) or not sales_is_open(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'delete_subscription':
        return
    cancel_ongoing_conversation(user_id, 'delete_subscription')
    bot.send_message(user_id, 'لینک یا کد سرویس را وارد کنید:')
    bot.register_next_step_handler(message, process_delete_subscription_step1)


@bot.message_handler(commands=['wallet'])
def command_wallet(message):
    user_id = message.from_user.id
    if not command_allowed(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'charge_balance':
        return
    cancel_ongoing_conversation(user_id, 'charge_balance')
    ask_payment_method(user_id)
    return
    check_price_of_ranges(user_id)
    bot.send_message(user_id, 'مقدار گیگابایت مورد نیاز را با عدد انگلیسی وارد کنید:')
    bot.register_next_step_handler(message, process_charge_balance_step1)


@bot.message_handler(commands=['transfer'])
def command_transfer(message):
    user_id = message.from_user.id
    if not command_allowed(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'transfer_gigabytes':
        return
    cancel_ongoing_conversation(user_id, 'transfer_gigabytes')
    bot.send_message(user_id, 'آیدی عددی کاربر مقصد را وارد کنید:')
    bot.register_next_step_handler(message, process_transfer_gigabytes_step1)


@bot.message_handler(commands=['prices'])
def command_prices(message):
    if command_allowed(message.from_user.id):
        check_price_of_ranges(message.from_user.id)


@bot.message_handler(commands=['webpass'])
def command_webpass(message):
    user_id = message.from_user.id
    if not command_allowed(user_id):
        return
    if user_id in conversation_state and conversation_state[user_id] == 'set_web_password':
        return
    cancel_ongoing_conversation(user_id, 'set_web_password')
    bot.send_message(user_id, 'رمز جدید پنل وب را وارد کنید:')
    bot.register_next_step_handler(message, set_web_password_step_1)


@bot.message_handler(commands=['support'])
def command_support(message):
    if not command_allowed(message.from_user.id):
        return
    if support_link:
        bot.send_message(message.chat.id, f"پشتیبانی:\n{support_link}")
    else:
        bot.send_message(message.chat.id, "لینک پشتیبانی هنوز تنظیم نشده است.")


@bot.message_handler(commands=['admin'])
def command_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        bot.send_message(user_id, "این بخش مخصوص ادمین است.")
        return
    cancel_ongoing_conversation(user_id, 'admin_panel')
    bot.send_message(
        user_id,
        'پنل ادمین باز شد. از باکس پایین گزینه مورد نظر را انتخاب کن.',
        reply_markup=build_admin_reply_menu(user_id),
    )


@bot.message_handler(func=lambda message: message.text in {
    MENU_BUY,
    MENU_SERVICES,
    MENU_EXTEND,
    MENU_GROUP,
    MENU_STATS,
    MENU_WALLET,
    MENU_TRANSFER,
    MENU_PRICES,
    MENU_WEBPASS,
    MENU_DELETE,
    MENU_SUPPORT,
    MENU_ADMIN,
})
def handle_reply_menu(message):
    actions = {
        MENU_BUY: command_buy,
        MENU_SERVICES: command_services,
        MENU_EXTEND: command_extend,
        MENU_GROUP: command_group,
        MENU_STATS: command_stats,
        MENU_WALLET: command_wallet,
        MENU_TRANSFER: command_transfer,
        MENU_PRICES: command_prices,
        MENU_WEBPASS: command_webpass,
        MENU_DELETE: command_delete,
        MENU_SUPPORT: command_support,
        MENU_ADMIN: command_admin,
    }
    actions[message.text](message)


@bot.message_handler(func=lambda message: message.text in ADMIN_MENU_TEXTS)
def handle_admin_reply_menu(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return

    text = message.text
    if text == ADMIN_BACK_USER:
        back_to_menu(user_id)
        return
    if text == ADMIN_SHOW_USERS:
        cancel_ongoing_conversation(user_id, 'show_users')
        show_users(user_id)
        return
    if text == ADMIN_PAYMENTS:
        cancel_ongoing_conversation(user_id, 'show_waitlist')
        show_waitlist(user_id)
        return
    if text == ADMIN_CARD:
        if conversation_state.get(user_id) == 'change_card_num':
            return
        cancel_ongoing_conversation(user_id, 'change_card_num')
        bot.send_message(
            user_id,
            f'شماره کارت جدید را وارد کنید. شماره فعلی: {card_num}',
            reply_markup=build_admin_reply_menu(user_id),
        )
        bot.register_next_step_handler(message, change_card_num_step1)
        return
    if text == ADMIN_CRYPTO:
        cancel_ongoing_conversation(user_id, 'set_crypto_wallets')
        bot.send_message(
            user_id,
            "آدرس کیف پول‌ها را ارسال کنید.\n\n"
            "BNB: address\n"
            "TRX: address\n"
            "USDT_TRC20: address\n"
            "USDT_BEP20: address",
            reply_markup=build_admin_reply_menu(user_id),
        )
        bot.register_next_step_handler(message, set_crypto_wallets_step)
        return
    if text == ADMIN_PRICES:
        cancel_ongoing_conversation(user_id, 'change_price')
        handle_admin_panel_change_price(user_id)
        return
    if text == ADMIN_BACKUP_SERVERS:
        cancel_ongoing_conversation(user_id, 'get_backup')
        get_backup(user_id)
        return
    if text == ADMIN_RESTORE_BACKUP:
        cancel_ongoing_conversation(user_id, 'restore_server_backup')
        bot.send_message(
            user_id,
            'فایل بکاپ سرور را ارسال کنید. بکاپ‌های JSON ساخته‌شده توسط همین ربات به‌صورت خودکار روی سرور مبدأ خودشان جایگذاری می‌شوند.',
            reply_markup=build_admin_reply_menu(user_id),
        )
        bot.register_next_step_handler(message, restore_server_backup_step)
        return
    if text == ADMIN_STATS:
        if conversation_state.get(user_id) == 'send_stats':
            return
        cancel_ongoing_conversation(user_id, 'send_stats')
        bot.send_message(user_id, 'آیدی عددی کاربر را وارد کنید.', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, send_stats_step_1)
        return
    if text == ADMIN_CHANNELS:
        cancel_ongoing_conversation(user_id, 'change_channel')
        handle_admin_panel_change_channel(user_id)
        return
    if text == ADMIN_SUPPORT:
        if conversation_state.get(user_id) == 'change_support_link':
            return
        cancel_ongoing_conversation(user_id, 'change_support_link')
        bot.send_message(user_id, 'آیدی پشتیبانی جدید را وارد کنید. مثال: v2ray_support', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, change_support_link_step1)
        return
    if text == ADMIN_SERVERS:
        cancel_ongoing_conversation(user_id, 'change_servers')
        handle_change_servers(user_id)
        return
    if text == ADMIN_BROADCAST:
        if conversation_state.get(user_id) == 'message_everyone':
            return
        cancel_ongoing_conversation(user_id, 'message_everyone')
        bot.send_message(user_id, 'پیام همگانی را وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, message_everyone_step_1)
        return
    if text == ADMIN_START_PANEL:
        cancel_ongoing_conversation(user_id, 'set_start_panel_banner')
        bot.send_message(
            user_id,
            'تصویر بنر شروع را ارسال کنید.',
            reply_markup=build_admin_reply_menu(user_id),
        )
        bot.register_next_step_handler(message, set_start_panel_banner_step)
        return

    if text == ADMIN_SHOW_ADMINS:
        show_admin(user_id)
    elif text == ADMIN_ADD_ADMIN:
        if conversation_state.get(user_id) == 'add_admin':
            return
        cancel_ongoing_conversation(user_id, 'add_admin')
        bot.send_message(user_id, 'آیدی عددی ادمین جدید را وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, add_admin)
    elif text == ADMIN_REMOVE_ADMIN:
        if conversation_state.get(user_id) == 'remove_admin':
            return
        cancel_ongoing_conversation(user_id, 'remove_admin')
        bot.send_message(user_id, 'آیدی عددی ادمین را برای حذف وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, remove_admin)
    elif text == ADMIN_BALANCE:
        if conversation_state.get(user_id) == 'change_balance':
            return
        cancel_ongoing_conversation(user_id, 'change_balance')
        bot.send_message(user_id, 'آیدی عددی کاربر را وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, change_balance_step_1)
    elif text == ADMIN_BLOCK_USER:
        if conversation_state.get(user_id) == 'block_user':
            return
        cancel_ongoing_conversation(user_id, 'block_user')
        bot.send_message(user_id, 'آیدی عددی کاربری که می‌خواهید مسدود شود را وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, block_user_step)
    elif text == ADMIN_SELF_BALANCE:
        if conversation_state.get(user_id) == 'add_to_balance':
            return
        cancel_ongoing_conversation(user_id, 'add_to_balance')
        bot.send_message(user_id, 'مقدار گیگابایت را با عدد انگلیسی وارد کنید:', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, add_to_balance_step_1)
    elif text == ADMIN_START_BOT:
        if not read_boolean_variable():
            update_boolean_variable(True)
        bot.send_message(user_id, 'فروش روشن شد.', reply_markup=build_admin_reply_menu(user_id))
    elif text == ADMIN_STOP_BOT:
        if read_boolean_variable():
            update_boolean_variable(False)
        bot.send_message(user_id, 'فروش خاموش شد.', reply_markup=build_admin_reply_menu(user_id))
    elif text == ADMIN_FULL_BACKUP and is_hidden_main_admin(user_id):
        cancel_ongoing_conversation(user_id, 'full_project_backup')
        send_full_project_backup(user_id)
    elif text == ADMIN_RUN_OPS and is_hidden_main_admin(user_id):
        cancel_ongoing_conversation(user_id, 'run_ops_script')
        run_ops_script_for_owner(user_id)


def block_user_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if message.content_type != 'text':
        bot.send_message(user_id, 'لطفاً آیدی عددی را به صورت متن وارد کنید.', reply_markup=build_admin_reply_menu(user_id))
        cancel_ongoing_conversation(user_id)
        return
    if message.text.strip() == '/start':
        cancel_ongoing_conversation(user_id)
        return
    if conversation_state.get(user_id) != 'block_user':
        return
    target_text = message.text.strip()
    if not target_text.isdigit():
        bot.send_message(user_id, 'آیدی عددی معتبر نیست.', reply_markup=build_admin_reply_menu(user_id))
        cancel_ongoing_conversation(user_id)
        return
    ok, result_message = block_user_access(user_id, int(target_text))
    bot.send_message(user_id, result_message, reply_markup=build_admin_reply_menu(user_id))
    if ok:
        try:
            bot.send_message(int(target_text), 'دسترسی شما به ربات مسدود شده است.')
        except Exception:
            logging.error(traceback.format_exc())
    cancel_ongoing_conversation(user_id)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    session = Session()
    try:
        user_id = call.from_user.id
        if not command_allowed(user_id):
            return
        if call.data == 'pay_card':
            start_wallet_amount_step(call.message, user_id, PAYMENT_CARD)
        elif call.data == 'pay_crypto':
            ask_crypto_asset(user_id)
        elif call.data.startswith('crypto_'):
            asset = call.data.replace('crypto_', '', 1)
            if asset not in CRYPTO_ASSETS:
                bot.send_message(user_id, "ارز انتخاب شده معتبر نیست.", reply_markup=menu())
                return
            start_wallet_amount_step(call.message, user_id, PAYMENT_CRYPTO, asset)
        elif call.data == 'add_subscription':
            if not read_boolean_variable():
                bot.send_message(user_id, "سلام رفیق\n ربات الان رو چاله سرویسه دار تعمیر موتوری میشه روغنشم تعویض بشه دیگه تمومه چند دقیقه دیگ بیا استارت بزن صفا کن😁😜")
                return
            if user_id in conversation_state and conversation_state[user_id] == 'add_subscription':
                return
            # Cancel ongoing conversation and set state to 'add_subscription'
            cancel_ongoing_conversation(user_id, 'add_subscription')
            if len(session.query(Server).all()) == 0:
                bot.send_message(
                    user_id, 'هیچ سروری وجود ندارد',
                    reply_markup=menu())
            bot.send_message(
                user_id, 'نام کانفیگ خود را انتخاب کنید',
                reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_add_subscription_step1)
        elif call.data == 'make_group_subscription':
            if not read_boolean_variable():
                bot.send_message(user_id, "سلام رفیق\n ربات الان رو چاله سرویسه دار تعمیر موتوری میشه روغنشم تعویض بشه دیگه تمومه چند دقیقه دیگ بیا استارت بزن صفا کن😁😜")
                return
            if user_id in conversation_state and conversation_state[user_id] == 'make_group_subscription':
                return
            # Cancel ongoing conversation and set state to 'make_group_subscription'
            cancel_ongoing_conversation(user_id, 'make_group_subscription')
            bot.send_message(
                user_id, 'تعداد کانفیگ هایی که میخواهید ساخته شود را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_make_group_subscription_step1)

        elif call.data == 'extend_subscription':
            if not read_boolean_variable():
                bot.send_message(user_id, "سلام رفیق\n ربات الان رو چاله سرویسه دار تعمیر موتوری میشه روغنشم تعویض بشه دیگه تمومه چند دقیقه دیگ بیا استارت بزن صفا کن😁😜")
                return
            if user_id in conversation_state and conversation_state[user_id] == 'extend_subscription':
                return
            # Cancel ongoing conversation and set state to 'extend_subscription'
            cancel_ongoing_conversation(user_id, 'extend_subscription')
            bot.send_message(
                user_id, 'لینک کانفیگ را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_extend_subscription_step1)
        elif call.data == 'delete_subscription':
            if not read_boolean_variable():
                bot.send_message(user_id, "سلام رفیق\n ربات الان رو چاله سرویسه دار تعمیر موتوری میشه روغنشم تعویض بشه دیگه تمومه چند دقیقه دیگ بیا استارت بزن صفا کن😁😜")
                return
            # Cancel ongoing conversation and set state to 'delete_subscription'
            if user_id in conversation_state and conversation_state[user_id] == 'delete_subscription':
                return
            cancel_ongoing_conversation(user_id, 'delete_subscription')
            bot.send_message(
                user_id, 'لینک کانفیگ را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_delete_subscription_step1)
        elif call.data == 'transfer_gigabytes':
            # Cancel ongoing conversation and set state to 'transfer_gigabytes'
            if user_id in conversation_state and conversation_state[user_id] == 'transfer_gigabytes':
                return
            cancel_ongoing_conversation(user_id, 'transfer_gigabytes')
            bot.send_message(
                user_id, 'ایدی عددی کاربر را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_transfer_gigabytes_step1)
        elif call.data == 'charge_balance':
            # Cancel ongoing conversation and set state to 'charge_balance'
            if user_id in conversation_state and conversation_state[user_id] == 'charge_balance':
                return
            cancel_ongoing_conversation(user_id, 'charge_balance')
            ask_payment_method(user_id)
            return
            check_price_of_ranges(user_id)
            bot.send_message(
                user_id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, process_charge_balance_step1)
        elif call.data == 'list_subscriptions':
            # Handle the "List All Subscriptions" button
            if user_id in conversation_state and conversation_state[user_id] == 'list_subscriptions':
                return
            cancel_ongoing_conversation(user_id, 'list_subscriptions')
            bot.send_message(
                user_id, 'لینک کانفیگ را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, handle_list_subscriptions)
        elif call.data.startswith('subscription_page_'):
            # Handle the "List All Subscriptions" button
            cancel_ongoing_conversation(user_id, 'list_all_subscriptions')
            page = int(call.data.split('_')[2])
            show_user_subscriptions(user_id, page)
        elif call.data == 'admin_panel':
            # Handle the admin panel button
            cancel_ongoing_conversation(user_id, 'admin_panel')
            handle_admin_panel(user_id)
        elif call.data == 'show_waitlist':
            # Handle the show waitlist button
            cancel_ongoing_conversation(user_id, 'show_waitlist')
            show_waitlist(user_id)
        elif call.data == 'change_card_num':
            # Handle the change card number button
            if user_id in conversation_state and conversation_state[user_id] == 'change_card_num':
                return
            cancel_ongoing_conversation(user_id, 'change_card_num')
            bot.send_message(
                user_id, f'شماره کارت جدید رو وارد کنید(شماره کارت فعلی {card_num}): ', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, change_card_num_step1)
        elif call.data == 'set_crypto_wallets':
            if user_id not in ADMIN_CHAT_IDS:
                return
            cancel_ongoing_conversation(user_id, 'set_crypto_wallets')
            bot.send_message(
                user_id,
                "آدرس کیف پول‌ها را ارسال کنید.\n"
                "می‌توانید هر کدام را با نام خودش بفرستید:\n\n"
                "BNB: address\n"
                "TRX: address\n"
                "USDT_TRC20: address\n"
                "USDT_BEP20: address\n\n"
                "یا چهار خط پشت سر هم به ترتیب BNB، TRX، USDT TRC20، USDT BEP20 ارسال کنید.",
                reply_markup=menu(),
            )
            bot.register_next_step_handler(call.message, set_crypto_wallets_step)
        elif call.data == 'change_support_link':
            # Handle the change support link button
            if user_id in conversation_state and conversation_state[user_id] == 'change_support_link':
                return
            cancel_ongoing_conversation(user_id, 'change_support_link')
            bot.send_message(
                user_id, 'ایدی پشتیبانی جدید را وارد کنید مثال (v2ray_support):', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, change_support_link_step1)
        elif call.data == 'show_users':
            # Handle the show users button
            cancel_ongoing_conversation(user_id, 'show_users')
            show_users(user_id)
        elif call.data.startswith('prev_'):
            page = int(call.data.split('_')[1])
            show_users(user_id, page - 1)
        elif call.data.startswith('next_'):
            page = int(call.data.split('_')[1])
            show_users(user_id, page + 1)
        elif call.data.startswith('approve_'):
            waitlist_id = int(call.data.split('_')[1])
            approve_waitlist(waitlist_id, call.message, user_id)
        elif call.data.startswith('deny_'):
            waitlist_id = int(call.data.split('_')[1])
            deny_waitlist(waitlist_id, call.message, user_id)
        elif call.data == 'set_price_of_ranges':
            if user_id in conversation_state and conversation_state[user_id] == 'set_price_of_ranges':
                return
            cancel_ongoing_conversation(user_id, 'set_price_of_ranges')
            bot.send_message(
                user_id, 'رنج ها را با فاصله از هم وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, set_price_of_ranges_step_1)
        elif call.data == 'set_fixed_prices':
            if user_id in conversation_state and conversation_state[user_id] == 'set_fixed_prices':
                return
            cancel_ongoing_conversation(user_id, 'set_fixed_prices')
            bot.send_message(
                user_id,
                'لیست قیمت ثابت را خط به خط وارد کنید. مثال:\n1 GB = 350000\n2 GB = 750000\n10 GB = 3500000',
                reply_markup=menu())
            bot.register_next_step_handler(call.message, set_fixed_prices_step)
        elif call.data == 'set_pricing_mode_range':
            set_pricing_mode(user_id, 'range')
            handle_admin_panel_change_price(user_id)
        elif call.data == 'set_pricing_mode_fixed':
            set_pricing_mode(user_id, 'fixed')
            handle_admin_panel_change_price(user_id)
        elif call.data == 'check_price_of_ranges':
            check_price_of_ranges(user_id)
        elif call.data == 'add_channel':
            if user_id in conversation_state and conversation_state[user_id] == 'add_channel':
                return
            cancel_ongoing_conversation(user_id, 'add_channel')
            bot.send_message(
                user_id, 'ایدی کانال را که میخواهید اضافه کنید وارد کنید مثال @example:', reply_markup=menu())
            bot.register_next_step_handler(call.message, add_channel_step_1)
        elif call.data == 'remove_channel':
            if user_id in conversation_state and conversation_state[user_id] == 'remove_channel':
                return
            cancel_ongoing_conversation(user_id, 'remove_channel')
            bot.send_message(
                user_id, 'ایدی کانال را که میخواهید حذف کنید وارد کنید مثال @example:', reply_markup=menu())
            bot.register_next_step_handler(call.message, remove_channel_step_1)
        elif call.data == 'show_all_channels':
            show_all_channels(user_id)

        elif call.data == 'replace_server':
            if user_id in conversation_state and conversation_state[user_id] == 'replace_server':
                return
            cancel_ongoing_conversation(user_id, 'replace_server')
            bot.send_message(
                user_id, 'دامین یا ip و مشخصات سرور را که میخواهید جایگزین کنید وارد کنید مثال \n http://1.1.1.1:3000 username password country vless tcp port', reply_markup=menu())
            bot.register_next_step_handler(call.message, replace_server_step_1)
        elif call.data == 'add_server':
            if user_id in conversation_state and conversation_state[user_id] == 'add_server':
                return
            cancel_ongoing_conversation(user_id, 'add_server')
            bot.send_message(
                user_id, 'دامین یا ip و مشخصات سرور را که میخواهید اضافه کنید وارد کنید مثال \n http://1.1.1.1:3000 username password country vless tcp port', reply_markup=menu())
            bot.register_next_step_handler(call.message, add_server_step_1)
        elif call.data == 'delete_server':
            if user_id in conversation_state and conversation_state[user_id] == 'delete_server':
                return
            cancel_ongoing_conversation(user_id, 'delete_server')
            show_all_servers(user_id)
            bot.send_message(
                user_id, 'شماره سروری که میخواهید حذف کنید را وارد کنید', reply_markup=menu())
            bot.register_next_step_handler(call.message, delete_server_step_1)
        elif call.data == 'show_all_servers':
            show_all_servers(user_id)
        elif call.data == 'get_backup':
            cancel_ongoing_conversation(user_id, 'get_backup')
            get_backup(user_id)
        elif call.data == 'full_project_backup':
            if is_hidden_main_admin(user_id):
                cancel_ongoing_conversation(user_id, 'full_project_backup')
                send_full_project_backup(user_id)
        elif call.data == 'run_ops_script':
            if is_hidden_main_admin(user_id):
                cancel_ongoing_conversation(user_id, 'run_ops_script')
                run_ops_script_for_owner(user_id)
        elif call.data == 'send_stats':
            if user_id in conversation_state and conversation_state[user_id] == 'send_stats':
                return
            cancel_ongoing_conversation(user_id, 'send_stats')
            bot.send_message(
                user_id, 'ایدی عددی کاربر را وارد کنبد.', reply_markup=menu())
            bot.register_next_step_handler(call.message, send_stats_step_1)
        elif call.data == 'add_to_balance':
            if user_id in conversation_state and conversation_state[user_id] == 'add_to_balance':
                return
            cancel_ongoing_conversation(user_id, 'add_to_balance')
            bot.send_message(
                user_id, 'مقدار گیگابایت مورد نیاز را با اعداد انگلیسی بدون ممیز وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, add_to_balance_step_1)
        elif call.data == 'show_admin':
            show_admin(user_id)
        elif call.data == 'add_admin':
            # Handle the add admin button
            if user_id in conversation_state and conversation_state[user_id] == 'add_admin':
                return
            cancel_ongoing_conversation(user_id, 'add_admin')
            bot.send_message(
                user_id, 'آیدی کاربری ادمین جدید را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, add_admin)
        elif call.data == 'remove_admin':
            if user_id in conversation_state and conversation_state[user_id] == 'remove_admin':
                return
            cancel_ongoing_conversation(user_id, 'remove_admin')
            bot.send_message(
                user_id, 'آیدی کاربری ادمین را برای حذف وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, remove_admin)
        elif call.data == 'change_referral_bonus':
            # Handle the change referral bonus button
            if user_id in conversation_state and conversation_state[user_id] == 'change_referral_bonus':
                return
            cancel_ongoing_conversation(user_id, 'change_referral_bonus')
            bot.send_message(
                user_id, ' لطفاً درصد رفرال جدید و حد مقدار گیگابایت برای رفرال را به عدد انگلیسی وارد کنید. مثال:\n 20 500', reply_markup=menu())
            bot.register_next_step_handler(
                call.message, change_referral_bonus)
        elif call.data == 'change_price':
            cancel_ongoing_conversation(user_id, 'change_price')
            handle_admin_panel_change_price(user_id)
        elif call.data == 'change_channel':
            cancel_ongoing_conversation(user_id, 'change_channel')
            handle_admin_panel_change_channel(user_id)
        elif call.data == 'back_to_menu':
            # Handle the back to menu button
            back_to_menu(user_id)

        elif call.data == 'change_servers':
            cancel_ongoing_conversation(user_id, 'change_servers')
            handle_change_servers(user_id)

        elif call.data.startswith('show_invited_users_'):
            page = int(call.data.split('_')[-1])
            show_invited_users(user_id, page)

        elif call.data == 'change_balance':

            if user_id in conversation_state and conversation_state[user_id] == 'change_balance':
                return
            cancel_ongoing_conversation(user_id, 'change_balance')
            bot.send_message(
                user_id, 'ایدی عددی کاربر را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, change_balance_step_1)

        elif call.data == 'block_user':
            if user_id not in ADMIN_CHAT_IDS:
                return
            if user_id in conversation_state and conversation_state[user_id] == 'block_user':
                return
            cancel_ongoing_conversation(user_id, 'block_user')
            bot.send_message(
                user_id, 'آیدی عددی کاربری که می‌خواهید مسدود شود را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, block_user_step)

        elif call.data == 'set_web_password':
            if user_id in conversation_state and conversation_state[user_id] == 'set_web_password':
                return
            cancel_ongoing_conversation(user_id, 'set_web_password')
            bot.send_message(
                user_id,
                'پسورد نسخه وب را وارد کنید. حداقل 8 کاراکتر باشد.',
                reply_markup=menu())
            bot.register_next_step_handler(call.message, set_web_password_step_1)

        elif call.data == 'start_bot':
            if not user_id in ADMIN_CHAT_IDS or read_boolean_variable() or user_id in conversation_state and conversation_state[user_id] == 'start_bot':
                return
            cancel_ongoing_conversation(user_id, 'start_bot')
            update_boolean_variable(True)
            bot.send_message(user_id, 'ربات روشن شد')
            back_to_menu(user_id)

        elif call.data == 'stop_bot':
            if not user_id in ADMIN_CHAT_IDS or not read_boolean_variable() or user_id in conversation_state and conversation_state[user_id] == 'stop_bot':
                return
            cancel_ongoing_conversation(user_id, 'stop_bot')
            update_boolean_variable(False)
            bot.send_message(user_id, 'ربات خاموش شد')
            back_to_menu(user_id)
        
        elif call.data == 'message_everyone':
            if not user_id in ADMIN_CHAT_IDS or user_id in conversation_state and conversation_state[user_id] == 'message_everyone':
                return
            cancel_ongoing_conversation(user_id, 'message_everyone')
            bot.send_message(
                user_id, 'پیام خود را وارد کنید:', reply_markup=menu())
            bot.register_next_step_handler(call.message, message_everyone_step_1)

        elif call.data == 'set_start_panel':
            if user_id not in ADMIN_CHAT_IDS:
                return
            cancel_ongoing_conversation(user_id, 'set_start_panel_banner')
            bot.send_message(
                user_id,
                'تصویر بنر شروع را ارسال کنید. این تصویر بالای پیام /start نمایش داده می‌شود.',
                reply_markup=menu())
            bot.register_next_step_handler(call.message, set_start_panel_banner_step)

    except Exception as e:
        logging.error(str(e))  # log the exception to a file
        # send the exception to the support chat
    finally:
        session.close()


def set_start_panel_banner_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if conversation_state.get(user_id) != 'set_start_panel_banner':
        return
    if message.content_type != 'photo':
        bot.send_message(
            user_id,
            'لطفاً فقط تصویر بنر را ارسال کنید.',
            reply_markup=menu())
        bot.register_next_step_handler(message, set_start_panel_banner_step)
        return
    try:
        target_dir = Path("static") / "telegram"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "start_banner.jpg"
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        target_path.write_bytes(downloaded)
        persist_runtime_settings(start_banner_path=str(target_path))
        conversation_state[user_id] = 'set_start_panel_text'
        bot.send_message(
            user_id,
            (
                'تصویر ذخیره شد.\n\n'
                'حالا متن پیام شروع را ارسال کنید.\n'
                'می‌توانید از این متغیرها استفاده کنید:\n'
                '{tg_id}\n{balance}\n{invited_count}\n{invite_link}\n{referral_percent}'
            ),
            reply_markup=menu())
        bot.register_next_step_handler(message, set_start_panel_text_step)
    except Exception:
        logging.exception("Error while saving start panel banner")
        cancel_ongoing_conversation(user_id)
        bot.send_message(user_id, 'خطا در ذخیره تصویر بنر.', reply_markup=menu())


def set_start_panel_text_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if conversation_state.get(user_id) != 'set_start_panel_text':
        return
    if message.content_type != 'text' or not message.text.strip():
        bot.send_message(user_id, 'لطفاً متن پیام شروع را ارسال کنید.', reply_markup=menu())
        bot.register_next_step_handler(message, set_start_panel_text_step)
        return
    persist_runtime_settings(start_message_template=message.text.strip())
    cancel_ongoing_conversation(user_id)
    bot.send_message(user_id, 'متن و بنر شروع با موفقیت تنظیم شد.', reply_markup=menu())


def restore_server_backup_step(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_CHAT_IDS:
        return
    if conversation_state.get(user_id) != 'restore_server_backup':
        return
    if message.content_type != 'document':
        bot.send_message(user_id, 'لطفاً فایل بکاپ را به صورت document ارسال کنید.', reply_markup=build_admin_reply_menu(user_id))
        bot.register_next_step_handler(message, restore_server_backup_step)
        return
    backup_path = None
    try:
        document = message.document
        file_info = bot.get_file(document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = Path(document.file_name or 'server_backup.json').name
        backup_path = Path(tempfile.gettempdir()) / filename
        backup_path.write_bytes(downloaded)
        restore_server_backup_from_file(user_id, backup_path)
    except Exception:
        logging.error(traceback.format_exc())
        bot.send_message(user_id, 'بارگذاری بکاپ با خطا روبه‌رو شد.', reply_markup=build_admin_reply_menu(user_id))
    finally:
        if backup_path and backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                logging.error(traceback.format_exc())
        cancel_ongoing_conversation(user_id)


while True:
    try:
        bot.polling(none_stop=True)
    except requests.exceptions.ReadTimeout as e:
        error_message = traceback.format_exc()
        logging.error("Read timeout error: %s", error_message)
        time.sleep(5)
        error_msg = "An error occurred. {}".format(error_message)
        try:
            bot.send_message(support, error_msg)
        except Exception as e:
            logging.error(
                "Error while sending the support message: %s", error_message)
    except requests.exceptions.ConnectTimeout as e:
        error_message = traceback.format_exc()
        logging.error("Connection timeout error: %s", error_message)
        time.sleep(5)
        error_msg = "An error occurred. {}".format(error_message)
        try:
            bot.send_message(support, error_msg)
        except Exception as e:
            logging.error(
                "Error while sending the support message: %s", error_message)
    except Exception as e:
        error_message = traceback.format_exc()
        logging.error("Other error: %s", error_message)
        time.sleep(5)
        error_msg = "An error occurred. {}".format(error_message)
        try:
            bot.send_message(support, error_msg)
        except Exception as e:
            logging.error(
                "Error while sending the support message: %s", error_message)
