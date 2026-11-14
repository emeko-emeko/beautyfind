"""Код де ви, Viled, Space NK, Cult Beauty: разбор карточек выдачи и пересчёт евро в тенге.

Запуск из папки с проектом: python -m pytest cosmetics_bot/tests/test_new_stores.py -v
"""

import asyncio
import unittest

from playwright.async_api import async_playwright

from cosmetics_bot.src.core.utils import EUR_TO_KZT
from cosmetics_bot.src.scraping.search import EXTRACT_JS, SEL_FIELDS, _build_candidate
from cosmetics_bot.src.scraping.stores import PENDING_STORES, STORES
from cosmetics_bot.src.ui.formatter import price_text

CDV_HTML = """
<div class="_6hPivq_root MuiBox-root mui-0"><a class="_6hPivq_link" href="/item/429384">
  <div class="_6hPivq_imageContainer"><img alt="image-429384" src="https://cdn-prod-check.viled.kz/item/a.jpg"></div>
  <div class="_6hPivq_descriptionContainer">
    <div class="_6hPivq_description"><h6 class="_6hPivq_brand">BY TERRY</h6></div>
    <div class="_6hPivq_description _6hPivq_title"><p>Молочный эликсир-спрей Matcha Mist Elixir</p></div>
    <div class="_6hPivq_priceBlock"><p class="pot8WW_currentPrice _6hPivq_currentPriceText">45&nbsp;540 ₸</p></div>
  </div></a>
  <div class="_6hPivq_actionButton"><button aria-label="Открыть действия с товаром"></button></div>
</div>
"""

VILED_HTML = """
<div class="hRF60W_root"><a class="hRF60W_link" href="/item/428815">
  <div class="hRF60W_imageContainer"><img alt="image-428815" src="https://cdn-prod-check.viled.kz/item/b.jpg"></div>
  <div class="hRF60W_descriptionContainer">
    <div class="hRF60W_description"><h6 class="hRF60W_brand">IENKI IENKI</h6></div>
    <div class="hRF60W_description hRF60W_title"><p>Стеганый пуховик</p></div>
    <div class="hRF60W_priceBlock"><p class="hRF60W_currentPriceText">920&nbsp;000 ₸</p></div>
  </div></a>
</div>
"""

SPACENK_HTML = """
<div class="product"><div class="product-tile">
  <div class="image-container"><a class="link" href="/uk/accessories/mini-travel-bag-pink-MUK200065905.html">
    <img class="tile-image d-block" alt="Mini Travel Bag Pink" src="https://www.spacenk.com/img/UK200065905_NK.jpg?sw=292&amp;sh=292"></a></div>
  <div class="tile-body">
    <h5 class="mb-1">Space NK</h5>
    <div class="pdp-link mb-1"><a class="link text-primary" href="/uk/accessories/mini-travel-bag-pink-MUK200065905.html">Mini Travel Bag Pink</a></div>
    <h5><div class="price"><span class="d-inline"><span class="sales d-inline-block">
      <span class="value" content="8900.0" data-price="8900.0">KZT 8,900</span>
    </span></span></div></h5>
  </div>
</div></div>
"""

CULT_HTML = """
<product-card-wrapper class="product-card z-0" data-e2e="search_list-item-0">
  <div class="group"><a href="/p/charlotte-tilbury-hot-lips-gift-set/18158217/" class="product-item">
    <figure><picture><img src="https://www.cultbeauty.com/images?url=x.jpg" alt="Charlotte Tilbury Hot Lips Gift Set (Worth €138)" class="item-image"></picture></figure>
  </a>
  <div class="product-item-text"><div class="product-data">
    <a class="product-item-title" href="/p/charlotte-tilbury-hot-lips-gift-set/18158217/">Charlotte Tilbury Hot Lips Gift Set (Worth €138)</a>
    <div class="product-item-price flex flex-col">
      <p class="price override-price-style text-sm mt-1"><span>111.00€</span></p>
    </div>
  </div></div></div>
</product-card-wrapper>
"""


def _store(name):
    return next(s for s in STORES + PENDING_STORES if s.name == name)


def _extract(html, store):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(f"<main>{html}</main>")
                sel = {f: getattr(store, f, None) for f in SEL_FIELDS}
                return await page.evaluate(
                    EXTRACT_JS,
                    {"cardSel": store.card, "sel": sel, "base": store.base_url, "limit": 5},
                )
            finally:
                await browser.close()

    return asyncio.run(run())


