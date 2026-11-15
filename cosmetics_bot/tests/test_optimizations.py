"""Оптимизации из журнала (запись 024, пункты 2–6): кэш выдачи, семафор магазинов,
группировка проверок цен по магазину, пул соединений.

Поведение: cosmetics_bot/src/scraping/search.py (кэш, collect_all), watcher.py (check_watches),
db.py (_get_pool). Отдельных тестов на них до этого не было (статусы выдачи — test_unavailable.py).
Запуск: python -m unittest cosmetics_bot.tests.test_optimizations
"""

import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from cosmetics_bot.src.core import db
from cosmetics_bot.src.core.models import Store
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.search import (
    SEARCH_CONCURRENCY,
    STATUS_OK,
    collect_all,
    search_cache_get,
    search_cache_set,
)
from cosmetics_bot.src.telegram import watcher


def make_store(name: str, detail: str | None = "monamie") -> Store:
    return Store(
        name=name,
        base_url=f"https://{name.replace(' ', '').lower()}.test",
        search_url="https://example.test/search/?q={query}",
        card=".card",
        brand=".brand",
        name_sel=".name",
        price=".price",
        images=[],
        link="a",
        detail=detail,
        detail_ready=".ready",
    )


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        search._search_cache.clear()
        self.stores = [make_store(f"Shop {i}") for i in range(3)]
        self.patch_stores = patch("cosmetics_bot.src.scraping.stores.STORES", self.stores)
        self.patch_stores.start()

    def tearDown(self):
        self.patch_stores.stop()
        search._search_cache.clear()

    def test_saved_result_is_returned(self):
        search_cache_set("le labo", ["c1"], [])
        self.assertEqual(search_cache_get("le labo"), (["c1"], []))

    def test_query_whitespace_is_normalized(self):
        search_cache_set("le   labo ", ["c1"], [])
        self.assertEqual(search_cache_get("le labo"), (["c1"], []))

    def test_unknown_query_misses(self):
        self.assertIsNone(search_cache_get("nothing"))

    def test_all_stores_unavailable_is_not_cached(self):
        search_cache_set("q", [], [s.name for s in self.stores])
        self.assertIsNone(search_cache_get("q"))

    def test_partial_unavailability_is_cached_with_names(self):
        search_cache_set("q", ["c1"], ["Shop 0"])
        self.assertEqual(search_cache_get("q"), (["c1"], ["Shop 0"]))

    def test_entry_expires_after_ttl(self):
        search_cache_set("q", ["c1"], [])
        with patch.object(search, "SEARCH_CACHE_TTL", -1):
            self.assertIsNone(search_cache_get("q"))


class ConcurrencyTests(unittest.TestCase):
    def test_no_more_than_semaphore_limit_run_at_once(self):
        stores = [make_store(f"Shop {i}") for i in range(8)]
        running = 0
        peak = 0

        async def fake_list_store(browser, store, query, groups):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return STATUS_OK, []

        with patch("cosmetics_bot.src.scraping.stores.STORES", stores), \
             patch.object(search, "list_store", side_effect=fake_list_store):
            asyncio.run(collect_all(MagicMock(), "крем", []))

        self.assertEqual(peak, SEARCH_CONCURRENCY)

    def test_queued_store_is_not_timed_out_while_waiting(self):
        # STORE_TIMEOUT считается только для работающего магазина: при 8 магазинах и лимите 3
        # ожидание в очереди не должно превращаться в «недоступен»
        stores = [make_store(f"Shop {i}") for i in range(8)]

        async def fake_list_store(browser, store, query, groups):
            await asyncio.sleep(0.01)
            return STATUS_OK, []

        with patch("cosmetics_bot.src.scraping.stores.STORES", stores), \
             patch.object(search, "list_store", side_effect=fake_list_store), \
             patch.object(search, "STORE_TIMEOUT", 0.5):
            _, unavailable = asyncio.run(collect_all(MagicMock(), "крем", []))
        self.assertEqual(unavailable, [])


def _watches(store, n):
    return [
        {"id": i, "chat_id": 1, "product_url": f"{store.base_url}/p{i}", "title": "t",
         "last_price": 100, "volume": None}
        for i in range(n)
    ]


@asynccontextmanager
async def _fake_browser():
    yield MagicMock()


async def _fake_open(browser):
    ctx = MagicMock()
    ctx.close = AsyncMock()
    return ctx


class WatcherGroupingTests(unittest.TestCase):
    def test_watches_of_one_store_share_one_browser_context(self):
        store = make_store("Mon Amie")
        opened = []
        saved = []

        async def counting_open(browser):
            opened.append(1)
            return await _fake_open(browser)

        async def fake_fetch(st, w, browser, context):
            return {"price": 100}

        with patch.object(watcher, "get_watches_for_monitor", lambda: _watches(store, 3)), \
             patch.object(watcher, "store_for_url", lambda url: store), \
             patch.object(watcher, "browser_ctx", _fake_browser), \
             patch.object(watcher, "open_detail_context", counting_open), \
             patch.object(watcher, "_fetch_price", fake_fetch), \
             patch.object(watcher, "update_watch_price", lambda wid, p: saved.append(wid)), \
             patch.object(watcher, "PAUSE_BETWEEN", 0):
            asyncio.run(watcher.check_watches(MagicMock()))

        self.assertEqual(len(opened), 1)
        self.assertEqual(sorted(saved), [0, 1, 2])

    def test_failure_mid_group_keeps_already_checked_prices(self):
        # Регрессия: сбой при записи второго товара выходит из _check_one наружу.
        # Уже проверенный первый товар не должен откатиться к старой цене (100).
        store = make_store("Mon Amie")
        saved = {}
        writes = {"n": 0}

        def flaky_update(wid, price):
            writes["n"] += 1
            if writes["n"] == 2:
                raise RuntimeError("база недоступна")
            saved[wid] = price

        async def fake_fetch(st, w, browser, context):
            return {"price": 80}

        bot = MagicMock()
        bot.send_message = AsyncMock()  # падение цены шлёт уведомление
        with patch.object(watcher, "get_watches_for_monitor", lambda: _watches(store, 3)), \
             patch.object(watcher, "store_for_url", lambda url: store), \
             patch.object(watcher, "browser_ctx", _fake_browser), \
             patch.object(watcher, "open_detail_context", _fake_open), \
             patch.object(watcher, "_fetch_price", fake_fetch), \
             patch.object(watcher, "update_watch_price", flaky_update), \
             patch.object(watcher, "PAUSE_BETWEEN", 0):
            asyncio.run(watcher.check_watches(bot))

        # Первый товар проверен до сбоя — остаётся 80. Второй и третий не обработаны — возвращаем 100.
        self.assertEqual(saved, {0: 80, 1: 100, 2: 100})


class PoolTests(unittest.TestCase):
    def test_missing_database_url_raises_clear_error(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(db, "_pool", None):
            with self.assertRaises(RuntimeError) as cm:
                db.get_connection()
        self.assertIn("DATABASE_URL", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
