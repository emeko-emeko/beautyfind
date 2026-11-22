"""Два написания запроса (кириллица и латиница), запись 037.

Поведение: search_variants (словарь TERM_PAIRS, SYNONYMS и транслит), общий ключ кэша в
search._cache_key, объединение выдачи по написаниям в search._list_store_variants.
Браузер не нужен: list_store подменён.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cosmetics_bot.src.core.models import Store
from cosmetics_bot.src.core.utils import search_variants
from cosmetics_bot.src.scraping import search
from cosmetics_bot.src.scraping.search import (
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    _list_store_variants,
)


def make_store(name: str) -> Store:
    return Store(
        name=name,
        base_url="https://example.test",
        search_url="https://example.test/search/?q={query}",
        card=".card",
        brand=".brand",
        name_sel=".name",
        price=".price",
        images=[],
        link="a",
        detail="monamie",
        detail_ready=".ready",
    )


def _fc(url: str):
    return SimpleNamespace(url=url)


class SearchVariantsTests(unittest.TestCase):
    def test_cyrillic_query_gets_latin_pair_from_dictionary(self):
        self.assertEqual(search_variants("телескопик"), ["телескопик", "telescopic"])

    def test_latin_query_gets_cyrillic_pair_from_dictionary(self):
        self.assertEqual(search_variants("telescopic"), ["telescopic", "телескопик"])

    def test_unknown_cyrillic_word_is_transliterated(self):
        self.assertEqual(search_variants("крем для рук"), ["крем для рук", "cream dlya ruk"])

    def test_brand_from_synonyms_gets_pair(self):
        self.assertEqual(search_variants("мейбелин")[1], "maybelline")

    def test_query_without_pair_has_single_variant(self):
        self.assertEqual(search_variants("le labo"), ["le labo"])

    def test_empty_query_has_no_variants(self):
        self.assertEqual(search_variants("   "), [])


class CacheKeyTests(unittest.TestCase):
    def test_both_spellings_share_one_cache_key(self):
        self.assertEqual(search._cache_key("телескопик"), search._cache_key("telescopic"))
        self.assertEqual(search._cache_key("Телескопик"), "telescopic|телескопик")


class ListStoreVariantsTests(unittest.TestCase):
    def run_variants(self, answers: dict[str, tuple[str, list]]):
        store = make_store("Mon Amie")

        async def fake(browser, st, query, groups):
            return answers[query]

        with patch.object(search, "list_store", side_effect=fake):
            return asyncio.run(_list_store_variants(MagicMock(), store, list(answers), []))

    def test_both_spellings_always_requested_even_with_many_cards(self):
        # EME-7, пункт 3: оба написания запускаются параллельно, порога нет
        store = make_store("Mon Amie")
        calls = []
        many = [_fc(f"u{i}") for i in range(10)]

        async def fake(browser, st, query, groups):
            calls.append(query)
            return STATUS_OK, many

        with patch.object(search, "list_store", side_effect=fake):
            status, found = asyncio.run(
                _list_store_variants(MagicMock(), store, ["телескопик", "telescopic"], [])
            )
        self.assertEqual(sorted(calls), ["telescopic", "телескопик"])
        self.assertEqual(len(found), 10)

    def test_fewer_cards_on_first_spelling_queries_second(self):
        store = make_store("Mon Amie")
        calls = []

        async def fake(browser, st, query, groups):
            calls.append(query)
            return STATUS_OK, [_fc("a")]

        with patch.object(search, "list_store", side_effect=fake):
            asyncio.run(_list_store_variants(MagicMock(), store, ["телескопик", "telescopic"], []))
        self.assertEqual(sorted(calls), ["telescopic", "телескопик"])

    def test_results_of_both_spellings_are_merged_by_url(self):
        status, found = self.run_variants({
            "телескопик": (STATUS_OK, [_fc("a")]),
            "telescopic": (STATUS_OK, [_fc("a"), _fc("b")]),
        })
        self.assertEqual(status, STATUS_OK)
        self.assertEqual(sorted(c.url for c in found), ["a", "b"])

    def test_empty_plus_ok_is_ok(self):
        status, found = self.run_variants({
            "телескопик": (STATUS_EMPTY, []),
            "telescopic": (STATUS_OK, [_fc("b")]),
        })
        self.assertEqual(status, STATUS_OK)
        self.assertEqual([c.url for c in found], ["b"])

    def test_unavailable_plus_empty_is_unavailable_not_empty(self):
        status, found = self.run_variants({
            "телескопик": (STATUS_UNAVAILABLE, []),
            "telescopic": (STATUS_EMPTY, []),
        })
        self.assertEqual(status, STATUS_UNAVAILABLE)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
