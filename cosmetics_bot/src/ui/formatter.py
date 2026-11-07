"""UI formatting and message rendering helpers."""

import html
from cosmetics_bot.src.core.models import Candidate, Group
from cosmetics_bot.src.core.utils import format_money, norm


def rating_line(rating: float | None, reviews: int) -> str:
    if not rating:
        return ""
    s = f"⭐ {rating:.1f}"
    if reviews:
        s += f" ({reviews:,} отз.)".replace(",", " ")
    return s


def unavailable_line(names: list[str]) -> str:
    """Строки о магазинах, которые не ответили. Пустой список — пустая строка."""
    return "\n".join(f"⚠️ {html.escape(n)}: недоступен" for n in names)


def build_caption(p: dict, confident: bool = True) -> str:
    cur = p["currency"]
    lines = [f"🏪 <b>{html.escape(p['store'])}</b>", f"🛍 <b>{html.escape(p['title'])}</b>"]
    if p.get("subtitle"):
        lines.append(f"<i>{html.escape(p['subtitle'])}</i>")
    r = rating_line(p.get("rating"), p.get("reviews", 0))
    if r:
        lines.append(r)
    lines.append("")

    if p.get("volume"):
        lines.append(f"📏 <b>Объём:</b> {p['volume']:g} {html.escape(p.get('unit') or 'мл')}")

    price = (p.get("price_prefix") or "") + format_money(p["price"], cur)
    old = f" (<s>{format_money(p['old_price'], cur)}</s>)" if p.get("old_price") else ""
    lines.append(f"💰 <b>Цена:</b> {price}{old}")

    if p.get("volume") and (p.get("unit") or "мл") == "мл" and p.get("price"):
        per_ml = round(p["price"] / p["volume"])
        lines.append(f"🧮 <b>Цена за 1 мл:</b> {format_money(per_ml, cur)}")

    if p.get("loyalty_price"):
        lines.append(f"🏷 {format_money(p['loyalty_price'], cur)} при авторизации на сайте")

    lines.append("")
    url = html.escape(p["product_url"], quote=True)
    lines.append(f"🔗 <a href='{url}'>Смотреть на сайте</a>")

    # Кнопки для подписки и избранного
    price = p.get("price")
    if price:
        lines.append(f"\n/watch — отслеживать цену")
        lines.append(f"/fav — добавить в избранное")

    if not confident:
        lines.append("\n⚠️ Точного совпадения не нашлось, возможно, это не тот товар.")
    return "\n".join(lines)


def render_group(i: int, g: Group) -> tuple[str, str]:
    rep = g.rep
    lines = [f"<b>{i}. {html.escape(rep.full_title)}</b>"]
    if rep.type_ and rep.store.show_type:
        lines.append(f"<i>{html.escape(rep.type_)}</i>")
    lines.append(f"🏪 {html.escape(rep.store.name)}")
    r = rating_line(rep.rating, rep.reviews)
    if r:
        lines.append(r)
    prices = [m.list_price for m in g.members if m.list_price]
    if prices:
        lines.append(f"💰 от {format_money(min(prices), rep.store.currency)}")
    if len(g.members) > 1:
        lines.append(f"🔀 Вариантов (оттенок/объём): {len(g.members)}")
    return "\n".join(lines), rep.image


def render_member(i: int, c: Candidate) -> tuple[str, str]:
    lines = [f"<b>{i}. {html.escape(c.full_title)}</b>"]
    detail = c.label if c.label and norm(c.label) != norm(c.full_title) else c.type_
    if detail:
        lines.append(f"<i>{html.escape(detail)}</i>")
    lines.append(f"🏪 {html.escape(c.store.name)}")
    r = rating_line(c.rating, c.reviews)
    if r:
        lines.append(r)
    if c.list_price:
        lines.append(f"💰 от {format_money(c.list_price, c.store.currency)}")
    return "\n".join(lines), c.image
