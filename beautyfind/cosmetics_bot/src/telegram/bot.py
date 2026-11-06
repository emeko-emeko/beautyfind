"""Telegram bot handlers and dispatcher setup."""
import asyncio
import html
import logging
import time
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cosmetics_bot.src.core.models import Candidate, Group
from cosmetics_bot.src.core.utils import (
    COMPARE_BY_UNIT,
    PAGE_SIZE,
    format_money,
    SESSION_TTL,
    RATIO_TOLERANCE,
    parse_query,
    has_specifics,
    MIN_RATIO
)
from cosmetics_bot.src.scraping.stores import STORES, browser_ctx
from cosmetics_bot.src.scraping.search import collect_all
from cosmetics_bot.src.scraping.details import fetch_detail
from cosmetics_bot.src.ui.formatter import build_caption, render_group, render_member, unavailable_line
from cosmetics_bot.src.telegram.sessions import SESSIONS, LAST_TOKEN, new_session
from cosmetics_bot.src.core.db import (
    init_db, add_watch, add_favorite, get_favorites, get_favorite,
    delete_favorite, update_favorite_prices,
)

init_db()

dp = Dispatcher()


def build_groups(cands: list[Candidate]) -> list[Group]:
    d: dict[str, list[Candidate]] = {}
    for c in cands:
        d.setdefault(c.url, []).append(c)
    return [Group(k, v) for k, v in d.items()]


def make_plan(groups_q: list[list[str]], cands: list[Candidate]) -> dict | None:
    if not cands:
        return None

    max_ratio = max(c.ratio for c in cands)
    confident = max_ratio >= 0.5
    eligible = [c for c in cands if c.ratio >= MIN_RATIO]
    logging.info(f"всего={len(cands)}, после_ratio={len(eligible)}")

    groups = build_groups(eligible)
    logging.info(f"групп={len(groups)}")

    if not has_specifics(groups_q, eligible):
        groups.sort(key=lambda g: g.pop_key(), reverse=True)
        return {"kind": "groups", "items": groups, "confident": confident}

    members = sorted(eligible, key=lambda c: (round(c.ratio, 3), c.pop_key()), reverse=True)
    logging.info(f"members={len(members)}")
    return {"kind": "members", "items": members, "confident": confident}


def pick_winner(results: list[dict]) -> dict:
    max_ratio = max(r["ratio"] for r in results)
    eligible = [r for r in results if r["ratio"] >= max_ratio - RATIO_TOLERANCE]
    use_unit = COMPARE_BY_UNIT and all(r.get("volume") for r in eligible)
    key = (lambda r: r["price"] / r["volume"]) if use_unit else (lambda r: r["price"])
    return min(eligible, key=key)


FINALIZE_CONCURRENCY = 4  # одновременных страниц товара: каждая открывает свой контекст браузера


async def finalize_cands(browser, cands: list[Candidate], want_volume: float | None) -> dict | None:
    sem = asyncio.Semaphore(FINALIZE_CONCURRENCY)

    async def one(c: Candidate):
        async with sem:
            return await fetch_detail(browser, c, want_volume)

    details = await asyncio.gather(*(one(c) for c in cands))
    results = [r for r in details if r]
    if not results:
        return None
    return pick_winner(results)


async def send_card(message: Message, caption: str, image_url: str, reply_markup=None):
    if image_url:
        try:
            return await message.answer_photo(photo=image_url, caption=caption, reply_markup=reply_markup)
        except Exception as e:
            logging.warning(f"Не удалось отправить фото, отправляю текстом: {e}")
    return await message.answer(caption, reply_markup=reply_markup)


async def send_product(message: Message, product: dict, confident: bool = True, reply_markup=None):
    return await send_card(message, build_caption(product, confident), product["image_url"], reply_markup=reply_markup)


def product_keyboard(chat_id: int, product: dict):
    """Кнопки «Отслеживать цену» и «В избранное» под карточкой товара."""
    if not product.get("price"):
        return None
    # callback_data не должна превышать 64 байта, поэтому кладём товар в сессию по короткому токену
    prod_token = new_session(chat_id, 3600, product=product)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔔 Отслеживать цену", callback_data=f"watch:{prod_token}")
    kb.button(text="⭐ Добавить в избранное", callback_data=f"fav:{prod_token}")
    kb.adjust(1)
    return kb.as_markup()