class NewStoresParsingTests(unittest.TestCase):
    def test_all_four_defined(self):
        names = {s.name for s in STORES + PENDING_STORES}
        self.assertTrue({"Код де ви", "Viled", "Space NK", "Cult Beauty"} <= names)

    def test_connected_stores_have_search_url(self):
        for name in ("Код де ви", "Viled"):
            store = next(s for s in STORES if s.name == name)
            self.assertIn("{query}", store.search_url)

    def test_cdv_card(self):
        items = _extract(CDV_HTML, _store("Код де ви"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://cdv.kz/item/429384")
        self.assertEqual(items[0]["brand"], "BY TERRY")
        self.assertEqual(items[0]["name"], "Молочный эликсир-спрей Matcha Mist Elixir")
        self.assertEqual(items[0]["price"], "45 540 ₸")

    def test_viled_card(self):
        items = _extract(VILED_HTML, _store("Viled"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://viled.kz/item/428815")
        self.assertEqual(items[0]["brand"], "IENKI IENKI")

    def test_spacenk_card(self):
        items = _extract(SPACENK_HTML, _store("Space NK"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["brand"], "Space NK")
        self.assertEqual(items[0]["name"], "Mini Travel Bag Pink")
        self.assertEqual(items[0]["price"], "KZT 8,900")

    def test_cult_beauty_card(self):
        items = _extract(CULT_HTML, _store("Cult Beauty"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.cultbeauty.com/p/charlotte-tilbury-hot-lips-gift-set/18158217/")
        self.assertEqual(items[0]["price"], "111.00€")


RESTRICTED_HTML = """
<div class="product"><div class="product-tile">
  <div class="image-container"><a class="link" href="/uk/brands/y/ysl-beauty/make-me-blush-MUK200067597.html">
    <img class="tile-image" alt="Make Me Blush Powder Set" src="https://www.spacenk.com/img.jpg"></a></div>
  <div class="tile-body unavailable">
    <h5 class="mb-1">YSL BEAUTY</h5>
    <div class="pdp-link mb-1"><a class="link" href="/uk/brands/y/ysl-beauty/make-me-blush-MUK200067597.html">Make Me Blush Powder Set</a></div>
    <h5><div class="price"><span class="sales"><span class="value">KZT 35,050</span></span></div></h5>
    <div class="col-12 pl-0"><h5 class="unavailable-notice">Unable to ship to Kazakhstan.</h5></div>
  </div>
</div></div>
"""

PLAIN_HTML = """
<div class="product"><div class="product-tile">
  <div class="image-container"><a class="link" href="/uk/accessories/bag-MUK200065905.html">
    <img class="tile-image" alt="Bag" src="https://www.spacenk.com/bag.jpg"></a></div>
  <div class="tile-body">
    <h5 class="mb-1">Space NK</h5>
    <div class="pdp-link mb-1"><a class="link" href="/uk/accessories/bag-MUK200065905.html">Mini Travel Bag Pink</a></div>
    <h5><div class="price"><span class="sales"><span class="value">KZT 8,900</span></span></div></h5>
  </div>
</div></div>
"""


class DeliveryRestrictionTests(unittest.TestCase):
    def test_restricted_card_is_flagged(self):
        items = _extract(RESTRICTED_HTML, _store("Space NK"))
        self.assertTrue(items[0]["restricted"])

    def test_normal_card_is_not_flagged(self):
        items = _extract(PLAIN_HTML, _store("Space NK"))
        self.assertFalse(items[0]["restricted"])

    def test_restricted_note_in_caption(self):
        from cosmetics_bot.src.ui.formatter import build_caption
        base = {
            "store": "Space NK", "title": "YSL BEAUTY Make Me Blush", "subtitle": "",
            "rating": None, "reviews": 0, "volume": None, "unit": "", "currency": "₸",
            "price": 35050, "old_price": None, "loyalty_price": None,
            "price_prefix": "", "product_url": "https://www.spacenk.com/x", "price_native": None,
        }
        self.assertIn("Доставка в Казахстан невозможна", build_caption({**base, "restricted": True}))
        self.assertNotIn("Доставка в Казахстан невозможна", build_caption({**base, "restricted": False}))


class CurrencyTests(unittest.TestCase):
    def test_eur_converted_to_tenge_and_native_kept(self):
        store = _store("Cult Beauty")
        raw = {
            "url": "https://www.cultbeauty.com/p/x/", "name": "Test", "brand": "", "type": "",
            "label": "Test", "image": "", "rating": "", "reviews": "", "price": "111.00€",
        }
        cand = _build_candidate(store, raw, [], 0)
        self.assertEqual(cand.list_price, round(111 * EUR_TO_KZT))
        self.assertEqual(cand.list_price_native, 111.0)

    def test_price_text_shows_both_currencies(self):
        text = price_text(56599, 111.0, "€")
        self.assertIn("56 599 ₸", text)
        self.assertIn("(≈ 111 €)", text)

    def test_tenge_store_has_no_native_price(self):
        self.assertEqual(price_text(45540, None, ""), "45 540 ₸")


if __name__ == "__main__":
    unittest.main()
