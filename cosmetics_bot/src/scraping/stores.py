""""Описания магазинов и контекст браузера."""

import asyncio
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from cosmetics_bot.src.core.models import Store
from cosmetics_bot.src.core.utils import EUR_TO_KZT

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

STORES = [
    Store(
        name="Mon Amie",
        base_url="https://www.monamie.kz",
        search_url="https://www.monamie.kz/search/?q={query}",
        card=".catalog-block__list > .catalog-block__item > .catalog-item.js-catalog-item",
        brand=".catalog-item__brand a",
        name_sel=".catalog-item__title a",
        name_from_attr=True,
        price=".price-box__item:not(.price-box__item--old)",
        images=[".catalog-item__image img"],
        link="a.catalog-item__image",
        detail="monamie",
        detail_ready=".js-product-detail__price-now",
    ),
    Store(
        name="Золотое Яблоко",
        base_url="https://goldapple.kz",
        search_url="https://goldapple.kz/catalogsearch/result/?q={query}",
        # Каждый товар в выдаче оборачивается в div[data-scroll-id].
        # Тип карточки (вертикальная/горизонтальная) не важен.
        card="main [data-scroll-id]",
        brand="[class*='product-card-name__brand']",
        name_sel="[class*='product-card-name__name']",
        type_sel=(
            "[class*='product-card-vertical__type'], "
            "[class*='product-card-horizontal__type']"
        ),
        label_sel="img[class*='product-card-media-item__img']",
        rating_sel="[itemprop='aggregateRating'] meta[itemprop='ratingValue']",
        reviews_sel="[itemprop='aggregateRating'] meta[itemprop='reviewCount']",
        show_type=True,
        price="[class*='product-card-price-row__item-actual']",
        images=["img[class*='product-card-media-item__img']", "picture img"],
        link="a[href]",
        detail="goldapple",
        detail_ready="[data-test-id='price-info-block']",
    ),
    Store(
        name="Французский дом",
        base_url="https://french-house.kz",
        search_url="https://french-house.kz/search/index.php?q={query}",
        # Бренда в карточке нет: он входит в название товара.
        card=".goodItem",
        brand="",
        name_sel=".goodCard .name",
        price=".cardCost",
        images=[".imageWrapper img"],
        link=".goodCard > a",
        detail="frenchhouse",
        detail_ready="#price",
    ),
    Store(
        name="Yves Rocher",
        base_url="https://www.yves-rocher.kz",
        search_url="https://www.yves-rocher.kz/search?query={query}",
        # Карточка помечена data-product-card-id. Классы с хешами, поэтому ищем по префиксу.
        card="[data-product-card-id]",
        brand="",
        name_sel="[class*='SimpleProductCard_simpleProductTitle']",
        # Старая цена внутри того же блока: берём только собственный текст элемента.
        price="[class*='PriceDisplay_price']",
        price_own_text=True,
        images=["img"],
        link="a[href^='/product/']",
        detail="yvesrocher",
        detail_ready="[class*='ProductCardSidebar_priceDisplay']",
    ),
    Store(
        name="Код де ви",
        base_url="https://cdv.kz",
        search_url="https://cdv.kz/women/search?searchQuery={query}",
        # Классы с хешами (например _6hPivq_), поэтому ищем по части имени.
        card="div:has(> a[href^='/item/'])",
        brand="[class*='_brand']",
        name_sel="[class*='_title'] p",
        price="[class*='_currentPriceText']",
        images=["img"],
        link="a[href^='/item/']",
        detail="",
        detail_ready="",
    ),
    Store(
        name="Viled",
        base_url="https://viled.kz",
        search_url="https://viled.kz/women/search?searchQuery={query}",
        card="div:has(> a[href^='/item/'])",
        brand="[class*='_brand']",
        name_sel="[class*='_title'] p",
        price="[class*='_currentPriceText']",
        images=["img"],
        link="a[href^='/item/']",
        detail="",
        detail_ready="",
    ),
]


# Магазины, которые ещё не подключены к боту: не хватает адреса поиска.
# Чтобы подключить, заполните search_url и перенесите запись в STORES.
PENDING_STORES = [
    Store(
        name="Space NK",
        base_url="https://www.spacenk.com",
        search_url="",  # TODO: адрес поиска
        card=".product-tile",
        brand="h5.mb-1",
        name_sel=".pdp-link a",
        price=".price .value",
        images=["img.tile-image"],
        link="a.link[href]",
        detail="",
        detail_ready="",
    ),
    Store(
        name="Cult Beauty",
        base_url="https://www.cultbeauty.com",
        search_url="",  # TODO: адрес поиска
        card="product-card-wrapper",
        brand="",
        name_sel="a.product-item-title",
        price="p.price",
        images=["img.item-image"],
        link="a.product-item[href]",
        detail="",
        detail_ready="",
        price_currency="€",
        fx_to_kzt=EUR_TO_KZT,
    ),
]


_PW = None
_BROWSER = None
_BROWSER_LOCK = asyncio.Lock()


@asynccontextmanager
async def browser_ctx():
    """Один Chromium на процесс: запуск занимает секунду, поэтому не делаем его на каждый запрос."""
    global _PW, _BROWSER
    async with _BROWSER_LOCK:
        if _BROWSER is None or not _BROWSER.is_connected():
            _PW = await async_playwright().start()
            _BROWSER = await _PW.chromium.launch(headless=True)
    yield _BROWSER