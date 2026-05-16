from config import *
import time
import logging

logging.basicConfig(filename='cronjob.log', level=logging.INFO)


while True:
    try:
        check_subscriptions()
    except Exception as e:
        logging.error("subscription check failed", exc_info=True)
        try:
            bot.send_message(support, f"{e}")
        except Exception:
            logging.error("support notification failed", exc_info=True)
    time.sleep(30)
