"""Product details scraping handlers for Mon Amie, Gold Apple and French House."""

import asyncio
import json
import re
from playwright.async_api import Browser
from cosmetics_bot.src.core.models import Candidate
from cosmetics_bot.src.core.utils import (
    digits_int,
    to_float,
    STORE_TIMEOUT,
    MAX_VOLUME_ONLY,
    VOLUME_RE,
)
from cosmetics_bot.src.scraping.stores import USER_AGENT
from cosmetics_bot.src.scraping.search import _block_heavy
from cosmetics_bot.src.core.db import cache_get, cache_set


async def text_of(root, selector: str | None) -> str:
    if not selector:
        return ""
    loc = root.locator(selector).first
    if await loc.count() == 0:
        return ""
    return ((await loc.text_content()) or "").strip()


def choose_variant(variants: list[tuple], want_volume: float | None, current: tuple | None = None) -> tuple:
    """Введённый объём в приоритете. Без него: максимальный (MAX_VOLUME_ONLY) или текущий вариант сайта."""
    if want_volume is not None:
        for v in variants:
            if abs(v[0] - want_volume) < 1e-6:
                return v
    if not MAX_VOLUME_ONLY and current is not None:
        return current
    return max(variants, key=lambda v: v[0])


async def detail_monamie(page, want_volume: float | None) -> dict | None:
    labels = page.locator("label.js-product-detail__prop.product-detail-prop__item--size")
    variants = []
    for i in range(await labels.count()):
        lab = labels.nth(i)
        try:
            info = json.loads(await lab.get_attribute("data-info") or "{}")
        except ValueError:
            continue
        vol = to_float(await text_of(lab, ".product-detail-prop__item-inner"))
        price = info.get("price")
        if vol is None or price is None:
            continue
        old = info.get("basePrice") if info.get("hasDiscount") else None
        variants.append((vol, int(price), int(old) if old else None))

    if variants:
        vol, price, old = choose_variant(variants, want_volume)
        return {"volume": vol, "unit": "мл", "price": price, "old_price": old, "loyalty_price": None}

    price = digits_int(await text_of(page, ".js-product-detail__price-now"))
    if price is None:
        return None
    return {"volume": None, "unit": "", "price": price, "old_price": None, "loyalty_price": None}


async def _ga_price_text(page) -> str:
    block = page.locator("[data-test-id='price-info-block']").first
    return await text_of(block, "[class*='pdp-price-row__row_actual'] [class*='pdp-price-row__value']")


async def detail_goldapple(page, want_volume: float | None) -> dict | None:
    radios = page.locator("input[name='units']")
    values = []
    for i in range(await radios.count()):
        raw = await radios.nth(i).get_attribute("value") or ""
        v = to_float(raw)
        if v is not None:
            values.append((v, raw))

    unit = "мл"
    label = await text_of(page, "[class*='pdp-attribute-few__label']")
    if "/" in label:
        unit = label.split("/")[-1].strip() or unit

    chosen_volume = None
    if values:
        current = None
        for v in values:
            if await page.locator(f"input[name='units'][value='{v[1]}']").first.is_checked():
                current = v
                break
        chosen_volume, raw = choose_variant(values, want_volume, current)
        radio = page.locator(f"input[name='units'][value='{raw}']").first
        if not await radio.is_checked():
            before = await _ga_price_text(page)
            try:
                await page.locator(f"label[data-test-id='radio-label_{raw}']").first.click(timeout=5000)
            except Exception:
                await radio.check(force=True)
            for _ in range(15):
                await page.wait_for_timeout(300)
                if await _ga_price_text(page) != before:
                    break

    block = page.locator("[data-test-id='price-info-block']").first
    price = digits_int(await _ga_price_text(page))
    if price is None:
        price = digits_int(await text_of(block, "[class*='pdp-price-row__value']"))
    if price is None:
        return None

    loyalty = digits_int(
        await text_of(block, "[class*='pdp-price-row__row_best'] [class*='pdp-price-row__value']")
    )
    if loyalty is not None and loyalty >= price:
        loyalty = None

    return {
        "volume": chosen_volume,
        "unit": unit if chosen_volume is not None else "",
        "price": price,
        "old_price": None,
        "loyalty_price": loyalty,
    }


