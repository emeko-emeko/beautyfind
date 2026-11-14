"""Общая загрузка .env до сбора тестов: DATABASE_URL нужна импорту bot.py (init_db)."""

import os

from dotenv import load_dotenv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(ROOT, ".env"))
