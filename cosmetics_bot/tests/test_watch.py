"""Отслеживание цен: подписка, отмена, проверка и уведомления. База — в памяти."""

import asyncio
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cosmetics_bot.src.core import db
from cosmetics_bot.src.telegram import watcher


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, product_url TEXT, "
        "title TEXT, initial_price INTEGER, last_price INTEGER, created_at REAL, last_check REAL, volume REAL)"
    )
    return conn


class DbWatchTests(unittest.TestCase):
    def test_resubscribe_replaces_and_keeps_one_row(self):
        conn = make_conn()
        with patch.object(db, "get_connection", lambda: conn):
            db.add_watch(1, "https://monamie.kz/p", "Tit", 100, volume=50)
            db.add_watch(1, "https://monamie.kz/p", "Tit", 120, volume=50)
            rows = db.get_watches(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["initial_price"], 120)
        self.assertEqual(rows[0]["volume"], 50)

    def test_other_chats_are_separate(self):
        conn = make_conn()
        with patch.object(db, "get_connection", lambda: conn):
            db.add_watch(1, "https://monamie.kz/p", "Tit", 100)
            db.add_watch(2, "https://monamie.kz/p", "Tit", 100)
            self.assertEqual(len(db.get_watches(1)), 1)
            self.assertEqual(len(db.get_watches(2)), 1)

    def test_remove_only_own_watch(self):
        conn = make_conn()
        with patch.object(db, "get_connection", lambda: conn):
            db.add_watch(1, "https://monamie.kz/p", "Tit", 100)
            wid = db.get_watches(1)[0]["id"]
            self.assertFalse(db.remove_watch(wid, chat_id=2))  # чужой чат
            self.assertTrue(db.remove_watch(wid, chat_id=1))
            self.assertEqual(db.get_watches(1), [])


class SupportTests(unittest.TestCase):
    def test_supported_only_with_detail_handler(self):
        self.assertTrue(watcher.is_watch_supported("Mon Amie"))
        self.assertTrue(watcher.is_watch_supported("Yves Rocher"))
        self.assertFalse(watcher.is_watch_supported("Cult Beauty"))
        self.assertFalse(watcher.is_watch_supported("Код де ви"))
        self.assertFalse(watcher.is_watch_supported("Unknown"))


class CheckWatchesTests(unittest.TestCase):
    def _run(self, watches, price_by_url):
        saved = []
        bot = MagicMock()
        bot.send_message = AsyncMock()

        async def fake_fetch(store, w):
            p = price_by_url.get(w["product_url"])
            return None if p is None else {"price": p}

        with patch.object(watcher, "get_watches_for_monitor", lambda: watches), \
             patch.object(watcher, "update_watch_price", lambda wid, price: saved.append((wid, price))), \
             patch.object(watcher, "_fetch_price", fake_fetch), \
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
        watches = [{"id": 1, "chat_id": 7, "product_url": "https://www.cultbeauty.com/p/x/", "title": "X",
                    "last_price": 5000, "volume": None}]
        bot, saved = self._run(watches, {"https://www.cultbeauty.com/p/x/": 1})
        bot.send_message.assert_not_awaited()
        self.assertEqual(saved, [(1, 5000)])


if __name__ == "__main__":
    unittest.main()
