import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from local_autocomplete import CompactIndex, query_variants, search_compact_index  # noqa: E402


class LocalAutocompleteRankingTestCase(unittest.TestCase):
    def test_japanese_c_query_variants_only_expand_cu_and_co(self):
        self.assertEqual(query_variants("ceshi"), ["ceshi"])
        self.assertEqual(query_variants("caisha"), ["caisha"])
        self.assertEqual(query_variants("cohii"), ["cohii", "kohii"])

    def test_ceshi_prefers_chinese_when_preferred_language_is_zh(self):
        index = CompactIndex(
            aliases=["ceshi", "keshi"],
            postings=[
                [
                    (0, "cc-cedict:pinyin"),
                    (1, "jmdict:romaji-fuzzy"),
                ],
                [
                    (1, "jmdict:romaji-fuzzy"),
                ],
            ],
            entries=[
                {
                    "surface": "\u6d4b\u8bd5",
                    "reading": "c\u00e8 sh\u00ec",
                    "meaning": "- test",
                    "lang": "zh",
                },
                {
                    "surface": "\u6d88\u3057",
                    "reading": "\u3051\u3057",
                    "meaning": "- erasing",
                    "lang": "ja",
                },
            ],
            meta={"providers": {"zh": "cc-cedict", "ja": "jmdict", "en": "cmudict"}},
        )

        results = search_compact_index(index, "ceshi", preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "\u6d4b\u8bd5")
        self.assertEqual(results[0]["reading"], "c\u00e8 sh\u00ec")
        self.assertEqual(results[0]["meaning"], "- test")
        self.assertEqual(results[1]["surface"], "\u6d88\u3057")
        self.assertEqual(results[1]["reading"], "\u3051\u3057")

    def test_cehsi_matches_ceshi_via_transposition_neighbor(self):
        index = CompactIndex(
            aliases=["ceshi"],
            postings=[
                [
                    (0, "cc-cedict:pinyin"),
                ],
            ],
            entries=[
                {
                    "surface": "\u6d4b\u8bd5",
                    "reading": "c\u00e8 sh\u00ec",
                    "meaning": "- test",
                    "lang": "zh",
                },
            ],
            meta={},
        )

        results = search_compact_index(index, "cehsi", preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "\u6d4b\u8bd5")
        self.assertEqual(results[0]["reading"], "c\u00e8 sh\u00ec")

    def test_mixed_query_prefers_full_coverage_candidate_over_partial_hits(self):
        query = "\u65e0\u5904buzai"
        index = CompactIndex(
            aliases=["buzai", "\u65e0\u5904", "\u65e0\u5904buzai"],
            postings=[
                [
                    (0, "cc-cedict:pinyin"),
                ],
                [
                    (1, "cc-cedict:surface"),
                ],
                [
                    (2, "cc-cedict:mixed"),
                ],
            ],
            entries=[
                {
                    "surface": "\u4e0d\u5728",
                    "reading": "b\u00f9 z\u00e0i",
                    "meaning": "- not to be present",
                    "lang": "zh",
                },
                {
                    "surface": "\u65e0\u5904",
                    "reading": "w\u00fa ch\u00f9",
                    "meaning": "- nowhere",
                    "lang": "zh",
                },
                {
                    "surface": "\u65e0\u5904\u4e0d\u5728",
                    "reading": "w\u00fa ch\u00f9 b\u00f9 z\u00e0i",
                    "meaning": "- to be everywhere",
                    "lang": "zh",
                },
            ],
            meta={},
        )

        results = search_compact_index(index, query, preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "\u65e0\u5904\u4e0d\u5728")
        self.assertEqual(results[1]["surface"], "\u4e0d\u5728")
        self.assertEqual(results[2]["surface"], "\u65e0\u5904")

    def test_single_segment_query_keeps_partial_term_ordering(self):
        index = CompactIndex(
            aliases=["buzai", "buzaihu"],
            postings=[
                [
                    (0, "cc-cedict:pinyin"),
                    (1, "cc-cedict:pinyin"),
                ],
                [
                    (1, "cc-cedict:pinyin"),
                ],
            ],
            entries=[
                {
                    "surface": "\u4e0d\u5728",
                    "reading": "b\u00f9 z\u00e0i",
                    "meaning": "- not to be present",
                    "lang": "zh",
                },
                {
                    "surface": "\u4e0d\u5728\u4e4e",
                    "reading": "b\u00f9 z\u00e0i hu",
                    "meaning": "- not to care",
                    "lang": "zh",
                },
            ],
            meta={},
        )

        results = search_compact_index(index, "buzai", preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "\u4e0d\u5728")


if __name__ == "__main__":
    unittest.main()
