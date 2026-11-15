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


def make_page(body_text: str, wait_state: str | None) -> MagicMock:
    """wait_state — что вернёт ожидание выдачи в браузере: «ok», «empty» или None (таймаут).
    Ожидание теперь идёт внутри страницы (wait_for_function), поэтому мокаем его результат."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()

    async def wait_for_function(js, arg=None, timeout=None, **_):
        if js != search.WAIT_LISTING_JS:
            return MagicMock()  # догрузка карточек при прокрутке: считаем, что ничего не добавилось
        if wait_state is None:
            raise PWTimeout("timeout")
        handle = MagicMock()
        handle.json_value = AsyncMock(return_value=wait_state)
        return handle

    page.wait_for_function = AsyncMock(side_effect=wait_for_function)
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
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
    def run_load(self, page) -> str:
        # Таймаут ожидания в тестах не ждём: мок страницы отвечает сразу
        return asyncio.run(_load_listing(page, make_store("Mon Amie"), "https://x"))

    def test_cards_found_is_ok(self):
        page = make_page(body_text="", wait_state="ok")
        self.assertEqual(self.run_load(page), STATUS_OK)

    def test_wait_uses_card_timeout_and_store_selector(self):
        page = make_page(body_text="", wait_state="ok")
        self.run_load(page)
        js, kwargs = page.wait_for_function.await_args_list[0].args[0], page.wait_for_function.await_args_list[0].kwargs
        self.assertEqual(js, search.WAIT_LISTING_JS)
        self.assertEqual(kwargs["timeout"], search.CARD_WAIT_MS)
        self.assertEqual(page.wait_for_function.await_args_list[0].kwargs["arg"][0], ".card")

    def test_not_found_text_is_empty_and_not_retried(self):
        page = make_page(body_text="По запросу ничего не найдено", wait_state="empty")
        self.assertEqual(self.run_load(page), STATUS_EMPTY)
        self.assertEqual(page.goto.await_count, 1)

    def test_timeout_without_markers_is_unavailable(self):
        page = make_page(body_text="", wait_state=None)
        self.assertEqual(self.run_load(page), STATUS_UNAVAILABLE)
        self.assertEqual(page.goto.await_count, MAX_LOAD_ATTEMPTS)

    def test_site_block_page_is_unavailable(self):
        page = make_page(body_text="Страница недоступна", wait_state=None)
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
