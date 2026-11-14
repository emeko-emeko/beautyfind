"""Сбор выдачи магазинов.

Один переход на страницу, один evaluate на все карточки, дедупликация по URL.
Фильтрация по релевантности здесь не выполняется: см. вызывающий код.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import TimeoutError as PWTimeout

from cosmetics_bot.src.core.models import Candidate, Store
from cosmetics_bot.src.core.utils import (
    CARDS_PER_STORE,
    STORE_TIMEOUT,
    digits_int,
    make_hay,
    relevance,
    to_float,
)
from cosmetics_bot.src.scraping.stores import USER_AGENT

DEBUG = os.getenv("SCRAPER_DEBUG") == "1"
STORAGE_STATE = os.getenv("GA_STORAGE_STATE")  # файл с куками (адрес доставки)
CARD_WAIT_MS = 12_000
POLL_MS = 400                   # шаг опроса выдачи: карточки или «ничего не найдено»
GOTO_TIMEOUT_MS = 20_000
MAX_LOAD_ATTEMPTS = 2
BLOCK_MARKERS = ("страница недоступна",)
NOT_FOUND_MARKERS = ("ничего не найден",)
HEAVY_RESOURCES = {"image", "font", "media"}

STATUS_OK = "ok"                  # выдача получена (карточки могут быть пустыми)
STATUS_EMPTY = "empty"            # магазин ответил «ничего не найдено»
STATUS_UNAVAILABLE = "unavailable"  # таймаут, заглушка, ошибка: магазин не ответил

# Один вызов в браузере: читает все карточки разом.
EXTRACT_JS = """
(args) => {
  const { cardSel, sel, base, limit } = args;
  const q = (root, s) => (s ? root.querySelector(s) : null);
  const txt = (root, s) => { const el = q(root, s); return el ? (el.textContent || "").trim() : ""; };
  const att = (root, s, a) => { const el = q(root, s); return el ? (el.getAttribute(a) || "").trim() : ""; };
  // Только собственный текст элемента, без текста вложенных (старой цены)
  const ownText = (root, s) => {
    const el = q(root, s);
    if (!el) return "";
    return Array.from(el.childNodes).filter((n) => n.nodeType === 3)
      .map((n) => n.textContent).join("").trim();
  };
  const fixUrl = (u) => {
    if (!u || u.startsWith("data:")) return "";
    if (u.startsWith("//")) return "https:" + u;
    if (u.startsWith("/")) return base + u;
    return u;
  };
  const out = [];
  const seen = new Set();
  for (const card of document.querySelectorAll(cardSel)) {
    if (out.length >= limit) break;
    const url = fixUrl(att(card, sel.link, "href"));
    if (!url || seen.has(url)) continue;
    seen.add(url);
    const name = sel.name_from_attr
      ? (att(card, sel.name_sel, "title") || txt(card, sel.name_sel))
      : txt(card, sel.name_sel);
    let image = "";
    for (const s of (sel.images || [])) {
      const img = q(card, s);
      if (!img) continue;
      image = fixUrl(img.getAttribute("data-src") || img.getAttribute("src") || "");
      if (image) break;
    }
    out.push({
      url,
      name,
      brand: txt(card, sel.brand),
      type: txt(card, sel.type_sel),
      label: att(card, sel.label_sel, "title") || name,
      image,
      rating: att(card, sel.rating_sel, "content"),
      reviews: att(card, sel.reviews_sel, "content"),
      price: sel.price_own_text ? ownText(card, sel.price) : txt(card, sel.price),
    });
  }
  return out;
}
"""

SEL_FIELDS = (
    "link", "name_sel", "name_from_attr", "brand", "type_sel",
    "label_sel", "rating_sel", "reviews_sel", "price", "price_own_text", "images",
)


async def _block_heavy(route):
    if route.request.resource_type in HEAVY_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def _open_context(browser: Browser) -> BrowserContext:
    kwargs = dict(
        user_agent=USER_AGENT,
        locale="ru-RU",
        timezone_id="Asia/Almaty",
        viewport={"width": 1366, "height": 900},
        extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
    )
    if STORAGE_STATE and os.path.exists(STORAGE_STATE):
        kwargs["storage_state"] = STORAGE_STATE
    ctx = await browser.new_context(**kwargs)
    await ctx.route("**/*", _block_heavy)
    return ctx


async def _body_text(page: Page) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=3000)).lower()
    except Exception:
        return ""


async def _scroll_all(page: Page) -> None:
    for _ in range(4):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(250)


async def _wait_listing(page: Page, store: Store) -> str:
    """Опрос страницы: возвращает «ok» или «empty» сразу, как только видно карточку
    или признак пустой выдачи. Если не появилось ни то ни другое — «timeout»."""
    deadline = time.monotonic() + CARD_WAIT_MS / 1000
    while True:
        if await page.locator(store.card).count() > 0:
            return "ok"
        text = await _body_text(page)
        if any(m in text for m in NOT_FOUND_MARKERS):
            return "empty"
        if time.monotonic() >= deadline:
            return "timeout"
        await page.wait_for_timeout(POLL_MS)


async def _load_listing(page: Page, store: Store, url: str) -> str:
    for attempt in range(1, MAX_LOAD_ATTEMPTS + 1):
        await page.goto(url, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        state = await _wait_listing(page, store)
        if state == "empty":
            # Магазин честно ответил «ничего не найдено»: ждать и повторять незачем
            logging.info(f"[{store.name}] в выдаче ничего не найдено")
            return STATUS_EMPTY
        if state == "ok":
            await _scroll_all(page)
            return STATUS_OK
        text = await _body_text(page)
        blocked = any(m in text for m in BLOCK_MARKERS)
        logging.warning(
            f"[{store.name}] попытка {attempt}: карточек нет "
            f"(заглушка сайта: {blocked})"
        )
        await page.wait_for_timeout(1500 * attempt)
    return STATUS_UNAVAILABLE


async def _dump_debug(page: Page, store: Store) -> None:
    if not DEBUG:
        return
    safe = re.sub(r"\W+", "_", store.name)
    try:
        await page.screenshot(path=f"debug_{safe}.png", full_page=True)
        Path(f"debug_{safe}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass


def _build_candidate(store: Store, raw: dict, groups, pos: int) -> Candidate:
    brand = raw["brand"]
    type_ = raw["type"]
    label = raw["label"]
    price_raw = raw["price"] or ""

    native = None
    if store.price_currency != "₸":
        # Цена в валюте магазина (например, 111.00€): переводим в тенге
        native = to_float(price_raw)
        list_price = round(native * store.fx_to_kzt) if native is not None else None
    else:
        list_price = digits_int(price_raw)

    cand = Candidate(
        store=store,
        brand=brand,
        name=raw["name"],
        type_=type_,
        label=label,
        url=raw["url"],
        image=raw["image"],
        rating=to_float(raw["rating"]),
        reviews=int(to_float(raw["reviews"]) or 0),
        list_price=list_price,
        price_prefix="от " if price_raw.lower().startswith("от") else "",
        pos=pos,
        list_price_native=native,
    )
    cand.hay = make_hay(f"{brand} {cand.full_title} {type_} {label}", brand)
    cand.ratio = relevance(groups, cand.hay)
    return cand


async def list_store(
    browser: Browser, store: Store, query: str, groups: list[list[str]]
) -> tuple[str, list[Candidate]]:
    """Возвращает (статус магазина, кандидаты). Статус: ok / empty / unavailable."""
    ctx = await _open_context(browser)
    try:
        page = await ctx.new_page()
        url = store.search_url.format(query=quote_plus(query))
        logging.info(f"[{store.name}] запрос: {url}")

        status = await _load_listing(page, store, url)
        if status == STATUS_UNAVAILABLE:
            logging.warning(f"[{store.name}] выдача не загрузилась")
            await _dump_debug(page, store)
            return status, []
        if status == STATUS_EMPTY:
            return status, []

        sel = {f: getattr(store, f, None) for f in SEL_FIELDS}
        raw_items = await page.evaluate(
            EXTRACT_JS,
            {
                "cardSel": store.card,
                "sel": sel,
                "base": store.base_url,
                "limit": CARDS_PER_STORE,
            },
        )
        logging.info(f"[{store.name}] карточек извлечено: {len(raw_items)}")
        return STATUS_OK, [
            _build_candidate(store, raw, groups, pos)
            for pos, raw in enumerate(raw_items)
        ]
    except Exception as e:
        logging.error(f"[{store.name}] ошибка при чтении выдачи: {e!r}")
        return STATUS_UNAVAILABLE, []
    finally:
        await ctx.close()


async def collect_all(
    browser: Browser, query: str, groups: list[list[str]]
) -> tuple[list[Candidate], list[str]]:
    """Возвращает (кандидаты всех магазинов, названия магазинов, которые не ответили)."""
    from cosmetics_bot.src.scraping.stores import STORES

    async def run(store: Store) -> tuple[str, list[Candidate]]:
        try:
            return await asyncio.wait_for(
                list_store(browser, store, query, groups),
                timeout=STORE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logging.error(f"[{store.name}] таймаут {STORE_TIMEOUT} с")
            return STATUS_UNAVAILABLE, []
        except Exception as e:
            logging.error(f"[{store.name}] ошибка: {e!r}")
            return STATUS_UNAVAILABLE, []

    results = await asyncio.gather(*(run(s) for s in STORES))
    cands = [c for _, r in results for c in r]
    unavailable = [
        s.name for s, (status, _) in zip(STORES, results) if status == STATUS_UNAVAILABLE
    ]
    return cands, unavailable
