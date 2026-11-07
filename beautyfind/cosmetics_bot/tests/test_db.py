"""db.py: импорт time и отсутствие дублей (задача №5). База — в памяти, data/bot.db не трогаем."""

import sqlite3
import time
import unittest
from unittest.mock import patch

from cosmetics_bot.src.core import db


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE watches (id INTEGER PRIMARY KEY, chat_id INTEGER, product_url TEXT, "
        "title TEXT, initial_price INTEGER, last_price INTEGER, created_at REAL, last_check REAL)"
    )
    return conn


class WatchesTests(unittest.TestCase):
    def test_get_watches_for_monitor_does_not_fail_and_returns_stale_rows(self):
        conn = make_conn()
        now = time.time()
        conn.execute("INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check) "
                     "VALUES (1, 'u1', 't1', 100, 100, ?, ?)", (now, now - 3600))  # старая проверка
        conn.execute("INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check) "
                     "VALUES (1, 'u2', 't2', 100, 100, ?, ?)", (now, now))          # свежая проверка
        conn.commit()
        with patch.object(db, "get_connection", lambda: conn):
            rows = db.get_watches_for_monitor()  # раньше тут был NameError: time
        self.assertEqual([r["product_url"] for r in rows], ["u1"])

    def test_get_all_watches_and_update_price(self):
        conn = make_conn()
        conn.execute("INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check) "
                     "VALUES (1, 'u1', 't1', 100, 100, 0, 0)")
        conn.commit()
        with patch.object(db, "get_connection", lambda: conn):
            self.assertEqual(len(db.get_all_watches()), 1)
            db.update_watch_price(1, 90)
            self.assertEqual(conn.execute("SELECT last_price FROM watches WHERE id=1").fetchone()[0], 90)


if __name__ == "__main__":
    unittest.main()
