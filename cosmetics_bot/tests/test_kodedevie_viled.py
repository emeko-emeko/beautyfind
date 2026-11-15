"""Страницы товара Код де ви и Viled: разбор цены и объёма на сохранённом HTML.

HTML лежит в корне репозитория (code de vie.txt, viled.txt). Файлы не в git,
поэтому при их отсутствии тесты пропускаются.
"""

import asyncio
import os
import unittest

from playwright.async_api import async_playwright

from cosmetics_bot.src.scraping.details import DETAIL_HANDLERS, detail_kodedevie, detail_viled
from cosmetics_bot.src.scraping.stores import STORES

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KODEDEVIE_HTML = os.path.join(ROOT, "code de vie.txt")
VILED_HTML = os.path.join(ROOT, "viled.txt")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _run_detail(handler, html):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html)
                return await handler(page, None)
            finally:
                await browser.close()

    return asyncio.run(run())


class StoreWiringTests(unittest.TestCase):
    def test_both_stores_use_handlers(self):
        by_name = {s.name: s for s in STORES}
        self.assertEqual(by_name["Code de Vie"].detail, "kodedevie")
        self.assertEqual(by_name["Viled"].detail, "viled")
        self.assertIs(DETAIL_HANDLERS["kodedevie"], detail_kodedevie)
        self.assertIs(DETAIL_HANDLERS["viled"], detail_viled)


# Файл code de vie.txt повреждён: в нём нет символов < > и ", разметки как HTML не осталось.
# Поэтому тест строит минимальную разметку по классам и значениям из этого файла
# (PA3B1q_current, PA3B1q_old, _6QkyVq_price). Проверка на настоящем HTML — после пересохранения страницы.
KODEDEVIE_FIXTURE = """<!doctype html><html><body>
<h1>Карандаш для губ LoveNude Kiss Shaper</h1>
<div class="PA3B1q_root _6QkyVq_price">
  <span class="MuiTypography-root PA3B1q_current">13&nbsp;860 ₸</span>
  <span class="MuiTypography-root PA3B1q_old">19&nbsp;800 ₸</span>
</div>
</body></html>"""


class KodeDeViDetailTests(unittest.TestCase):
    def test_sale_and_old_price_on_reconstructed_markup(self):
        detail = _run_detail(detail_kodedevie, KODEDEVIE_FIXTURE)
        self.assertEqual(detail["price"], 13860)
        self.assertEqual(detail["old_price"], 19800)
        self.assertIsNone(detail["volume"])


@unittest.skipUnless(os.path.exists(VILED_HTML), "нет файла viled.txt")
class ViledDetailTests(unittest.TestCase):
    def test_price_and_active_volume(self):
        detail = _run_detail(detail_viled, _read(VILED_HTML))
        self.assertEqual(detail["price"], 63000)
        self.assertIsNone(detail["old_price"])
        self.assertEqual(detail["volume"], 30.0)
        self.assertEqual(detail["unit"], "мл")


if __name__ == "__main__":
    unittest.main()