async def send_page(message: Message, token: str):
    s = SESSIONS.get(token)
    if not s:
        await message.answer("Список устарел, повторите поиск.")
        return
    items, start = s["items"], s["shown"]
    chunk = items[start:start + PAGE_SIZE]

    for offset, it in enumerate(chunk):
        idx = start + offset
        caption, img = (render_group if s["mode"] == "groups" else render_member)(idx + 1, it)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Выбрать", callback_data=f"pick:{token}:{idx}")
        await send_card(message, caption, img, kb.as_markup())

    s["shown"] = start + len(chunk)
    s["ts"] = time.time()
    remaining = len(items) - s["shown"]
    if remaining > 0:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"➕ Показать ещё {min(PAGE_SIZE, remaining)}", callback_data=f"more:{token}")
        await message.answer(
            f"Показано {s['shown']} из {len(items)}. Остальные: кнопка ниже или команда /more",
            reply_markup=kb.as_markup(),
        )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    names = ", ".join(s.name for s in STORES)
    await message.answer(
        f"👋 Привет! Я ищу парфюмерию и косметику в магазинах: <b>{html.escape(names)}</b>.\n\n"
        "• Точный запрос (<i>ysl libre edp</i>, <i>pupa shine bright</i>): покажу самое выгодное предложение.\n"
        "• Общий запрос (<i>тушь</i>, <i>крем для лица</i>): покажу 3 самых популярных и высоко оценённых "
        "варианта.\n"
        "• Если позиций с одинаковым названием несколько, можно выбрать нужную. "
        "Команда /more показывает следующие 3.\n\n"
        "Цена показывается для максимального объёма. Нужен другой? Добавьте его в запрос: "
        "<i>ysl libre edp 50 мл</i>.\n\n"
        "• /watch — подписаться на отслеживание цены.\n"
        "• /fav — посмотреть избранное.\n"
    )


@dp.message(Command("more"))
async def cmd_more(message: Message):
    token = LAST_TOKEN.get(message.chat.id)
    s = SESSIONS.get(token) if token else None
    if not s:
        await message.answer("Нет активного списка. Отправьте поисковый запрос.")
        return
    if s["shown"] >= len(s["items"]):
        await message.answer("Больше вариантов нет.")
        return
    await send_page(message, token)


@dp.callback_query(F.data.startswith("more:"))
async def on_more(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    s = SESSIONS.get(token)
    if not s:
        await cb.answer("Список устарел, повторите поиск.", show_alert=True)
        return
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    LAST_TOKEN[s["chat_id"]] = token
    if s["shown"] >= len(s["items"]):
        await cb.message.answer("Больше вариантов нет.")
        return
    await send_page(cb.message, token)


def store_currency(store_name: str) -> str:
    return next((s.currency for s in STORES if s.name == store_name), "₸")


def fav_text(f: dict) -> str:
    cur = store_currency(f["store"])
    lines = [f"🏪 <b>{html.escape(f['store'])}</b>", f"🛍 <b>{html.escape(f['title'])}</b>"]
    if f.get("volume"):
        lines.append(f"📏 <b>Объём:</b> {f['volume']:g} мл")
    lines.append("")
    old = f" (<s>{format_money(f['old_price'], cur)}</s>)" if f.get("old_price") else ""
    lines.append(f"💰 <b>Цена:</b> {format_money(f['price'], cur)}{old}")
    if f.get("loyalty_price"):
        lines.append(f"🏷 {format_money(f['loyalty_price'], cur)} при авторизации на сайте")
    return "\n".join(lines)


def fav_keyboard(f: dict):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Открыть на сайте", url=f["product_url"])
    kb.button(text="🔄 Обновить цену", callback_data=f"fref:{f['id']}")
    kb.button(text="❌ Удалить", callback_data=f"fdel:{f['id']}")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(Command("fav"))
async def cmd_fav(message: Message):
    favs = get_favorites(message.chat.id)
    if not favs:
        await message.answer("У вас пока нет избранных товаров.")
        return
    await message.answer(f"⭐ <b>Ваше избранное: {len(favs)}</b>")
    for f in favs:
        await message.answer(fav_text(f), reply_markup=fav_keyboard(f))


@dp.callback_query(F.data.startswith("fdel:"))
async def on_fav_delete(cb: CallbackQuery):
    fav_id = int(cb.data.split(":", 1)[1])
    if not delete_favorite(fav_id, cb.message.chat.id):
        await cb.answer("Товар уже удалён из избранного.", show_alert=True)
        return
    await cb.answer("Удалено из избранного")
    try:
        await cb.message.delete()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("fref:"))
