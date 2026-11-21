"""Проверка кодов оттенков на страницах товаров.

Нужна, когда в выдаче магазина кода нет, а на странице товара список оттенков есть.
Открывает страницу товара, читает элементы из Store.shade_sel и кладёт коды в Candidate.shade_codes.
Если страница не открылась (ошибка, блокировка 403, проверка Cloudflare), код остаётся None:
такой товар не считается совпадением, но и не считается «без кода».
"""

import asyncio
import logging

from playwright.async_api import Browser
from playwright.async_api import TimeoutError as PWTimeout

from cosmetics_bot.src.core.models import Candidate
from cosmetics_bot.src.core.shade import codes_in
from cosmetics_bot.src.scraping.search import GOTO_TIMEOUT_MS, _open_context

PROBE_BUDGET_S = 15      # сек на все проверки вместе; что не успели, остаётся с кодом None
PROBE_CONCURRENCY = 4    # одновременных страниц товара
PROBE_MAX = 20           # максимум страниц за один запрос
PROBE_WAIT_MS = 4_000    # сколько ждать элементы оттенков на странице

_BLOCK_TITLE_MARKERS = ("just a moment", "один момент", "attention required")

_READ_SHADES_JS = """
(args) => {
  const { sel, attr } = args;
  return Array.from(document.querySelectorAll(sel))
    .map((el) => (attr ? el.getAttribute(attr) : null) || el.textContent || "")
    .map((s) => s.trim())
    .filter(Boolean);
}
"""


async def _probe_one(browser: Browser, cand: Candidate) -> None:
    store = cand.store
    ctx = await _open_context(browser, store.block_images)
    try:
        page = await ctx.new_page()
        response = await page.goto(cand.url, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        status = getattr(response, "status", None)
        title = (await page.title()).lower()
        if (status is not None and status >= 400) or any(m in title for m in _BLOCK_TITLE_MARKERS):
            logging.warning(f"[оттенки] {store.name}: страница недоступна (HTTP {status}), код не проверен")
            return
        try:
            # state="attached": список оттенков часто скрыт (раскрывается по клику), но есть в DOM
            await page.wait_for_selector(store.shade_sel, state="attached", timeout=PROBE_WAIT_MS)
        except PWTimeout:
            pass  # товар с одним оттенком: списка нет, код берём из того, что есть на странице
        raw = await page.evaluate(_READ_SHADES_JS, {"sel": store.shade_sel, "attr": store.shade_attr})
        cand.shade_codes = codes_in(" ".join(raw)) or ()
    finally:
        await ctx.close()


async def probe_shades(browser: Browser, cands: list[Candidate]) -> int:
    """Проверяет коды у кандидатов без кода, у магазинов с shade_sel. Возвращает число проверяемых."""
    todo = [c for c in cands if c.shade_codes is None and c.store.shade_sel][:PROBE_MAX]
    if not todo:
        return 0
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def one(c: Candidate) -> None:
        async with sem:
            try:
                await _probe_one(browser, c)
            except Exception as e:
                logging.warning(f"[оттенки] {c.store.name}: проверка не удалась: {e!r}")

    try:
        await asyncio.wait_for(asyncio.gather(*(one(c) for c in todo)), timeout=PROBE_BUDGET_S)
    except asyncio.TimeoutError:
        logging.warning(f"[оттенки] не уложились в {PROBE_BUDGET_S} с, часть товаров без проверки")
    logging.info(f"[оттенки] проверено страниц: {len(todo)}")
    return len(todo)
