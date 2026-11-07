"""French House: варианты объёма, приоритет введённого объёма, цена за 1 мл в карточке."""

import asyncio
import unittest
from unittest import mock

from playwright.async_api import async_playwright

from cosmetics_bot.src.scraping import details
from cosmetics_bot.src.scraping.details import detail_frenchhouse
from cosmetics_bot.src.ui.formatter import build_caption

# Упрощённая копия блока из страницы french-house.kz (60 ML выбран по умолчанию).
PRODUCT_HTML = """
<html><body>
<div class="goodParamsList volume">
  <div class="goodParam">
    <input type="radio" name="VOLUME" id="goodParam55" value="55" checked onchange="changeVolume(this);">
    <label class="goodParamVal" for="goodParam55">60 ML</label>
  </div>
  <div class="goodParam">
    <input type="radio" name="VOLUME" id="goodParam60" value="60" onchange="changeVolume(this);">
    <label class="goodParamVal" for="goodParam60">100 ML</label>
  </div>
</div>
<span class="cardCost new" id="price">92&nbsp;300 <span class="costPostfix"></span></span>
<span class="cardCost old" id="oldPrice"></span>
<script>
var PRICES = {goodParam55: '92 300 ₸', goodParam60: '120 000 ₸'};
function changeVolume(el) {
  document.getElementById('price').textContent = PRICES[el.id];
}
</script>
</body></html>
"""


def _run_detail(want_volume):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(PRODUCT_HTML)
                return await detail_frenchhouse(page, want_volume)
            finally:
                await browser.close()

    return asyncio.run(run())


class FrenchHouseVolumeTests(unittest.TestCase):
    def test_without_volume_takes_max_volume_price(self):
        with mock.patch.object(details, "MAX_VOLUME_ONLY", True):
            detail = _run_detail(None)
        self.assertEqual(detail["volume"], 100.0)
        self.assertEqual(detail["unit"], "мл")
        self.assertEqual(detail["price"], 120000)

    def test_entered_volume_has_priority(self):
        with mock.patch.object(details, "MAX_VOLUME_ONLY", True):
            detail = _run_detail(60.0)
        self.assertEqual(detail["volume"], 60.0)
        self.assertEqual(detail["price"], 92300)

    def test_without_max_mode_keeps_site_default_variant(self):
        with mock.patch.object(details, "MAX_VOLUME_ONLY", False):
            detail = _run_detail(None)
        self.assertEqual(detail["volume"], 60.0)
        self.assertEqual(detail["price"], 92300)


class PricePerMlCaptionTests(unittest.TestCase):
    def test_caption_shows_price_per_ml(self):
        caption = build_caption({
            "currency": "₸", "store": "Французский дом", "title": "YSL Y",
            "product_url": "https://french-house.kz/x", "price": 120000,
            "volume": 100.0, "unit": "мл",
        })
        self.assertIn("Цена за 1 мл", caption)
        self.assertIn("1 200", caption)

    def test_no_per_ml_line_without_volume(self):
        caption = build_caption({
            "currency": "₸", "store": "Французский дом", "title": "Крем",
            "product_url": "https://french-house.kz/x", "price": 5000,
        })
        self.assertNotIn("Цена за 1 мл", caption)


if __name__ == "__main__":
    unittest.main()
