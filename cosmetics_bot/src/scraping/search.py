"""Сбор выдачи магазинов.

Один переход на страницу, один evaluate на все карточки, дедупликация по URL.
Фильтрация по релевантности здесь не выполняется: см. вызывающий код.
"""

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import TimeoutError as PWTimeout

from cosmetics_bot.src.core import db as cache_db
from cosmetics_bot.src.core.models import Candidate, Store
from cosmetics_bot.src.core.utils import (
    CARDS_PER_STORE,
    STORE_TIMEOUT,
    digits_int,
    make_hay,
    relevance,
    search_variants,
    to_float,
)
from cosmetics_bot.src.scraping.stores import USER_AGENT

DEBUG = os.getenv("SCRAPER_DEBUG") == "1"
STORAGE_STATE = os.getenv("GA_STORAGE_STATE")  # файл с куками (адрес доставки)
CARD_WAIT_MS = 6_000            # сколько ждать карточки или признак пустой выдачи (было 12 с)
SCROLL_STEPS = 4                # сколько раз листать выдачу (ленивая подгрузка карточек)
SCROLL_WAIT_MS = 1_000          # сколько ждать новые карточки после прокрутки
SEARCH_CONCURRENCY = 3          # одновременно открытых магазинов (больше — падают вкладки)
# Бюджет поиска для пользователя, сек. По истечении отдаём то, что уже собрано; остальные магазины
# доснимаются в фоне и кладут полную выдачу в кэш (запись 035).
SEARCH_DEADLINE_S = 20  # было 10 с (запись 035), 14 с (запись 039); 20 с — решение владельца (запись 045)
# Второе написание запроса запрашиваем, только если первое дало меньше карточек (запись 040).
# 1 = только если первое пусто или магазин не ответил. Больше — полнее выдача, но дольше сбор.
SECOND_SPELLING_IF_FEWER_THAN = 5  # запись 042: было 1
SEARCH_CACHE_TTL = 60 * 60          # сек, свежая выдача: отдаём без обращения к магазинам
SEARCH_CACHE_STALE = 6 * 60 * 60    # сек, старая выдача: отдаём сразу и обновляем в фоне
SEARCH_CACHE_MAX = 1000             # максимум запросов в кэше; самые давние вытесняются
# Кэш в Postgres (таблица search_cache): переживает деплой. Включается SEARCH_CACHE_DB=1 в окружении.
SEARCH_CACHE_DB = os.getenv("SEARCH_CACHE_DB") == "1"
GOTO_TIMEOUT_MS = 10_000        # было 20 с
MAX_LOAD_ATTEMPTS = 2
BLOCK_MARKERS = ("страница недоступна",)
# Фразы пустой выдачи на сайтах: Viled — «товаров не найдено», Space NK — «couldn't find results»
NOT_FOUND_MARKERS = ("ничего не найден", "товаров не найдено", "couldn't find results", "couldn’t find results")
HEAVY_RESOURCES = {"image", "font", "media"}