async def detail_frenchhouse(page, want_volume: float | None) -> dict | None:
    # Варианты объёма: радио name="VOLUME", подпись вида «100 ML» в label[for=id].
    radios = page.locator("input[name='VOLUME']")
    variants = []  # (volume, radio_id)
    current = None
    for i in range(await radios.count()):
        rid = await radios.nth(i).get_attribute("id") or ""
        m = VOLUME_RE.search(await text_of(page, f"label[for='{rid}']")) if rid else None
        if not m:
            continue
        v = (float(m.group(1).replace(",", ".")), rid)
        variants.append(v)
        if await radios.nth(i).is_checked():
            current = v

    chosen_volume = None
    if variants:
        chosen_volume, rid = choose_variant(variants, want_volume, current)
        if current is None or rid != current[1]:
            before = await text_of(page, "#price")
            try:
                await page.locator(f"label[for='{rid}']").first.click(timeout=5000)
            except Exception:
                await page.locator(f"input[id='{rid}']").first.check(force=True)
            for _ in range(15):
                await page.wait_for_timeout(300)
                if await text_of(page, "#price") != before:
                    break

    price = digits_int(await text_of(page, "#price"))
    if price is None:
        return None
    old = digits_int(await text_of(page, "#oldPrice"))
    if old is not None and old <= price:
        old = None
    return {
        "volume": chosen_volume,
        "unit": "мл" if chosen_volume is not None else "",
        "price": price,
        "old_price": old,
        "loyalty_price": None,
    }


async def _own_text(loc) -> str:
    """Текст самого элемента, без текста вложенных (старой цены внутри блока)."""
    if await loc.count() == 0:
        return ""
    return await loc.evaluate(
        "el => Array.from(el.childNodes).filter(n => n.nodeType === 3)"
        ".map(n => n.textContent).join('').trim()"
    )


async def detail_yvesrocher(page, want_volume: float | None) -> dict | None:
    # Объёма в селекторах нет: он в заголовке, например «..., 30 мл». Вариантов размера нет.
    price_loc = page.locator(
        "[class*='ProductCardSidebar_priceDisplay'] [class*='PriceDisplay_price']"
    ).first
    price = digits_int(await _own_text(price_loc))
    if price is None:
        return None
    old = digits_int(await text_of(
        page, "[class*='ProductCardSidebar_priceDisplay'] [class*='PriceDisplay_oldPrice']"
    ))
    if old is not None and old <= price:
        old = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*мл", await text_of(page, "h1"))
    volume = float(m.group(1).replace(",", ".")) if m else None
    return {
        "volume": volume,
        "unit": "мл" if volume is not None else "",
        "price": price,
        "old_price": old,
        "loyalty_price": None,
    }


DETAIL_HANDLERS = {
    "monamie": detail_monamie,
    "goldapple": detail_goldapple,
    "frenchhouse": detail_frenchhouse,
    "yvesrocher": detail_yvesrocher,
}


async def fetch_detail(browser: Browser, cand: Candidate, want_volume: float | None) -> dict | None:
    store = cand.store
    result = cand.to_result()

    if not store.detail:
        # Страница товара не разбирается: берём цену из выдачи
        result["price"] = cand.list_price
        result["price_native"] = cand.list_price_native
        return result if result["price"] is not None else None

    # Цена зависит от объёма: ключ кэша включает введённый объём или режим выбора без него.
    if want_volume is not None:
        mode = f"v{want_volume:g}"
    else:
        mode = "max" if MAX_VOLUME_ONLY else "cur"
    cache_key = f"{cand.url}#{mode}"

    cached = cache_get(cache_key)
    if cached:
        result.update(cached)
        return result

    async def _load():
        context = await browser.new_context(user_agent=USER_AGENT, locale="ru-RU")
        # Картинки, шрифты и видео на странице товара не нужны: цена приходит из HTML/JS
        await context.route("**/*", _block_heavy)
        try:
            page = await context.new_page()
            await page.goto(cand.url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_selector(store.detail_ready, timeout=15000)
            return await DETAIL_HANDLERS[store.detail](page, want_volume)
        finally:
            await context.close()

    detail = None
    try:
        detail = await asyncio.wait_for(_load(), timeout=STORE_TIMEOUT)
    except Exception as e:
        import logging
        logging.warning(f"[{store.name}] не удалось разобрать страницу товара: {e!r}")

    if detail:
        result.update(detail)
        cache_set(cache_key, detail)
    else:
        result["price"] = cand.list_price
        result["price_native"] = cand.list_price_native
        result["price_prefix"] = cand.price_prefix
    return result if result["price"] is not None else None
