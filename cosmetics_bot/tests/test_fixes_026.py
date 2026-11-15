"""Запись 026: пустая выдача по новым фразам, страница одного товара (Mon Amie), фото, которое Telegram не открыл."""
import asyncio
import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
from aiogram.types import BufferedInputFile
from playwright.async_api import async_playwright

from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.stores import STORES
from cosmetics_bot.src.telegram import bot


def _webp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 60)).save(buf, format="WEBP")
    return buf.getvalue()


class EmptyMarkersTests(unittest.TestCase):
    def test_new_empty_phrases_are_markers(self):
        self.assertIn("товаров не найдено", search.NOT_FOUND_MARKERS)  # Viled
        self.assertIn("couldn't find results", search.NOT_FOUND_MARKERS)  # Space NK


class JpegTests(unittest.TestCase):
    def test_webp_becomes_jpeg(self):
        data = bot._to_jpeg(_webp_bytes())
        self.assertTrue(data.startswith(b"\xff\xd8"))  # маркер JPEG


class SendCardFallbackTests(unittest.TestCase):
    def _message(self, photo_side_effect):
        msg = MagicMock()
        msg.answer_photo = AsyncMock(side_effect=photo_side_effect)
        msg.answer = AsyncMock(return_value="text-sent")
        return msg

    def test_retries_with_bytes_when_telegram_cannot_fetch_url(self):
        jpeg = bot._to_jpeg(_webp_bytes())
        msg = self._message([Exception("failed to get HTTP URL content"), "photo-sent"])
        with patch.object(bot, "fetch_image_jpeg", AsyncMock(return_value=jpeg)):
            res = asyncio.run(bot.send_card(msg, "caption", "https://example.test/a.webp"))
        self.assertEqual(res, "photo-sent")
        second = msg.answer_photo.await_args_list[1].kwargs["photo"]
        self.assertIsInstance(second, BufferedInputFile)
        msg.answer.assert_not_awaited()

    def test_falls_back_to_text_when_download_fails(self):
        msg = self._message([Exception("failed to get HTTP URL content")])
        with patch.object(bot, "fetch_image_jpeg", AsyncMock(return_value=None)):
            res = asyncio.run(bot.send_card(msg, "caption", "https://example.test/a.webp"))
        self.assertEqual(res, "text-sent")


class MonAmieProductPageTests(unittest.TestCase):
    """Сайт на кириллический запрос открывает страницу товара: разбор одной карточки."""

    HTML = """<html><body>
    <div class="product-detail__head"><div>L'ORÉAL PARIS</div>
      <div class="product-detail__head-subtitle">Telescopic Lift Extra Black</div></div>
    </body></html>"""

    def test_single_card_from_product_page(self):
        mon = next(s for s in STORES if s.name == "Mon Amie")

        async def run():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_content(self.HTML)
                    return await search._product_raw(page, mon)
                finally:
                    await browser.close()

        raw = asyncio.run(run())
        self.assertEqual(raw["brand"], "L'ORÉAL PARIS")
        self.assertEqual(raw["name"], "Telescopic Lift Extra Black")


if __name__ == "__main__":
    unittest.main()
