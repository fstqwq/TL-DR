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
                    (0, 0, 450),  # 测试 via pinyin
                    (1, 1, 870),  # けし via fuzzy romaji alias
                ],
                [
                    (1, 1, 870),  # same Japanese candidate via generated query variant
                ],
            ],
            surfaces=[
                ("测试", "zh"),
                ("けし", "ja"),
            ],
            sources=[
                "cc-cedict:pinyin",
                "jmdict:romaji-fuzzy",
            ],
            meta={},
        )

        results = search_compact_index(index, "ceshi", preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "测试")
        self.assertEqual(results[1]["surface"], "けし")

    def test_cehsi_matches_ceshi_via_transposition_neighbor(self):
        index = CompactIndex(
            aliases=["ceshi"],
            postings=[
                [
                    (0, 0, 450),
                ],
            ],
            surfaces=[
                ("测试", "zh"),
            ],
            sources=[
                "cc-cedict:pinyin",
            ],
            meta={},
        )

        results = search_compact_index(index, "cehsi", preferred_language="zh", limit=5)

        self.assertEqual(results[0]["surface"], "测试")


if __name__ == "__main__":
    unittest.main()