async def on_fav_refresh(cb: CallbackQuery):
    fav_id = int(cb.data.split(":", 1)[1])
    chat_id = cb.message.chat.id
    f = get_favorite(fav_id, chat_id)
    if not f:
        await cb.answer("Товар уже удалён из избранного.", show_alert=True)
        return
    store = next((s for s in STORES if s.name == f["store"]), None)
    if not store:
        await cb.answer("Магазин не найден.", show_alert=True)
        return
    await cb.answer("Обновляю цену...")

    cand = Candidate(store=store, brand="", name=f["title"], type_="", label="", url=f["product_url"],
                     image="", rating=None, reviews=0, list_price=None, price_prefix="", pos=0)
    try:
        async with browser_ctx() as browser:
            res = await fetch_detail(browser, cand, f.get("volume"))
    except Exception as e:
        logging.error(f"Ошибка при обновлении избранного: {e}")
        res = None
    if not res:
        await cb.message.answer("⚠️ Не удалось обновить цену. Попробуйте позже.")
        return

    update_favorite_prices(fav_id, chat_id, res["price"], res.get("old_price"), res.get("loyalty_price"))
    f.update(price=res["price"], old_price=res.get("old_price"), loyalty_price=res.get("loyalty_price"))
    try:
        await cb.message.edit_text(fav_text(f), reply_markup=fav_keyboard(f))
    except Exception:
        pass


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🔍 <b>Как пользоваться ботом:</b>\n\n"
        "• Точный запрос: <i>ysl libre edp</i> — покажу самое выгодное предложение.\n"
        "• Общий запрос: <i>тушь</i> — покажу 3 самых популярных варианта.\n"
        "• /more — показать следующие 3 варианта.\n"
        "• Нажмите ✅ Выбрать под товаром, чтобы получить цену.\n"
        "• Под карточкой товара есть кнопки \"🔔 Отслеживать цену\" и \"⭐ Добавить в избранное\".\n"
        "• /fav — просмотреть избранное.\n"
        "• /watch (пока только кнопка) — подписаться на отслеживание цены."
    )


