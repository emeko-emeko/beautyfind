"""db.py: тесты на Postgres.

Запускаются только если задана TEST_DATABASE_URL. Работают в отдельной схеме test_db_tests,
рабочие таблицы (DATABASE_URL) не трогают. Без TEST_DATABASE_URL тесты пропускаются.
"""

import os
import time
import unittest
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row

from cosmetics_bot.src.core import db

TEST_URL = os.environ.get("TEST_DATABASE_URL")
SCHEMA = "test_db_tests"


def _connect():
    # search_path уводит все запросы в тестовую схему
    return psycopg.connect(TEST_URL, row_factory=dict_row, options=f"-c search_path={SCHEMA}")


@unittest.skipUnless(TEST_URL, "нужна переменная TEST_DATABASE_URL")
class WatchesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(TEST_URL) as c:
            c.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
            c.execute(f"CREATE SCHEMA {SCHEMA}")
            c.execute(f"""
                CREATE TABLE {SCHEMA}.watches (
                    id bigint generated always as identity primary key,
                    chat_id bigint, product_url text, title text,
                    initial_price integer, last_price integer,
                    created_at double precision, last_check double precision)
            """)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(TEST_URL) as c:
            c.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")

    def setUp(self):
        with _connect() as c:
            c.execute("DELETE FROM watches")

    def _insert(self, url, last_check):
        with _connect() as c:
            c.execute("INSERT INTO watches (chat_id, product_url, title, initial_price, last_price, created_at, last_check) "
                      "VALUES (1, %s, 't', 100, 100, %s, %s)", (url, time.time(), last_check))

    def test_get_watches_for_monitor_returns_only_stale_rows(self):
        now = time.time()
        self._insert("u1", now - 3600)  # старая проверка
        self._insert("u2", now)         # свежая проверка
        with patch.object(db, "get_connection", _connect):
            rows = db.get_watches_for_monitor()
        self.assertEqual([r["product_url"] for r in rows], ["u1"])

    def test_get_all_watches_and_update_price(self):
        self._insert("u1", 0)
        with patch.object(db, "get_connection", _connect):
            self.assertEqual(len(db.get_all_watches()), 1)
            wid = db.get_all_watches()[0]["id"]
            db.update_watch_price(wid, 90)
        with _connect() as c:
            self.assertEqual(c.execute("SELECT last_price FROM watches WHERE id = %s", (wid,)).fetchone()["last_price"], 90)


if __name__ == "__main__":
    unittest.main()
