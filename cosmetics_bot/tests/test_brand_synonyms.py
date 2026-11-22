"""Бренды, написанные по-русски (SYNONYMS и TERM_PAIRS, запись 067): один и тот же запрос
в кириллице и латинице даёт одни и те же группы и один ключ кэша.

Модули: core/utils.py (SYNONYMS, TERM_PAIRS, search_variants, parse_query),
scraping/search.py (_cache_key). Похожие тесты: test_search_variants.py, test_palette_query.py.
"""

import unittest

from cosmetics_bot.src.core.utils import parse_query, search_variants
from cosmetics_bot.src.scraping import search


class BrandSynonymTests(unittest.TestCase):
    def test_mac_cyrillic_gets_latin_pair(self):
        self.assertEqual(search_variants("мак помада"), ["мак помада", "mac lipstick"])

    def test_nars_cyrillic_and_latin_share_cache_key(self):
        self.assertEqual(search._cache_key("нарс"), search._cache_key("nars"))

    def test_urban_decay_spellings_share_one_group(self):
        groups, _ = parse_query("урбан декей палетка")
        brand = groups[0]
        self.assertIn("urban decay", brand)
        self.assertIn("урбан декей", brand)

    def test_fenty_cyrillic_query_matches_latin_brand_alt(self):
        groups, _ = parse_query("фенти тушь")
        self.assertIn("fenty", groups[0])

    def test_existing_brand_order_kept(self):
        # Старое соответствие не должно сдвинуться: «мейбелин» → maybelline
        self.assertEqual(search_variants("мейбелин")[1], "maybelline")


if __name__ == "__main__":
    unittest.main()
