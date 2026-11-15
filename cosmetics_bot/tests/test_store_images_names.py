"""Картинки в выдаче Code de Vie / Viled и официальные названия магазинов с поиском по прежним названиям.

Браузер не нужен: проверяем настройки магазинов и то, как открывается контекст выдачи.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.stores import STORES, find_store


class BlockImagesTests(unittest.TestCase):
    def test_cdv_and_viled_keep_images(self):
        by_name = {s.name: s for s in STORES}
        self.assertFalse(by_name["Code de Vie"].block_images)
        self.assertFalse(by_name["Viled"].block_images)

    def test_other_stores_still_block_images(self):
        for s in STORES:
            if s.name not in ("Code de Vie", "Viled"):
                self.assertTrue(s.block_images, s.name)

    def test_block_route_installed_only_when_enabled(self):
        def make_browser():
            ctx = MagicMock()
            ctx.route = AsyncMock()
            browser = MagicMock()
            browser.new_context = AsyncMock(return_value=ctx)
            return browser, ctx

        browser, ctx = make_browser()
        asyncio.run(search._open_context(browser, block_images=False))
        ctx.route.assert_not_awaited()

        browser, ctx = make_browser()
        asyncio.run(search._open_context(browser, block_images=True))
        ctx.route.assert_awaited_once()


class OfficialNamesTests(unittest.TestCase):
    def test_official_names(self):
        names = {s.name for s in STORES}
        self.assertIn("Code de Vie", names)
        self.assertIn("Goldapple", names)
        self.assertIn("French House", names)
        self.assertNotIn("Код де ви", names)
        self.assertNotIn("Золотое Яблоко", names)
        self.assertNotIn("Французский дом", names)

    def test_old_names_still_resolve(self):
        for old, new in (("Код де ви", "Code de Vie"),
                         ("Золотое Яблоко", "Goldapple"),
                         ("Французский дом", "French House")):
            store = find_store(old)
            self.assertIsNotNone(store, old)
            self.assertEqual(store.name, new)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(find_store("Unknown"))


if __name__ == "__main__":
    unittest.main()
