"""Yves Rocher: регистрация магазина и разбор цены без старой цены."""

import asyncio
import unittest

from playwright.async_api import async_playwright

from cosmetics_bot.src.scraping.details import DETAIL_HANDLERS, detail_yvesrocher
from cosmetics_bot.src.scraping.search import EXTRACT_JS, SEL_FIELDS
from cosmetics_bot.src.scraping.stores import STORES

CARD_HTML = """
<div data-product-card-id="2497"><div class="SimpleProductCard_simpleProduct__-2lRp">
  <a href="/product/krem-30-ml-42850-2497">
    <div class="SimpleProductCard_simpleProductImage__9biFN"><img src="https://img.yves-rocher.kz/a.webp"></div>
  </a>
  <div class="SimpleProductCard_simpleProductTitle__IFJx3">Крем для рук, 30 мл</div>
  <div class="PriceDisplay_container__wSaeP">
    <div class="Typography_price__OhpkA PriceDisplay_price__0Tk-a">1&nbsp;791&nbsp;₸<span class="Typography_text50__YVPn8 PriceDisplay_oldPrice__dcnJm">1&nbsp;990&nbsp;₸</span></div>
  </div>
</div></div>
"""

PRODUCT_HTML = """
<html><body>
<h1>Увлажняющий Крем для Рук «Сочный Личи», 30 мл</h1>
<div class="ProductCardSidebar_priceDisplay__nWKfm">
  <div class="PriceDisplay_container__wSaeP">
    <div class="Typography_h1__zlhk- PriceDisplay_price__0Tk-a">1&nbsp;791&nbsp;₸<span class="PriceDisplay_oldPrice__dcnJm">1&nbsp;990&nbsp;₸</span></div>
  </div>
</div>
</body></html>
"""


class YvesRocherStoreTests(unittest.TestCase):
    def test_store_registered_with_detail_handler(self):
        store = next(s for s in STORES if s.name == "Yves Rocher")
        self.assertIn(store.detail, DETAIL_HANDLERS)
        self.assertTrue(store.price_own_text)
        self.assertIn("price_own_text", SEL_FIELDS)

    def test_card_price_excludes_old_price(self):
        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_content(f"<main>{CARD_HTML}</main>")
                    store = next(s for s in STORES if s.name == "Yves Rocher")
                    sel = {f: getattr(store, f, None) for f in SEL_FIELDS}
                    items = await page.evaluate(
                        EXTRACT_JS,
                        {"cardSel": store.card, "sel": sel, "base": store.base_url, "limit": 5},
                    )
                    return items
                finally:
                    await browser.close()

        items = asyncio.run(run())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["price"], "1 791 ₸")
        self.assertEqual(items[0]["url"], "https://www.yves-rocher.kz/product/krem-30-ml-42850-2497")

    def test_detail_price_and_volume(self):
        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_content(PRODUCT_HTML)
                    return await detail_yvesrocher(page, None)
                finally:
                    await browser.close()

        detail = asyncio.run(run())
        self.assertEqual(detail["price"], 1791)
        self.assertEqual(detail["old_price"], 1990)
        self.assertEqual(detail["volume"], 30.0)
        self.assertEqual(detail["unit"], "мл")


if __name__ == "__main__":
    unittest.main()
