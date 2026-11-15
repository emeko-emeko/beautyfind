"""Отслеживание цен: подписка, отмена, проверка и уведомления.

Тесты подписок идут в Postgres (строка подключения из .env, DATABASE_URL).
Таблица создаётся как TEMP: она видна только этой сессии и затеняет public.watches,
поэтому боевые данные не затрагиваются. Без DATABASE_URL тесты подписок пропускаются.
"""

import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from cosmetics_bot.src.core import db
from cosmetics_bot.src.telegram import watcher

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(ROOT, ".env"))
DATABASE_URL = os.environ.get("DATABASE_URL")

TEMP_WATCHES_DDL = """
CREATE TEMP TABLE watches (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id bigint,
    product_url text,
    title text,
    initial_price integer,
    last_price integer,
    created_at double precision,
    last_check double precision,
    volume double precision
)
"""


class _Shared:
    """Отдаёт одно соединение; закрывать его должен сам тест, а не db.py."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


@unittest.skipUnless(DATABASE_URL, "нет DATABASE_URL в .env")
class DbWatchTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
        self.conn.execute(TEMP_WATCHES_DDL)
        # Страховка: unqualified watches должна указывать на временную таблицу, а не на public
        schema = self.conn.execute(
            "SELECT n.nspname AS s FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.oid = to_regclass('watches')"
        ).fetchone()["s"]
        self.assertTrue(schema.startswith("pg_temp"), f"watches не временная, схема: {schema}")
        self.patch = patch.object(db, "get_connection", lambda: _Shared(self.conn))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.conn.close()

    def test_resubscribe_replaces_and_keeps_one_row(self):
        db.add_watch(1, "https://monamie.kz/p", "Tit", 100, volume=50)
        db.add_watch(1, "https://monamie.kz/p", "Tit", 120, volume=50)
        rows = db.get_watches(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["initial_price"], 120)
        self.assertEqual(rows[0]["volume"], 50)

    def test_other_chats_are_separate(self):
        db.add_watch(1, "https://monamie.kz/p", "Tit", 100)
        db.add_watch(2, "https://monamie.kz/p", "Tit", 100)
        self.assertEqual(len(db.get_watches(1)), 1)
        self.assertEqual(len(db.get_watches(2)), 1)

    def test_remove_only_own_watch(self):
        db.add_watch(1, "https://monamie.kz/p", "Tit", 100)
        wid = db.get_watches(1)[0]["id"]
        self.assertFalse(db.remove_watch(wid, chat_id=2))  # чужой чат
        self.assertTrue(db.remove_watch(wid, chat_id=1))
        self.assertEqual(db.get_watches(1), [])


class SupportTests(unittest.TestCase):
    def test_supported_only_with_detail_handler(self):
        self.assertTrue(watcher.is_watch_supported("Mon Amie"))
        self.assertTrue(watcher.is_watch_supported("Yves Rocher"))
        self.assertTrue(watcher.is_watch_supported("Cult Beauty"))
        self.assertTrue(watcher.is_watch_supported("Space NK"))
        self.assertTrue(watcher.is_watch_supported("Viled"))
        self.assertTrue(watcher.is_watch_supported("Код де ви"))
        self.assertFalse(watcher.is_watch_supported("Unknown"))


class CheckWatchesTests(unittest.TestCase):
    def _run(self, watches, price_by_url):
        saved = []
        bot = MagicMock()
        bot.send_message = AsyncMock()

        async def fake_fetch(store, w, browser, context):
            p = price_by_url.get(w["product_url"])
            return None if p is None else {"price": p}

        # Браузер не нужен: _fetch_price подменён, контекст тоже
        @asynccontextmanager
        async def fake_browser():
            yield MagicMock()

        fake_context = MagicMock()
        fake_context.close = AsyncMock()

        with patch.object(watcher, "get_watches_for_monitor", lambda: watches), \
             patch.object(watcher, "update_watch_price", lambda wid, price: saved.append((wid, price))), \
             patch.object(watcher, "_fetch_price", fake_fetch), \
             patch.object(watcher, "browser_ctx", fake_browser), \
             patch.object(watcher, "open_detail_context", AsyncMock(return_value=fake_context)), \
             patch.object(watcher, "PAUSE_BETWEEN", 0):
            asyncio.run(watcher.check_watches(bot))
        return bot, saved

    def test_price_drop_notifies_and_saves_new_price(self):
        watches = [{"id": 1, "chat_id": 7, "product_url": "https://www.monamie.kz/p1", "title": "Духи",
                    "last_price": 10000, "volume": 50}]
        bot, saved = self._run(watches, {"https://www.monamie.kz/p1": 8000})
        bot.send_message.assert_awaited_once()
        args, kwargs = bot.send_message.call_args
        self.assertEqual(args[0], 7)
        self.assertIn("снизилась", args[1])
        self.assertEqual(saved, [(1, 8000)])

    def test_unchanged_price_no_notification(self):
        watches = [{"id": 1, "chat_id": 7, "product_url": "https://www.monamie.kz/p1", "title": "Духи",
                    "last_price": 10000, "volume": None}]
        bot, saved = self._run(watches, {"https://www.monamie.kz/p1": 10000})
        bot.send_message.assert_not_awaited()
        self.assertEqual(saved, [(1, 10000)])

    def test_failed_fetch_keeps_old_price(self):
        watches = [{"id": 1, "chat_id": 7, "product_url": "https://www.monamie.kz/p1", "title": "Духи",
                    "last_price": 10000, "volume": None}]
        bot, saved = self._run(watches, {})
        bot.send_message.assert_not_awaited()
        self.assertEqual(saved, [(1, 10000)])

    def test_store_without_detail_handler_is_skipped_without_fetch(self):
        watches = [{"id": 1, "chat_id": 7, "product_url": "https://unknown-shop.example/item/1", "title": "X",
                    "last_price": 5000, "volume": None}]
        bot, saved = self._run(watches, {"https://unknown-shop.example/item/1": 1})
        bot.send_message.assert_not_awaited()
        self.assertEqual(saved, [(1, 5000)])


if __name__ == "__main__":
    unittest.main()
