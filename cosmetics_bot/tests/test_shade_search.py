"""Поиск по коду оттенка: разбор запроса, коды из карточек, фильтр выдачи, кэш, проверка страниц.

Модули: core/shade.py, telegram/bot.py (make_plan), scraping/search.py (кэш), scraping/shade_probe.py.
Старых тестов на эти функции с кодами не было.
"""

import unittest
from unittest.mock import patch

from cosmetics_bot.src.core.models import Candidate
from cosmetics_bot.src.core.shade import codes_in, matches_shade, split_shade
from cosmetics_bot.src.core.utils import make_hay
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping import shade_probe
from cosmetics_bot.src.scraping.stores import STORES
from cosmetics_bot.src.telegram.bot import make_plan


def _cand(codes, ratio=1.0, store=None, url="https://x.test/p", name="Помада"):
    store = store or STORES[0]
    c = Candidate(
        store=store, brand="", name=name, type_="", label=name, url=url, image="",
        rating=None, reviews=0, list_price=1000, price_prefix="", pos=0,
    )
    c.ratio = ratio
    c.shade_codes = codes
    c.hay = make_hay(name)
    return c


class SplitShadeTests(unittest.TestCase):
    def test_number_code_is_taken_out(self):
        self.assertEqual(split_shade("помада 205"), (["205"], "помада"))

    def test_volume_is_not_a_code(self):
        self.assertEqual(split_shade("помада 30 мл"), ([], "помада 30 мл"))

    def test_hex_needs_hash(self):
        self.assertEqual(split_shade("помада #b22222"), (["#b22222"], "помада"))
        self.assertEqual(split_shade("помада b22222"), ([], "помада b22222"))

    def test_leading_zeros_and_letters(self):
        self.assertEqual(split_shade("помада 001")[0], ["1"])
        self.assertEqual(split_shade("помада M02")[0], ["m02"])

    def test_code_only_query_leaves_empty_rest(self):
        self.assertEqual(split_shade("205"), (["205"], ""))

    def test_name_word_is_not_a_code(self):
        self.assertEqual(split_shade("помада ruby woo"), ([], "помада ruby woo"))


class CodesInTests(unittest.TestCase):
    def test_yves_rocher_card_name(self):
        self.assertEqual(
            codes_in("Губная Помада ROUGE BOTANIQUE Сатиновая – 130. Нюдовая Роза, 3,5 г"), ("130",)
        )

    def test_gold_apple_title_with_volume(self):
        self.assertEqual(codes_in("Pupa Губная помада Miss 201, Cinderella 2.4 мл"), ("201",))

    def test_no_code_in_title_with_volume_only(self):
        self.assertEqual(codes_in("MAC Губная помада MACximal Matte Lipstick Warm teddy 3.5 г"), ())

    def test_volume_with_space_after_comma_is_not_a_code(self):
        # Yves Rocher: «... № 110. ..., 3, 5 г» — «3» не код оттенка (запись 062)
        self.assertEqual(codes_in("ROUGE BOTANIQUE Помада № 110. Оттенок, 3, 5 г"), ("110",))

    def test_hex_in_text(self):
        self.assertEqual(codes_in("Оттенок #B22222"), ("#b22222",))

    def test_matches_shade(self):
        self.assertTrue(matches_shade(("130",), ["130"]))
        self.assertFalse(matches_shade(("140",), ["130"]))
        self.assertFalse(matches_shade(None, ["130"]))
        self.assertFalse(matches_shade((), ["130"]))


class MakePlanShadeTests(unittest.TestCase):
    def test_keeps_only_matching_shade(self):
        a, b, c = _cand(("205",)), _cand(("130",)), _cand(None)
        plan = make_plan([["помада"]], [a, b, c], ["205"])
        self.assertEqual(plan["kind"], "members")
        self.assertEqual(plan["items"], [a])
        self.assertEqual(plan["unknown"], 1)
        self.assertEqual(plan["wanted"], ["205"])

    def test_none_matched_returns_shade_none(self):
        b, c = _cand(("130",)), _cand(None)
        plan = make_plan([["помада"]], [b, c], ["205"])
        self.assertEqual(plan["kind"], "shade_none")
        self.assertEqual(plan["checked"], 1)
        self.assertEqual(plan["unknown"], 1)

    def test_without_shade_plan_unchanged(self):
        plan = make_plan([["помада"]], [_cand(("205",))])
        self.assertNotEqual(plan["kind"], "shade_none")
        self.assertNotIn("wanted", plan)


class CachePayloadTests(unittest.TestCase):
    def test_shade_codes_survive_round_trip(self):
        cands = [_cand(("205", "#b22222")), _cand(None, url="https://x.test/q")]
        back = search._from_payload(search._to_payload(cands))
        self.assertEqual(back[0].shade_codes, ("205", "#b22222"))
        self.assertIsNone(back[1].shade_codes)

    def test_old_payload_without_field_reads_as_unknown(self):
        payload = search._to_payload([_cand(("205",))])
        for d in payload:
            d.pop("shade_codes")
        self.assertIsNone(search._from_payload(payload)[0].shade_codes)


class _Resp:
    def __init__(self, status):
        self.status = status


class _FakePage:
    def __init__(self, status, title, shades):
        self._status, self._title, self._shades = status, title, shades

    async def goto(self, url, **kw):
        return _Resp(self._status)

    async def title(self):
        return self._title

    async def wait_for_selector(self, sel, **kw):
        return None

    async def evaluate(self, js, args):
        return self._shades


class _FakeCtx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page

    async def close(self):
        return None


async def _open(ctx):
    return ctx


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_codes_from_product_page(self):
        store = next(s for s in STORES if s.shade_sel)
        cand = _cand(None, store=store, url="https://x.test/p")
        page = _FakePage(200, "Товар", ["112 Eliza Ginger", "217 Valeria Rose"])
        with patch.object(shade_probe, "_open_context", lambda b, bi: _open(_FakeCtx(page))):
            n = await shade_probe.probe_shades(object(), [cand])
        self.assertEqual(n, 1)
        self.assertEqual(cand.shade_codes, ("112", "217"))

    async def test_blocked_page_stays_unknown(self):
        store = next(s for s in STORES if s.shade_sel)
        cand = _cand(None, store=store, url="https://x.test/p")
        page = _FakePage(403, "Just a moment...", [])
        with patch.object(shade_probe, "_open_context", lambda b, bi: _open(_FakeCtx(page))):
            await shade_probe.probe_shades(object(), [cand])
        self.assertIsNone(cand.shade_codes)

    async def test_store_without_selector_is_not_probed(self):
        store = next(s for s in STORES if not s.shade_sel)
        cand = _cand(None, store=store)
        n = await shade_probe.probe_shades(object(), [cand])
        self.assertEqual(n, 0)
        self.assertIsNone(cand.shade_codes)


if __name__ == "__main__":
    unittest.main()
