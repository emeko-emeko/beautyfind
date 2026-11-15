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

    def test_partial_unavailability_is_not_cached(self):
        # Частичная выдача (один магазин не ответил) не кэшируется: иначе сбой держится час
        search_cache_set("q", ["c1"], ["Shop 0"])
        self.assertIsNone(search_cache_get("q"))
        self.assertIsNone(search.search_cache_get_stale("q"))

    def test_complete_result_is_cached_with_empty_unavailable(self):
        search_cache_set("q", ["c1"], [])
        self.assertEqual(search_cache_get("q"), (["c1"], []))

    def test_entry_expires_after_ttl(self):
        search_cache_set("q", ["c1"], [])
        with patch.object(search, "SEARCH_CACHE_TTL", -1):
            self.assertIsNone(search_cache_get("q"))


class SearchCacheBoundsTests(unittest.TestCase):
    def setUp(self):
        search._search_cache.clear()
        self.stores = [make_store(f"Shop {i}") for i in range(3)]
        self.patch_stores = patch("cosmetics_bot.src.scraping.stores.STORES", self.stores)
        self.patch_stores.start()

    def tearDown(self):
        self.patch_stores.stop()
        search._search_cache.clear()

    def test_size_is_capped_and_oldest_evicted(self):
        with patch.object(search, "SEARCH_CACHE_MAX", 5):
            for i in range(8):
                search_cache_set(f"q{i}", [i], [])
            self.assertEqual(len(search._search_cache), 5)
            self.assertIsNone(search_cache_get("q0"))
            self.assertIsNotNone(search_cache_get("q7"))

    def test_recently_read_entry_survives_eviction(self):
        with patch.object(search, "SEARCH_CACHE_MAX", 3):
            search_cache_set("a", [1], [])
            search_cache_set("b", [2], [])
            search_cache_set("c", [3], [])
            search_cache_get("a")          # «a» стала самой свежей
            search_cache_set("d", [4], [])  # вытесняется «b»
            self.assertIsNotNone(search_cache_get("a"))
            self.assertIsNone(search_cache_get("b"))

    def test_expired_entries_are_purged_on_set(self):
        import time
        # Просроченная запись: другой запрос её не трогает, но set должен удалить её сам
        search._search_cache["old"] = (time.monotonic() - search.SEARCH_CACHE_STALE - 10, [0], [])
        search_cache_set("new", [1], [])
        self.assertNotIn("old", search._search_cache)
        self.assertIn("new", search._search_cache)


class SearchCacheFreshnessTests(unittest.TestCase):
    def setUp(self):
        search._search_cache.clear()
        self.stores = [make_store(f"Shop {i}") for i in range(3)]
        self.patch_stores = patch("cosmetics_bot.src.scraping.stores.STORES", self.stores)
        self.patch_stores.start()

    def tearDown(self):
        self.patch_stores.stop()
        search._search_cache.clear()

    def _age(self, query, seconds):
        import time
        key = search._cache_key(query)
        cands, unavailable = [1], []
        search._search_cache[key] = (time.monotonic() - seconds, cands, unavailable)

    def test_defaults_are_one_hour_fresh_and_six_hours_stale(self):
        self.assertEqual(search.SEARCH_CACHE_TTL, 60 * 60)
        self.assertEqual(search.SEARCH_CACHE_STALE, 6 * 60 * 60)
        self.assertEqual(search.SEARCH_CACHE_MAX, 1000)

    def test_entry_older_than_ttl_is_stale_not_fresh(self):
        self._age("q", 2 * 60 * 60)
        self.assertIsNone(search_cache_get("q"))
        self.assertEqual(search.search_cache_get_stale("q"), ([1], []))

    def test_entry_older_than_stale_limit_is_gone(self):
        self._age("q", 7 * 60 * 60)
        self.assertIsNone(search_cache_get("q"))
        self.assertIsNone(search.search_cache_get_stale("q"))

    def test_key_ignores_case_and_yo(self):
        search_cache_set("Крём  для рук", ["c1"], [])
        self.assertEqual(search_cache_get("крем для рук"), (["c1"], []))

    def test_refresh_stores_new_result_and_clears_flag(self):
        async def fake_collect(browser, query, groups):
            return ["new"], []

        with patch.object(search, "collect_all", fake_collect), \
             patch("cosmetics_bot.src.scraping.stores.browser_ctx", _fake_browser):
            asyncio.run(search._refresh("Крем", []))
        self.assertEqual(search_cache_get("крем"), (["new"], []))
        self.assertNotIn(search._cache_key("Крем"), search._refreshing)

    def test_repeated_schedule_starts_one_refresh(self):
        calls = []

        async def fake_collect(browser, query, groups):
            calls.append(query)
            await asyncio.sleep(0.01)
            return ["new"], []

        async def main():
            with patch.object(search, "collect_all", fake_collect), \
                 patch("cosmetics_bot.src.scraping.stores.browser_ctx", _fake_browser):
                search.schedule_refresh("Крем", [])
                search.schedule_refresh("крем", [])
                await asyncio.sleep(0.05)

        asyncio.run(main())
        self.assertEqual(len(calls), 1)