@dp.callback_query(F.data.startswith("fav:"))
async def on_fav(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    s = SESSIONS.get(token)
    if not s or "product" not in s:
        await cb.answer("Информация о товаре устарела.", show_alert=True)
        return
    prod = s["product"]
    add_favorite(cb.message.chat.id, prod["product_url"], prod["title"], prod["store"], prod["price"],
                 old_price=prod.get("old_price"), loyalty_price=prod.get("loyalty_price"),
                 volume=prod.get("volume"))
    await cb.answer("Добавлено в избранное!", show_alert=False)


@dp.callback_query(F.data.startswith("watch:"))
async def on_watch(cb: CallbackQuery):
    token = cb.data.split(":", 1)[1]
    s = SESSIONS.get(token)
    if not s or "product" not in s:
        await cb.answer("Информация о товаре устарела.", show_alert=True)
        return
    prod = s["product"]
    add_watch(cb.message.chat.id, prod["product_url"], prod["title"], prod["price"])
    await cb.answer("Подписка на цену оформлена!", show_alert=False)


@dp.callback_query(F.data.startswith("pick:"))
async def on_pick(cb: CallbackQuery):
    _, token, idx = cb.data.split(":")
    s = SESSIONS.get(token)
    if not s:
        await cb.answer("Список устарел, повторите поиск.", show_alert=True)
        return
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    msg = cb.message
    item = s["items"][int(idx)]
    want_volume = s.get("want_volume")

    if s["mode"] == "groups":
        members: list[Candidate] = sorted(item.members, key=lambda c: c.pop_key(), reverse=True)
        if len(members) > 1:
            token2 = new_session(s["chat_id"], SESSION_TTL, mode="members", items=members, want_volume=want_volume)
            await msg.answer(
                f"🔀 Нашлось позиций с названием «{html.escape(item.rep.full_title)}»: {len(members)}. "
                "Выберите нужную:"
            )
            await send_page(msg, token2)
            return
        cand = members[0]
    else:
        cand = item

    status = await msg.answer("Получаю цену... ⏳")
    try:
        async with browser_ctx() as browser:
            result = await fetch_detail(browser, cand, want_volume)
    except Exception as e:
        logging.error(f"Ошибка при получении цены: {e}")
        result = None
    try:
        await status.delete()
    except Exception:
        pass

    if not result:
        await msg.answer("⚠️ Не удалось получить цену. Попробуйте ещё раз или откройте товар на сайте.")
        return

    await send_product(msg, result, reply_markup=product_keyboard(s["chat_id"], result))


@dp.message(Command("watch"))
async def cmd_watch(message: Message):
    await message.answer("Для подписки на цену используйте кнопку «Отслеживать» под карточкой товара.")


@dp.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if not query:
        await message.answer("Введите название для поиска.")
        return
    if query.startswith("/"):
        # Незарегистрированная команда: не ищем её как товар
        await message.answer("Неизвестная команда. Список команд: /help")
        return

    groups_q, want_volume = parse_query(query)
    if not groups_q:
        await message.answer("Введите название для поиска.")
        return
    logging.info(f"Группы запроса: {groups_q}, объём: {want_volume}")

    status = await message.answer("Ищу по магазинам... 🔍")

    try:
        async with browser_ctx() as browser:
            cands, unavailable = await collect_all(browser, query, groups_q)
            plan = make_plan(groups_q, cands)

            winner = None
            single_res = None
            if plan and plan["kind"] == "final":
                winner = await finalize_cands(browser, plan["cands"], want_volume)
            elif plan and plan["kind"] == "groups" and len(plan["items"]) == 1 and len(plan["items"][0].members) == 1:
                # Одна позиция: сразу открываем её карточку, в той же сессии браузера
                single_res = await fetch_detail(browser, plan["items"][0].members[0], want_volume)

        try:
            await status.delete()
        except Exception:
            pass

        if unavailable:
            await message.answer(unavailable_line(unavailable))

        if not plan:
            if len(unavailable) == len(STORES):
                # Ни один магазин не ответил: «ничего не нашлось» было бы неверно
                await message.answer("⚠️ Магазины не ответили, попробуйте позже.")
            else:
                await message.answer("😔 К сожалению, по вашему запросу ничего не нашлось.")
            return

        warn = "" if plan["confident"] else "\n⚠️ Точного совпадения нет, показываю ближайшее."

        if plan["kind"] == "final":
            if not winner:
                await message.answer("⚠️ Товар найден, но не удалось получить цену. Попробуйте позже.")
                return
            await send_product(message, winner, plan["confident"],
                               reply_markup=product_keyboard(message.chat.id, winner))
            return

        items = plan["items"]
        if plan["kind"] == "groups":
            if single_res:
                await send_product(message, single_res, plan["confident"],
                                   reply_markup=product_keyboard(message.chat.id, single_res))
                return
            await message.answer(
                "🔎 Запрос общий (нет бренда, модели или оттенка), поэтому показываю самые популярные "
                f"и высоко оценённые варианты. Выберите нужный:{warn}"
            )
            token = new_session(message.chat.id, SESSION_TTL, mode="groups", items=items, want_volume=want_volume)
        else:
            await message.answer(
                f"🔀 Нашлось несколько позиций с одинаковым названием. Выберите нужную:{warn}"
            )
            token = new_session(message.chat.id, SESSION_TTL, mode="members", items=items, want_volume=want_volume)

        await send_page(message, token)

    except Exception as e:
        logging.error(f"Ошибка в боте: {e}")
        try:
            await status.delete()
        except Exception:
            pass
        await message.answer("⚠️ Произошла ошибка при поиске. Попробуйте позже.")
