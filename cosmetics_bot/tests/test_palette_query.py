"""Запрос «палетка диор»: выдача только палеток, и одинаковый запрос в разной транслитерации
даёт одинаковую выдачу (ключ кэша, группы релевантности, отбор в make_plan).

Модули: core/utils.py (search_variants, parse_query, token_alts), telegram/bot.py (make_plan).
Существующие тесты: test_search_variants.py (написания и кэш), test_shade_search.py (make_plan).
"""

import unittest

from cosmetics_bot.src.core.models import Candidate
from cosmetics_bot.src.core.utils import (
    make_hay,
    parse_query,
    relevance,
    search_variants,
    token_alts,
)
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.stores import STORES
from cosmetics_bot.src.telegram.bot import make_plan


def _cand(name: str, brand: str, url: str, groups) -> Candidate:
    c = Candidate(
        store=STORES[0], brand=brand, name=name, type_="", label=name, url=url, image="",
        rating=None, reviews=0, list_price=1000, price_prefix="", pos=0,
    )
    c.hay = make_hay(f"{brand} {name}", brand)
    c.ratio = relevance(groups, c.hay)
    c.shade_codes = None
    return c


class PaletteSelectionTests(unittest.TestCase):
    def setUp(self):
        self.groups, _ = parse_query("палетка диор")
        self.dior_palette = _cand("Diorshow Eyeshadow Palette", "Dior", "u1", self.groups)
        self.dior_palette_ru = _cand("Палетка теней", "Dior", "u2", self.groups)
        self.dior_lip = _cand("Dior Addict Lip Maximizer Блеск-плампер", "Dior", "u3", self.groups)
        self.dior_perfume = _cand("Miss Dior Eau de Parfum Парфюмерная вода", "Dior", "u4", self.groups)
        self.other_palette = _cand("Huda Beauty Eyeshadow Palette", "Huda", "u5", self.groups)

    def test_palette_word_is_a_category_group(self):
        # Раньше «палетка» не была категорией, и её не требовали в карточке
        self.assertTrue(any("palette" in g for g in self.groups))
        plan = make_plan(self.groups, [self.dior_lip, self.dior_palette])
        self.assertEqual([c.url for c in plan["items"]], ["u1"])

    def test_dior_items_without_palette_are_dropped(self):
        cands = [self.dior_lip, self.dior_perfume, self.dior_palette]
        plan = make_plan(self.groups, cands)
        self.assertEqual([c.url for c in plan["items"]], ["u1"])

    def test_dior_palette_ranks_above_other_brand_palette(self):
        plan = make_plan(self.groups, [self.other_palette, self.dior_palette])
        self.assertEqual([c.url for c in plan["items"]], ["u1", "u5"])

    def test_russian_palette_card_matches_query_word(self):
        self.assertEqual(self.dior_palette_ru.ratio, 1.0)

    def test_query_without_category_keeps_brand_only_items(self):
        groups, _ = parse_query("диор")
        lip = _cand("Dior Addict Lip Maximizer", "Dior", "u3", groups)
        plan = make_plan(groups, [lip])
        self.assertEqual([c.url for c in plan["items"]], ["u3"])


class TranslitConsistencyTests(unittest.TestCase):
    def test_same_query_in_all_spellings_has_one_cache_key(self):
        keys = {
            search._cache_key(q)
            for q in ("палетка диор", "paletka dior", "palette dior", "Палетка Диор")
        }
        self.assertEqual(len(keys), 1)

    def test_latin_translit_word_gets_english_store_query(self):
        self.assertEqual(search_variants("paletka dior")[0], "palette dior")

    def test_cyrillic_query_gets_english_pair(self):
        self.assertEqual(search_variants("палетка диор"), ["палетка диор", "palette dior"])

    def test_token_alts_contains_dictionary_pair_both_ways(self):
        self.assertIn("palette", token_alts("палетка"))
        self.assertIn("палетка", token_alts("palette"))
        self.assertIn("palette", token_alts("paletka"))

    def test_group_for_latin_query_matches_cyrillic_card_name(self):
        groups, _ = parse_query("palette dior")
        c = _cand("Палетка теней Dior", "Dior", "x", groups)
        self.assertEqual(c.ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
