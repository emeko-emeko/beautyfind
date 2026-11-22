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

    def test_light_block_installed_for_image_stores(self):
        ctx = MagicMock()
        ctx.route = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=ctx)
        asyncio.run(search._open_context(browser, block_images=False))
        ctx.route.assert_awaited_once()
        self.assertIs(ctx.route.await_args.args[1], search._block_light)

    def test_block_route_installed_only_when_enabled(self):
        def make_browser():
            ctx = MagicMock()
            ctx.route = AsyncMock()
            browser = MagicMock()
            browser.new_context = AsyncMock(return_value=ctx)
            return browser, ctx

        browser, ctx = make_browser()
        asyncio.run(search._open_context(browser, block_images=False))
        self.assertIs(ctx.route.await_args.args[1], search._block_light)

        browser, ctx = make_browser()
        asyncio.run(search._open_context(browser, block_images=True))
        ctx.route.assert_awaited_once()


class OfficialNamesTests(unittest.TestCase):
    def test_official_names(self):
        names = {s.name for s in STORES}
        self.assertIn("Code de Vie", names)
        self.assertIn("Золотое Яблоко", names)
        self.assertIn("Французский дом", names)
        self.assertNotIn("Код де ви", names)

    def test_old_name_still_resolves(self):
        store = find_store("Код де ви")
        self.assertIsNotNone(store)
        self.assertEqual(store.name, "Code de Vie")

    def test_current_names_resolve(self):
        for name in ("Code de Vie", "Золотое Яблоко", "Французский дом"):
            self.assertIsNotNone(find_store(name), name)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(find_store("Unknown"))


if __name__ == "__main__":
    unittest.main()