STATUS_OK = "ok"                  # выдача получена (карточки могут быть пустыми)
STATUS_EMPTY = "empty"            # магазин ответил «ничего не найдено»
STATUS_UNAVAILABLE = "unavailable"  # таймаут, заглушка, ошибка: магазин не ответил
STATUS_PRODUCT = "product"          # сайт сразу открыл страницу одного товара, списка нет

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
      restricted: !!q(card, sel.restricted_sel),
    });
  }
  return out;
}
"""

SEL_FIELDS = (
    "link", "name_sel", "name_from_attr", "brand", "type_sel",
    "label_sel", "rating_sel", "reviews_sel", "price", "price_own_text", "images",
    "restricted_sel",
)


async def _block_heavy(route):
    if route.request.resource_type in HEAVY_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def _open_context(browser: Browser, block_images: bool = True) -> BrowserContext:
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
    if block_images:
        await ctx.route("**/*", _block_heavy)
    return ctx


async def _body_text(page: Page) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=3000)).lower()
    except Exception:
        return ""


async def _scroll_all(page: Page, card: str) -> None:
    """Листаем выдачу, пока догружаются новые карточки. Ждём их появления в браузере,
    а не фиксированные паузы: как только ничего не догрузилось или набран лимит — останавливаемся."""
    for _ in range(SCROLL_STEPS):
        before = await page.locator(card).count()
        if before >= CARDS_PER_STORE:
            return
        await page.mouse.wheel(0, 1500)
        try:
            await page.wait_for_function(
                "([sel, n]) => document.querySelectorAll(sel).length > n",
                arg=[card, before],
                timeout=SCROLL_WAIT_MS,
            )
        except PWTimeout:
            return


# Ждём в браузере одно из двух: карточки или признак пустой выдачи (без опроса из Python)
WAIT_LISTING_JS = """
([cardSel, markers]) => {
  if (document.querySelector(cardSel)) return "ok";
  const t = ((document.body && document.body.innerText) || "").toLowerCase();
  if (markers.some((m) => t.includes(m))) return "empty";
  return null;
}
"""


async def _wait_listing(page: Page, store: Store) -> str:
    """Возвращает «ok» или «empty» сразу, как только видно карточку или признак пустой выдачи.
    Если ни то ни другое не появилось за CARD_WAIT_MS — «timeout»."""
    try:
        handle = await page.wait_for_function(
            WAIT_LISTING_JS,
            arg=[store.card, list(NOT_FOUND_MARKERS)],
            timeout=CARD_WAIT_MS,
        )
    except PWTimeout:
        return "timeout"
    return await handle.json_value()


async def _page_diag(page: Page, response) -> str:
    """Короткая сводка о странице для лога: HTTP-статус, title, длина текста.
    Нужна, чтобы отличить блокировку (статус 403, пустой текст) от медленной загрузки."""
    status = getattr(response, "status", "?") if response is not None else "?"
    try:
        title = await page.title()
    except Exception:
        title = "?"
    text = await _body_text(page)
    return f"HTTP {status}, title {title!r}, текст {len(text)} симв."


async def _is_product_page(page: Page, store: Store) -> bool:
    return bool(store.product_page_sel) and await page.locator(store.product_page_sel).count() > 0


async def _product_raw(page: Page, store: Store) -> dict:
    """Одна карточка из страницы товара (когда сайт пропустил список)."""
    async def txt(sel: str | None) -> str:
        if not sel:
            return ""
        loc = page.locator(sel).first
        return ((await loc.text_content()) or "").strip() if await loc.count() else ""

    name = " ".join((await txt(store.product_name_sel)).split())
    brand_block = await txt(store.product_brand_sel)
    brand = " ".join(brand_block.split("\n")[0].split()) if brand_block else ""
    return {
        "url": page.url, "name": name, "brand": brand, "type": "", "label": name,
        "image": "", "rating": "", "reviews": "", "price": "", "restricted": False,
    }


async def _load_listing(page: Page, store: Store, url: str) -> str:
    for attempt in range(1, MAX_LOAD_ATTEMPTS + 1):
        response = await page.goto(url, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        state = await _wait_listing(page, store)
        if state == "timeout" and await _is_product_page(page, store):
            return STATUS_PRODUCT
        if state == "empty":
            # Магазин честно ответил «ничего не найдено»: ждать и повторять незачем
            logging.info(f"[{store.name}] в выдаче ничего не найдено")
            return STATUS_EMPTY
        if state == "ok":
            await _scroll_all(page, store.card)
            return STATUS_OK
        text = await _body_text(page)
        blocked = any(m in text for m in BLOCK_MARKERS)
        logging.warning(
            f"[{store.name}] попытка {attempt}: карточек нет "
            f"(заглушка сайта: {blocked}; {await _page_diag(page, response)})"
        )
        if getattr(response, "status", None) == 403:
            # 403 — блокировка (Cloudflare): повтор тем же браузером ничего не даст, экономим 10–20 с
            logging.warning(f"[{store.name}] HTTP 403, повтор не делаем")
            return STATUS_UNAVAILABLE
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
        restricted=bool(raw.get("restricted")),
    )
    cand.hay = make_hay(f"{brand} {cand.full_title} {type_} {label}", brand)
    cand.ratio = relevance(groups, cand.hay)
    return cand


async def list_store(
    browser: Browser, store: Store, query: str, groups: list[list[str]]
) -> tuple[str, list[Candidate]]:
    """Возвращает (статус магазина, кандидаты). Статус: ok / empty / unavailable."""
    ctx = await _open_context(browser, store.block_images)
    try:
        page = await ctx.new_page()
        url = store.search_url.format(query=quote_plus(query))
        logging.info(f"[{store.name}] запрос: {url}")

        status = await _load_listing(page, store, url)
        if status == STATUS_PRODUCT:
            logging.info(f"[{store.name}] сайт открыл страницу товара вместо списка")
            return STATUS_OK, [_build_candidate(store, await _product_raw(page, store), groups, 0)]
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


# Кэш выдачи по запросу в памяти процесса: повтор того же запроса не открывает магазины заново.
# Ключ — запрос без лишних пробелов, в нижнем регистре, «ё» как «е» (группы для релевантности
# выводятся из запроса, поэтому разные написания одного запроса дают один ключ).
# Запись свежая до SEARCH_CACHE_TTL. После этого до SEARCH_CACHE_STALE её отдают сразу,
# а выдачу обновляют в фоне (schedule_refresh). Всё ограничено по размеру и по времени,
# иначе память растёт с каждым новым запросом.
_search_cache: "OrderedDict[str, tuple[float, list[Candidate], list[str]]]" = OrderedDict()
_refreshing: set[str] = set()     # ключи, по которым обновление уже идёт
_refresh_tasks: set = set()       # ссылки на фоновые задачи, чтобы их не удалил сборщик мусора


def _cache_key(query: str) -> str:
    """Ключ общий для обоих написаний (кириллица и латиница): выдача по ним одна (запись 037)."""
    return "|".join(sorted(set(search_variants(query))))


def _purge_expired(now: float) -> None:
    for key in [k for k, (saved_at, _, _) in _search_cache.items() if now - saved_at > SEARCH_CACHE_STALE]:
        del _search_cache[key]


def _to_payload(cands: list[Candidate]) -> list[dict]:
    """Кандидат → словарь для Postgres. Магазин хранится именем, hay — списком строк."""
    return [
        {
            "store": c.store.name, "brand": c.brand, "name": c.name, "type_": c.type_,
            "label": c.label, "url": c.url, "image": c.image, "rating": c.rating,
            "reviews": c.reviews, "list_price": c.list_price, "price_prefix": c.price_prefix,
            "pos": c.pos, "ratio": c.ratio, "list_price_native": c.list_price_native,
            "restricted": c.restricted, "hay": list(c.hay),
        }
        for c in cands
    ]


def _from_payload(items: list[dict]) -> list[Candidate] | None:
    """Словарь → кандидат. None, если какого-то магазина уже нет в STORES: такую запись не используем."""
    from cosmetics_bot.src.scraping.stores import find_store

    out = []
    for d in items:
        store = find_store(d["store"])
        if store is None:
            return None
        out.append(Candidate(
            store=store, brand=d["brand"], name=d["name"], type_=d["type_"], label=d["label"],
            url=d["url"], image=d["image"], rating=d["rating"], reviews=d["reviews"],
            list_price=d["list_price"], price_prefix=d["price_prefix"], pos=d["pos"],
            ratio=d["ratio"], list_price_native=d["list_price_native"], restricted=d["restricted"],
            hay=tuple(d["hay"]),
        ))
    return out


def _load_from_db(key: str) -> tuple[float, list[Candidate], list[str]] | None:
    """Запись из Postgres в память. Ошибка базы — не ошибка поиска: просто промах."""
    try:
        row = cache_db.search_cache_load(key)
        if row is None:
            return None
        age = time.time() - row["saved_at"]
        if age > SEARCH_CACHE_STALE:
            return None
        cands = _from_payload(row["payload"])
        if cands is None:
            return None
        entry = (time.monotonic() - age, cands, list(row["unavailable"]))
    except Exception as e:
        logging.error(f"[кэш] чтение из базы не удалось: {e!r}")
        return None
    _search_cache[key] = entry
    _search_cache.move_to_end(key)
    while len(_search_cache) > SEARCH_CACHE_MAX:
        _search_cache.popitem(last=False)
    return entry


def _save_to_db(key: str, saved_at_wall: float, cands: list[Candidate], unavailable: list[str]) -> None:
    try:
        cache_db.search_cache_save(key, saved_at_wall, _to_payload(cands), unavailable)
        cache_db.search_cache_purge(time.time() - SEARCH_CACHE_STALE)
    except Exception as e:
        logging.error(f"[кэш] запись в базу не удалась: {e!r}")


def _lookup(query: str, max_age: float) -> tuple[list[Candidate], list[str]] | None:
    key = _cache_key(query)
    hit = _search_cache.get(key)
    if hit is None and SEARCH_CACHE_DB:
        hit = _load_from_db(key)
    if hit is None:
        return None
    saved_at, cands, unavailable = hit
    if time.monotonic() - saved_at > max_age:
        return None
    _search_cache.move_to_end(key)  # недавно использованный запрос вытесняется последним
    return cands, unavailable


def search_cache_get(query: str) -> tuple[list[Candidate], list[str]] | None:
    """Свежая выдача (моложе SEARCH_CACHE_TTL)."""
    return _lookup(query, SEARCH_CACHE_TTL)


def search_cache_get_stale(query: str) -> tuple[list[Candidate], list[str]] | None:
    """Выдача старше TTL, но не старше SEARCH_CACHE_STALE. Её можно показать, пока идёт обновление."""
    return _lookup(query, SEARCH_CACHE_STALE)


def search_cache_set(query: str, cands: list[Candidate], unavailable: list[str]) -> None:
    """Не кэшируем, если хоть один магазин не ответил: частичная выдача закрепила бы сбой на час.
    Старая полная запись при этом не удаляется: её продолжают отдавать, пока она не устареет."""
    if unavailable:
        return
    now = time.monotonic()
    _purge_expired(now)
    key = _cache_key(query)
    _search_cache[key] = (now, cands, unavailable)
    _search_cache.move_to_end(key)
    while len(_search_cache) > SEARCH_CACHE_MAX:
        _search_cache.popitem(last=False)
    if SEARCH_CACHE_DB:
        _save_to_db(key, time.time(), cands, unavailable)


async def _refresh(query: str, groups: list[list[str]]) -> None:
    """Собирает выдачу заново в собственном браузере и кладёт в кэш."""
    from cosmetics_bot.src.scraping.stores import browser_ctx

    key = _cache_key(query)
    try:
        async with browser_ctx() as browser:
            # Фоновое обновление ждёт всех магазинов: бюджет поиска сюда не относится
            cands, unavailable = await collect_all(browser, query, groups, deadline=None)
        search_cache_set(query, cands, unavailable)
        logging.info(f"[кэш] выдача обновлена в фоне: «{query}», карточек {len(cands)}")
    except Exception as e:
        logging.error(f"[кэш] фоновое обновление «{query}» не удалось: {e!r}")
    finally:
        _refreshing.discard(key)


def schedule_refresh(query: str, groups: list[list[str]]) -> None:
    """Запускает фоновое обновление выдачи. Повторные вызовы для того же запроса игнорируются,
    пока первое обновление не закончится. Нужен работающий event loop."""
    key = _cache_key(query)
    if key in _refreshing:
        return
    _refreshing.add(key)
    task = asyncio.create_task(_refresh(query, groups))
    _refresh_tasks.add(task)
    task.add_done_callback(_refresh_tasks.discard)


async def _list_store_variants(
    browser: Browser, store: Store, variants: list[str], groups: list[list[str]]
) -> tuple[str, list[Candidate]]:
    """Собирает выдачу магазина по написаниям запроса и объединяет по URL.
    Первое написание всегда. Следующие — только пока карточек меньше SECOND_SPELLING_IF_FEWER_THAN
    (по умолчанию 1: то есть только если первое дало пусто или не ответило; запись 040).
    Статус: ok, если хоть одно написание дало карточки; unavailable, если магазин не ответил
    ни на одно написание (и не было ok); иначе empty."""
    statuses: list[str] = []
    found: list[Candidate] = []
    seen: set[str] = set()
    for i, variant in enumerate(variants):
        if i > 0 and len(found) >= SECOND_SPELLING_IF_FEWER_THAN:
            break
        status, cands = await list_store(browser, store, variant, groups)
        statuses.append(status)
        for c in cands:
            if c.url not in seen:
                seen.add(c.url)
                found.append(c)
    if STATUS_OK in statuses:
        return STATUS_OK, found
    if STATUS_UNAVAILABLE in statuses:
        return STATUS_UNAVAILABLE, []
    return STATUS_EMPTY, []


_tab_sem: asyncio.Semaphore | None = None
_tab_sem_loop: asyncio.AbstractEventLoop | None = None


def _tab_slots() -> asyncio.Semaphore:
    """Общий на весь процесс лимит одновременно открытых вкладок поиска (запись 041).
    Обычный поиск и фоновое доснятие делят одни и те же SEARCH_CONCURRENCY слотов.
    Семафор привязан к текущему event loop: при смене loop (тесты) создаётся новый."""
    global _tab_sem, _tab_sem_loop
    loop = asyncio.get_running_loop()
    if _tab_sem is None or _tab_sem_loop is not loop:
        _tab_sem = asyncio.Semaphore(SEARCH_CONCURRENCY)
        _tab_sem_loop = loop
    return _tab_sem


def _summarize(stores, results) -> tuple[list[Candidate], list[str]]:
    cands = [c for _, r in results for c in r]
    unavailable = [
        s.name for s, (status, _) in zip(stores, results) if status == STATUS_UNAVAILABLE
    ]
    return cands, unavailable


async def collect_all(
    browser: Browser, query: str, groups: list[list[str]], deadline: float | None = SEARCH_DEADLINE_S
) -> tuple[list[Candidate], list[str]]:
    """Возвращает (кандидаты всех магазинов, названия магазинов, которые не ответили).

    С deadline (сек): ждём не дольше него. Магазины, не успевшие к сроку, в ответе считаются
    не ответившими, а их сбор продолжается в фоне; когда все закончатся, полная выдача
    попадает в кэш (search_cache_set). deadline=None — ждать всех (как раньше, для фонового обновления).
    """
    from cosmetics_bot.src.scraping.stores import STORES

    variants = search_variants(query) or [query]

    async def run(store: Store) -> tuple[str, list[Candidate]]:
        # Общий на процесс семафор: таймаут магазина считается, только когда он уже работает
        async with _tab_slots():
            try:
                return await asyncio.wait_for(
                    _list_store_variants(browser, store, variants, groups),
                    timeout=STORE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logging.error(f"[{store.name}] таймаут {STORE_TIMEOUT} с")
                return STATUS_UNAVAILABLE, []
            except Exception as e:
                logging.error(f"[{store.name}] ошибка: {e!r}")
                return STATUS_UNAVAILABLE, []

    tasks = [asyncio.ensure_future(run(s)) for s in STORES]
    if deadline is None:
        results = await asyncio.gather(*tasks)
        return _summarize(STORES, results)

    done, pending = await asyncio.wait(tasks, timeout=deadline)
    results = [t.result() if t in done else (STATUS_UNAVAILABLE, []) for t in tasks]
    if pending:
        logging.info(
            f"[поиск] к сроку {deadline} с не успели: {len(pending)} из {len(tasks)}, доснимаем в фоне"
        )
        bg = asyncio.create_task(_finish_in_background(query, STORES, tasks))
        _refresh_tasks.add(bg)
        bg.add_done_callback(_refresh_tasks.discard)
    return _summarize(STORES, results)


_inflight: dict[str, asyncio.Future] = {}


async def collect_shared(
    browser: Browser, query: str, groups: list[list[str]]
) -> tuple[list[Candidate], list[str]]:
    """Один сбор на ключ кэша (запись 043). Если такой же запрос (тот же ключ, любое написание)
    уже идёт, второй ждёт его результат и не открывает свои вкладки, иначе он не укладывается в срок.
    Сбор привязан к текущему event loop; shield: отмена одного ждущего не останавливает сбор для других."""
    loop = asyncio.get_running_loop()
    key = _cache_key(query)
    task = _inflight.get(key)
    if task is None or task.done() or task.get_loop() is not loop:
        task = asyncio.ensure_future(collect_all(browser, query, groups))
        _inflight[key] = task

        def _forget(t: asyncio.Future, k: str = key) -> None:
            if _inflight.get(k) is t:
                del _inflight[k]

        task.add_done_callback(_forget)
    else:
        logging.info(f"[поиск] «{query}» уже идёт, жду общий результат")
    return await asyncio.shield(task)


async def _finish_in_background(query: str, stores, tasks) -> None:
    """Дожидается всех магазинов и кладёт полную выдачу в кэш (если никто не ответил с ошибкой)."""
    try:
        results = await asyncio.gather(*tasks)
        cands, unavailable = _summarize(stores, results)
        search_cache_set(query, cands, unavailable)
        logging.info(f"[кэш] полная выдача доснята: «{query}», карточек {len(cands)}")
    except Exception as e:
        logging.error(f"[кэш] доснятие «{query}» не удалось: {e!r}")
