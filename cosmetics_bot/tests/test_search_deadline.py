"""Бюджет поиска (запись 035): дедлайн collect_all с доснятием в фоне и отказ от повтора при 403.

Браузер не нужен: list_store и страница подменены.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cosmetics_bot.src.core.models import Store
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.search import (
    MAX_LOAD_ATTEMPTS,
    STATUS_BLOCKED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    _load_listing,
    collect_all,
)


def make_store(name: str) -> Store:
    return Store(
        name=name,
        base_url="https://example.test",
        search_url="https://example.test/search/?q={query}",
        card=".card",
        brand=".brand",
        name_sel=".name",
        price=".price",
        images=[],
        link="a",
        detail="monamie",
        detail_ready=".ready",
    )


def _fc(url: str):
    """Фиктивный кандидат: collect_all объединяет выдачу по url."""
    from types import SimpleNamespace
    return SimpleNamespace(url=url)


class DeadlineTests(unittest.TestCase):
    def test_returns_done_stores_at_deadline_and_completes_cache_in_background(self):
        fast, slow = make_store("Fast"), make_store("Slow")

        async def fake(browser, store, query, groups):
            if store is slow:
                await asyncio.sleep(0.3)
                return STATUS_OK, [_fc("cand-slow")]
            return STATUS_OK, [_fc("cand-fast")]

        async def scenario():
            with patch.object(search, "list_store", side_effect=fake), \
                 patch.object(search, "search_cache_set") as cache_set:
                cands, unavailable = await collect_all(
                    MagicMock(), "крем", [], deadline=0.1
                )
                # К сроку: быстрый магазин в выдаче, медленный — «не ответил»
                self.assertEqual([c.url for c in cands], ["cand-fast"])
                self.assertEqual(unavailable, ["Slow"])
                # Пока медленный не закончил, полная выдача в кэш не попадает
                cache_set.assert_not_called()
                # Медленный магазин опрашивается по двум написаниям: 2 × 0.3 с
                await asyncio.sleep(1.0)
                # После доснятия полная выдача попала в кэш (без недоступных)
                cache_set.assert_called_once()
                args = cache_set.call_args.args
                self.assertEqual(args[0], "крем")
                self.assertEqual(sorted(c.url for c in args[1]), ["cand-fast", "cand-slow"])
                self.assertEqual(args[2], [])

        with patch("cosmetics_bot.src.scraping.stores.STORES", [fast, slow]):
            asyncio.run(scenario())

    def test_all_done_before_deadline_returns_everything(self):
        a, b = make_store("A"), make_store("B")

        async def fake(browser, store, query, groups):
            return STATUS_OK, [_fc(store.name)]

        with patch("cosmetics_bot.src.scraping.stores.STORES", [a, b]), \
             patch.object(search, "list_store", side_effect=fake):
            cands, unavailable = asyncio.run(collect_all(MagicMock(), "крем", [], deadline=5))
        self.assertEqual(sorted(c.url for c in cands), ["A", "B"])
        self.assertEqual(unavailable, [])

    def test_no_deadline_waits_for_all(self):
        a = make_store("A")

        async def fake(browser, store, query, groups):
            await asyncio.sleep(0.2)
            return STATUS_OK, [_fc("x")]

        with patch("cosmetics_bot.src.scraping.stores.STORES", [a]), \
             patch.object(search, "list_store", side_effect=fake):
            cands, unavailable = asyncio.run(collect_all(MagicMock(), "крем", [], deadline=None))
        self.assertEqual([c.url for c in cands], ["x"])
        self.assertEqual(unavailable, [])


class Forbidden403Tests(unittest.TestCase):
    def test_403_is_not_retried(self):
        page = MagicMock()
        page.goto = AsyncMock(return_value=MagicMock(status=403))
        page.title = AsyncMock(return_value="")
        page.wait_for_timeout = AsyncMock()
        page.wait_for_function = AsyncMock(side_effect=search.PWTimeout("timeout"))
        locator = MagicMock()
        locator.count = AsyncMock(return_value=0)
        locator.inner_text = AsyncMock(return_value="")
        page.locator = MagicMock(return_value=locator)

        status = asyncio.run(_load_listing(page, make_store("Золотое Яблоко"), "https://x"))
        self.assertEqual(status, STATUS_BLOCKED)
        self.assertEqual(page.goto.await_count, 1)
        self.assertLess(1, MAX_LOAD_ATTEMPTS)  # без 403 повтор по-прежнему есть


class SharedTabLimitTests(unittest.TestCase):
    def test_two_concurrent_collections_share_one_tab_limit(self):
        # Запись 041: фон и обычный поиск вместе не открывают больше SEARCH_CONCURRENCY вкладок
        stores = [make_store(f"Shop {i}") for i in range(6)]
        running = 0
        peak = 0

        async def fake(browser, store, query, groups):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            return STATUS_OK, []

        async def main():
            with patch.object(search, "list_store", side_effect=fake):
                await asyncio.gather(
                    collect_all(MagicMock(), "крем", [], deadline=None),
                    collect_all(MagicMock(), "помада", [], deadline=None),
                )

        with patch("cosmetics_bot.src.scraping.stores.STORES", stores):
            asyncio.run(main())
        self.assertLessEqual(peak, search.SEARCH_CONCURRENCY)
        self.assertEqual(peak, search.SEARCH_CONCURRENCY)


class SingleFlightTests(unittest.TestCase):
    def test_same_query_twice_at_once_scans_stores_once(self):
        # Запись 043: второй одинаковый запрос ждёт идущий сбор и не открывает свои вкладки
        stores = [make_store("A"), make_store("B")]
        calls = []

        async def fake(browser, store, query, groups):
            calls.append(store.name)
            await asyncio.sleep(0.05)
            # 5 карточек: оба написания всё равно запускаются параллельно (EME-7, пункт 3)
            return STATUS_OK, [_fc(f"{store.name}-{i}") for i in range(5)]

        async def main():
            with patch.object(search, "list_store", side_effect=fake):
                return await asyncio.gather(
                    search.collect_shared(MagicMock(), "крем", []),
                    search.collect_shared(MagicMock(), "крем", []),
                )

        with patch("cosmetics_bot.src.scraping.stores.STORES", stores):
            first, second = asyncio.run(main())
        # Два написания «крем» (кириллица и латиница) на каждый магазин: по одному вызову на написание
        self.assertEqual(sorted(calls), ["A", "A", "B", "B"])
        self.assertEqual(sorted(c.url for c in first[0]), sorted(c.url for c in second[0]))
        self.assertEqual(len(first[0]), 10)


class ConstantsTests(unittest.TestCase):
    def test_budget_and_waits(self):
        self.assertEqual(search.SEARCH_DEADLINE_S, 30)
        self.assertEqual(search.CARD_WAIT_MS, 6_000)
        self.assertEqual(search.GOTO_TIMEOUT_MS, 10_000)


if __name__ == "__main__":
    unittest.main()
