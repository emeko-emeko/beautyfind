"""Статусы магазинов и строка «недоступен» (задача №4).

Запуск из папки www:  venv\\Scripts\\python -m pytest cosmetics_bot/tests -v
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import TimeoutError as PWTimeout

from cosmetics_bot.src.core.models import Store
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.search import (
    MAX_LOAD_ATTEMPTS,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    _load_listing,
    collect_all,
)
from cosmetics_bot.src.ui.formatter import unavailable_line


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


def make_page(body_text: str, card_found: bool, cards_after_polls: int = 0) -> MagicMock:
    """card_found=True — карточки есть сразу; иначе они появятся после cards_after_polls опросов
    (если cards_after_polls=0 и card_found=False — карточек не будет совсем)."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    if card_found:
        counts = [1]
    elif cards_after_polls:
        counts = [0] * cards_after_polls + [1]
    else:
        counts = [0]
    locator = MagicMock()
    locator.count = AsyncMock(side_effect=counts + [counts[-1]] * 10_000)
    locator.inner_text = AsyncMock(return_value=body_text)
    page.locator = MagicMock(return_value=locator)
    return page


class UnavailableLineTests(unittest.TestCase):
    def test_empty_list_gives_empty_string(self):
        self.assertEqual(unavailable_line([]), "")

    def test_one_store(self):
        self.assertEqual(unavailable_line(["Mon Amie"]), "⚠️ Mon Amie: недоступен")

    def test_several_stores_one_per_line(self):
        self.assertEqual(
            unavailable_line(["Mon Amie", "Золотое Яблоко"]),
            "⚠️ Mon Amie: недоступен\n⚠️ Золотое Яблоко: недоступен",
        )

    def test_name_is_html_escaped(self):
        self.assertEqual(unavailable_line(["A<b>"]), "⚠️ A&lt;b&gt;: недоступен")


class LoadListingStatusTests(unittest.TestCase):
    def run_load(self, page, card_wait_ms: int = 30) -> str:
        # Короткий таймаут, чтобы тесты не ждали реальные 12 секунд
        with patch.object(search, "CARD_WAIT_MS", card_wait_ms), \
             patch.object(search, "POLL_MS", 1):
            return asyncio.run(_load_listing(page, make_store("Mon Amie"), "https://x"))

    def test_cards_found_is_ok(self):
        page = make_page(body_text="", card_found=True)
        self.assertEqual(self.run_load(page), STATUS_OK)

    def test_cards_appearing_later_are_ok(self):
        page = make_page(body_text="", card_found=False, cards_after_polls=3)
        self.assertEqual(self.run_load(page, card_wait_ms=10_000), STATUS_OK)

    def test_not_found_text_is_empty_and_not_retried(self):
        page = make_page(body_text="По запросу ничего не найдено", card_found=False)
        self.assertEqual(self.run_load(page), STATUS_EMPTY)
        self.assertEqual(page.goto.await_count, 1)

    def test_empty_result_returns_without_waiting_full_card_timeout(self):
        import time
        page = make_page(body_text="По запросу ничего не найдено", card_found=False)
        t = time.perf_counter()
        # Таймаут 10 с: раньше ждали бы его целиком; теперь признак пустой выдачи возвращает сразу
        self.assertEqual(self.run_load(page, card_wait_ms=10_000), STATUS_EMPTY)
        self.assertLess(time.perf_counter() - t, 2.0)

    def test_timeout_without_markers_is_unavailable(self):
        page = make_page(body_text="", card_found=False)
        self.assertEqual(self.run_load(page), STATUS_UNAVAILABLE)
        self.assertEqual(page.goto.await_count, MAX_LOAD_ATTEMPTS)

    def test_site_block_page_is_unavailable(self):
        page = make_page(body_text="Страница недоступна", card_found=False)
        self.assertEqual(self.run_load(page), STATUS_UNAVAILABLE)


class CollectAllStatusTests(unittest.TestCase):
    def run_collect(self, fake_list_store, stores):
        with patch("cosmetics_bot.src.scraping.stores.STORES", stores), \
             patch.object(search, "list_store", side_effect=fake_list_store):
            return asyncio.run(collect_all(MagicMock(), "крем", []))

    def test_unavailable_store_is_reported_and_others_kept(self):
        a, b = make_store("Mon Amie"), make_store("Золотое Яблоко")

        async def fake(browser, store, query, groups):
            if store is a:
                return STATUS_UNAVAILABLE, []
            return STATUS_OK, ["cand-b"]

        cands, unavailable = self.run_collect(fake, [a, b])
        self.assertEqual(cands, ["cand-b"])
        self.assertEqual(unavailable, ["Mon Amie"])

    def test_empty_store_is_not_reported_as_unavailable(self):
        a, b = make_store("Mon Amie"), make_store("Золотое Яблоко")

        async def fake(browser, store, query, groups):
            return (STATUS_EMPTY, []) if store is a else (STATUS_OK, ["cand-b"])

        cands, unavailable = self.run_collect(fake, [a, b])
        self.assertEqual(cands, ["cand-b"])
        self.assertEqual(unavailable, [])

    def test_exception_in_store_is_unavailable(self):
        a, b = make_store("Mon Amie"), make_store("Золотое Яблоко")

        async def fake(browser, store, query, groups):
            if store is a:
                raise RuntimeError("boom")
            return STATUS_OK, []

        _, unavailable = self.run_collect(fake, [a, b])
        self.assertEqual(unavailable, ["Mon Amie"])

    def test_timeout_is_unavailable(self):
        a = make_store("Mon Amie")

        async def slow(browser, store, query, groups):
            await asyncio.sleep(1)
            return STATUS_OK, []

        with patch.object(search, "STORE_TIMEOUT", 0.01):
            _, unavailable = self.run_collect(slow, [a])
        self.assertEqual(unavailable, ["Mon Amie"])


if __name__ == "__main__":
    unittest.main()
