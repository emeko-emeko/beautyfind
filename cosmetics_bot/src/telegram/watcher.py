"""Фоновая проверка цен отслеживаемых товаров и уведомления об изменении."""

import asyncio
import html
import logging

from aiogram import Bot

from cosmetics_bot.src.core.db import get_watches_for_monitor, update_watch_price
from cosmetics_bot.src.core.models import Candidate
from cosmetics_bot.src.core.utils import format_money
from cosmetics_bot.src.scraping.details import DETAIL_HANDLERS, fetch_detail, open_detail_context
from cosmetics_bot.src.scraping.stores import STORES, browser_ctx, find_store

CHECK_INTERVAL = 600   # сек между проходами по списку
PAUSE_BETWEEN = 3      # сек между товарами, чтобы не нагружать магазины


def store_for_url(url: str):
    return next((s for s in STORES if url.startswith(s.base_url + "/")), None)


def is_watch_supported(store_name: str) -> bool:
    """Цену можно перепроверить, только если у магазина есть обработчик страницы товара."""
    store = find_store(store_name)
    return bool(store and store.detail in DETAIL_HANDLERS)


async def _fetch_price(store, watch: dict, browser, context) -> dict | None:
    cand = Candidate(
        store=store, brand="", name=watch["title"], type_="", label="", url=watch["product_url"],
        image="", rating=None, reviews=0, list_price=None, price_prefix="", pos=0,
    )
    return await fetch_detail(browser, cand, watch.get("volume"), context=context)


async def _notify(bot: Bot, watch: dict, old: int, new: int, currency: str) -> None:
    head = "📉 Цена снизилась" if new < old else "📈 Цена выросла"
    text = (
        f"{head}: <b>{html.escape(watch['title'])}</b>\n"
        f"Было: {format_money(old, currency)}\n"
        f"Стало: {format_money(new, currency)}\n"
        f"<a href='{html.escape(watch['product_url'], quote=True)}'>Смотреть на сайте</a>"
    )
    try:
        await bot.send_message(watch["chat_id"], text)
    except Exception as e:
        logging.warning(f"Не удалось отправить уведомление о цене: {e!r}")


async def _check_one(bot: Bot, store, w: dict, browser, context) -> None:
    try:
        res = await _fetch_price(store, w, browser, context)
    except Exception as e:
        logging.warning(f"[{store.name}] проверка цены не удалась: {e!r}")
        res = None

    if not res or res.get("price") is None:
        # Товара нет в наличии или страница не открылась: цену не меняем
        update_watch_price(w["id"], w["last_price"])
    else:
        new = res["price"]
        old = w["last_price"]
        if old is not None and new != old:
            await _notify(bot, w, old, new, store.currency)
        update_watch_price(w["id"], new)


async def _check_store(bot: Bot, store, items: list[dict]) -> None:
    """Все отслеживаемые товары одного магазина — в одном браузерном контексте."""
    done = 0
    try:
        async with browser_ctx() as browser:
            context = await open_detail_context(browser)
            try:
                for w in items:
                    await _check_one(bot, store, w, browser, context)
                    done += 1
                    await asyncio.sleep(PAUSE_BETWEEN)
            finally:
                await context.close()
    except Exception as e:
        # Браузер или контекст не поднялись: цены необработанных товаров не меняем,
        # уже проверенные не трогаем (иначе старая цена вернулась бы в базу)
        logging.warning(f"[{store.name}] проверка прервана: {e!r}")
        for w in items[done:]:
            update_watch_price(w["id"], w["last_price"])


async def check_watches(bot: Bot) -> None:
    groups: dict[str, tuple] = {}  # название магазина -> (магазин, [подписки])
    for w in get_watches_for_monitor():
        store = store_for_url(w["product_url"])
        if store is None or store.detail not in DETAIL_HANDLERS:
            # Магазин без страницы товара: проверку пропускаем, цена остаётся прежней
            update_watch_price(w["id"], w["last_price"])
            continue
        groups.setdefault(store.name, (store, []))[1].append(w)

    for store, items in groups.values():
        await _check_store(bot, store, items)


async def watch_loop(bot: Bot) -> None:
    while True:
        try:
            await check_watches(bot)
        except Exception:
            logging.exception("Ошибка при проверке цен")
        await asyncio.sleep(CHECK_INTERVAL)
