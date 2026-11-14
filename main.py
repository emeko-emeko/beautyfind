"""Main entry point for the Cosmetics Telegram Bot."""

import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from cosmetics_bot.src.telegram.bot import dp
from cosmetics_bot.src.telegram.watcher import watch_loop
import platform

if platform.system() == "Windows":
    import msvcrt
else:
    # Альтернатива для Linux или заглушка
    msvcrt = None
import sys

import tempfile

LOCK_PATH = os.path.join(tempfile.gettempdir(), "cosmetics_bot.lock")
_lock_file = open(LOCK_PATH, "w")
try:
    msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    sys.exit("Бот уже запущен: второй экземпляр не стартует")




load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main():
    if not TOKEN:
        logging.error("Не найден TELEGRAM_TOKEN в переменных окружения (.env)! Задайте его.")
        return

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    logging.info("Telegram-бот запущен и готов к работе...")
    asyncio.create_task(watch_loop(bot))
    await dp.start_polling(bot)






if __name__ == "__main__":
    asyncio.run(main())
