import gzip
import lzma
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
SCRIPT_DIR = API_DIR / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from build_autocomplete_index import (  # noqa: E402
    arpabet_to_ipa,
    build_compact_index_from_entries,
    iter_cedict_entries,
    iter_cmudict_entries,
    iter_jmdict_entries,
    normalize_pinyin,
)
from local_autocomplete import load_compact_index, search_compact_index  # noqa: E402


class BuildAutocompleteIndexTestCase(unittest.TestCase):
    def test_normalize_pinyin_preserves_tones_for_display(self):
        self.assertEqual(normalize_pinyin("ce4 shi4"), ("c\u00e8 sh\u00ec", "ce shi", "ce shi"))
        self.assertEqual(normalize_pinyin("lu:4"), ("l\u01dc", "lu", "lv"))

    def test_arpabet_to_ipa_converts_stress(self):
        self.assertEqual(arpabet_to_ipa("T EH1 S T"), "/t\u02c8\u025bst/")
        self.assertEqual(arpabet_to_ipa("R IY1 D"), "/r\u02c8id/")

    def test_iter_cmudict_entries_merges_alternate_pronunciations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cmudict.dict"
            path.write_text(
                "\n".join(
                    [
                        "READ  R IY1 D",
                        "READ(1)  R EH1 D",
                        "TEST  T EH1 S T",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("build_autocomplete_index.wordfreq_score", side_effect=lambda word, lang: 7.0 if word == "read" else 6.0):
                entries = list(iter_cmudict_entries(path))

        entry, score = entries[0]
        self.assertEqual(entry["surface"], "read")
        self.assertEqual(entry["reading"], "/r\u02c8id/ /r\u02c8\u025bd/")
        self.assertEqual(entry["lang"], "en")
        self.assertEqual(entry["meaning"], "")
        self.assertEqual(entry["aliases"]["cmudict:word"], ["read"])
        self.assertEqual(score, 7.0)

    def test_iter_cedict_entries_keeps_meaning_and_alias_groups(self):
        payload = "測試 测试 [ce4 shi4] /to test/to examine/\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cc-cedict.txt.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(payload)

            with patch("build_autocomplete_index.wordfreq_score", return_value=5.0):
                entries = list(iter_cedict_entries(path))

        entry, score = entries[0]
        self.assertEqual(entry["surface"], "\u6d4b\u8bd5")
        self.assertEqual(entry["reading"], "c\u00e8 sh\u00ec")
        self.assertEqual(entry["lang"], "zh")
        self.assertEqual(entry["meaning"], "- to test\n- to examine")
        self.assertIn("cc-cedict:surface", entry["aliases"])
        self.assertIn("cc-cedict:pinyin", entry["aliases"])
        self.assertEqual(score, 5.0)

    def test_iter_jmdict_entries_keeps_surface_reading_romaji_and_meaning(self):
        payload = """<?xml version="1.0" encoding="UTF-8"?>
<JMdict>
  <entry>
    <k_ele><keb>\u79c1</keb></k_ele>
    <r_ele><reb>\u308f\u305f\u3057</reb></r_ele>
    <sense>
      <pos>pronoun</pos>
      <gloss>I</gloss>
      <gloss>me</gloss>
    </sense>
  </entry>
</JMdict>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "JMdict_e.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(payload)

            with patch("build_autocomplete_index.wordfreq_score", return_value=5.0):
                entries = list(iter_jmdict_entries(path))

        entry, score = entries[0]
        self.assertEqual(entry["surface"], "\u79c1")
        self.assertEqual(entry["reading"], "\u308f\u305f\u3057")
        self.assertEqual(entry["lang"], "ja")
        self.assertEqual(entry["meaning"], "- (pronoun) I; me")
        self.assertIn("\u79c1", entry["aliases"]["jmdict:surface"])
        self.assertIn("\u308f\u305f\u3057", entry["aliases"]["jmdict:reading"])
        self.assertIn("watashi", entry["aliases"]["jmdict:romaji"])
        self.assertEqual(score, 5.0)

    def test_build_compact_index_from_entries_writes_packed_payload(self):
        entries = [
            (
                {
                    "surface": "\u6d4b\u8bd5",
                    "reading": "c\u00e8 sh\u00ec",
                    "lang": "zh",
                    "meaning": "- test",
                    "aliases": {
                        "cc-cedict:surface": ["\u6d4b\u8bd5"],
                        "cc-cedict:pinyin": ["ce shi"],
                    },
                },
                6.0,
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "lexicon.json.xz"
            meta = build_compact_index_from_entries(entries, path, meta_extra={"builder": {"ok": True}})
            with lzma.open(path, "rb") as handle:
                payload = pickle.load(handle)
            index = load_compact_index(path)
            results = search_compact_index(index, "ceshi", preferred_language="zh", limit=3)

        self.assertEqual(meta["version"], 4)
        self.assertEqual(payload["format"], "packed-index-v1")
        self.assertIn("providers", payload["meta"])
        self.assertIn("postings", payload)
        self.assertEqual(payload["entries"]["surfaces"][0], "\u6d4b\u8bd5")
        self.assertEqual(results[0]["surface"], "\u6d4b\u8bd5")
        self.assertEqual(results[0]["reading"], "c\u00e8 sh\u00ec")


if __name__ == "__main__":
    unittest.main()
