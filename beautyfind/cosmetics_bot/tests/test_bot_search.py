"""handle_search: сообщения о недоступных магазинах (задача №4). Telegram и браузер не нужны."""

import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cosmetics_bot.src.telegram import bot
from cosmetics_bot.src.scraping.stores import STORES
from cosmetics_bot.src.ui.formatter import unavailable_line


def make_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat.id = 1
    status = MagicMock()
    status.delete = AsyncMock()
    msg.answer = AsyncMock(return_value=status)
    return msg


@contextlib.asynccontextmanager
async def fake_browser_ctx():
    yield MagicMock()


class HandleSearchUnavailableTests(unittest.TestCase):
    def run_search(self, text: str, collect_result):
        msg = make_message(text)
        with patch.object(bot, "browser_ctx", fake_browser_ctx), \
             patch.object(bot, "collect_all", AsyncMock(return_value=collect_result)):
            asyncio.run(bot.handle_search(msg))
        # Первое сообщение — статус «Ищу по магазинам...», его не проверяем
        return [c.args[0] for c in msg.answer.await_args_list][1:]

    def test_all_stores_unavailable_says_not_answered(self):
        names = [s.name for s in STORES]
        sent = self.run_search("крем", ([], names))
        self.assertEqual(sent[0], unavailable_line(names))
        self.assertEqual(sent[-1], "⚠️ Магазины не ответили, попробуйте позже.")
        self.assertNotIn("ничего не нашлось", " ".join(sent))

    def test_one_store_unavailable_shows_notice_and_not_found(self):
        sent = self.run_search("крем", ([], ["Mon Amie"]))
        self.assertEqual(sent[0], "⚠️ Mon Amie: недоступен")
        self.assertIn("ничего не нашлось", sent[-1])

    def test_no_unavailable_keeps_old_message(self):
        sent = self.run_search("крем", ([], []))
        self.assertEqual(sent, ["😔 К сожалению, по вашему запросу ничего не нашлось."])


class UnknownCommandTests(unittest.TestCase):
    def test_unknown_command_is_not_searched(self):
        msg = make_message("/foo")
        collect = AsyncMock(return_value=([], []))
        with patch.object(bot, "browser_ctx", fake_browser_ctx), \
             patch.object(bot, "collect_all", collect):
            asyncio.run(bot.handle_search(msg))
        collect.assert_not_awaited()
        msg.answer.assert_awaited_once_with("Неизвестная команда. Список команд: /help")


class FinalizeConcurrencyTests(unittest.TestCase):
    def test_no_more_than_limit_pages_in_parallel(self):
        state = {"now": 0, "max": 0}

        async def fake_fetch(browser, cand, want_volume):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return {"price": 100, "ratio": 1.0, "volume": None, "name": cand}

        cands = [f"c{i}" for i in range(12)]
        with patch.object(bot, "fetch_detail", fake_fetch):
            winner = asyncio.run(bot.finalize_cands(MagicMock(), cands, None))
        self.assertIsNotNone(winner)
        self.assertLessEqual(state["max"], bot.FINALIZE_CONCURRENCY)
        self.assertEqual(state["max"], bot.FINALIZE_CONCURRENCY)


class SingleItemSessionTests(unittest.TestCase):
    def test_single_position_uses_one_browser_block(self):
        from cosmetics_bot.src.core.models import Candidate

        cand = Candidate(store=STORES[0], brand="Vichy", name="Dercos", type_="", label="",
                         url="https://example.test/p/1", image="", rating=None, reviews=0,
                         list_price=1000, price_prefix="", pos=0, ratio=1.0)
        entered = {"n": 0}

        @contextlib.asynccontextmanager
        async def counting_ctx():
            entered["n"] += 1
            yield MagicMock()

        detail = {"price": 900, "title": "Dercos", "product_url": cand.url, "store": "Mon Amie",
                  "image_url": "", "currency": "₸"}
        fetch = AsyncMock(return_value=detail)
        msg = make_message("крем")
        with patch.object(bot, "browser_ctx", counting_ctx), \
             patch.object(bot, "collect_all", AsyncMock(return_value=([cand], []))), \
             patch.object(bot, "fetch_detail", fetch), \
             patch.object(bot, "send_product", AsyncMock()) as send:
            asyncio.run(bot.handle_search(msg))
        self.assertEqual(entered["n"], 1)
        fetch.assert_awaited_once()
        send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