def _cand(store, name="Крем"):
    from cosmetics_bot.src.core.models import Candidate
    from cosmetics_bot.src.core.utils import make_hay
    return Candidate(
        store=store, brand="Бренд", name=name, type_="тип", label=name, url=f"{store.base_url}/p",
        image="img", rating=4.5, reviews=12, list_price=1000, price_prefix="", pos=0,
        ratio=0.75, list_price_native=None, restricted=False, hay=make_hay(name, "Бренд"),
    )


class SearchCacheDbTests(unittest.TestCase):
    """Кэш в Postgres. Сама база не нужна: функции db подменены."""

    def setUp(self):
        import time  # noqa: F401
        search._search_cache.clear()
        self.store = make_store("Shop 0")
        self.patch_stores = patch("cosmetics_bot.src.scraping.stores.STORES", [self.store])
        self.patch_stores.start()
        self.patch_db = patch.object(search, "SEARCH_CACHE_DB", True)
        self.patch_db.start()

    def tearDown(self):
        self.patch_db.stop()
        self.patch_stores.stop()
        search._search_cache.clear()

    def test_payload_round_trip_keeps_candidate(self):
        cand = _cand(self.store)
        back = search._from_payload(search._to_payload([cand]))
        self.assertEqual(back[0].name, cand.name)
        self.assertEqual(back[0].url, cand.url)
        self.assertEqual(back[0].ratio, cand.ratio)
        self.assertEqual(back[0].hay, cand.hay)
        self.assertIs(back[0].store, self.store)

    def test_fresh_row_in_db_is_returned_and_kept_in_memory(self):
        import time
        payload = search._to_payload([_cand(self.store)])
        row = {"saved_at": time.time() - 60, "payload": payload, "unavailable": []}
        with patch.object(db, "search_cache_load", return_value=row):
            got = search_cache_get("Крем")
        self.assertEqual(got[0][0].name, "Крем")
        self.assertIn("крем", search._search_cache)

    def test_row_older_than_stale_limit_is_miss(self):
        import time
        payload = search._to_payload([_cand(self.store)])
        row = {"saved_at": time.time() - search.SEARCH_CACHE_STALE - 10, "payload": payload, "unavailable": []}
        with patch.object(db, "search_cache_load", return_value=row):
            self.assertIsNone(search.search_cache_get_stale("Крем"))

    def test_row_with_unknown_store_is_miss(self):
        import time
        payload = search._to_payload([_cand(self.store)])
        payload[0]["store"] = "Удалённый магазин"
        row = {"saved_at": time.time() - 60, "payload": payload, "unavailable": []}
        with patch.object(db, "search_cache_load", return_value=row):
            self.assertIsNone(search_cache_get("Крем"))

    def test_db_read_error_is_just_a_miss(self):
        with patch.object(db, "search_cache_load", side_effect=RuntimeError("база недоступна")):
            self.assertIsNone(search_cache_get("Крем"))

    def test_set_writes_to_db_and_purges_old_rows(self):
        save = MagicMock()
        purge = MagicMock()
        with patch.object(db, "search_cache_save", save), patch.object(db, "search_cache_purge", purge):
            search_cache_set("Крем", [_cand(self.store)], [])
        self.assertEqual(save.call_args.args[0], "крем")
        self.assertEqual(purge.call_count, 1)

    def test_db_write_error_keeps_memory_cache(self):
        with patch.object(db, "search_cache_save", side_effect=RuntimeError("база недоступна")), \
             patch.object(db, "search_cache_purge"):
            search_cache_set("Крем", [_cand(self.store)], [])  # не должно упасть
        self.assertEqual(search_cache_get("Крем")[0][0].name, "Крем")

    def test_db_not_used_when_disabled(self):
        load = MagicMock(return_value=None)
        with patch.object(search, "SEARCH_CACHE_DB", False), patch.object(db, "search_cache_load", load):
            self.assertIsNone(search_cache_get("Крем"))
        load.assert_not_called()


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
