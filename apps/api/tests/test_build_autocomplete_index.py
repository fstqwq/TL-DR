import gzip
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

from build_autocomplete_index import arpabet_to_ipa, iter_cmudict_rows, iter_jmdict_rows, normalize_pinyin  # noqa: E402


class BuildAutocompleteIndexTestCase(unittest.TestCase):
    def test_normalize_pinyin_preserves_tones_for_display(self):
        self.assertEqual(normalize_pinyin("ce4 shi4"), ("cè shì", "ce shi", "ce shi"))
        self.assertEqual(normalize_pinyin("lu:4"), ("lǜ", "lu", "lv"))

    def test_arpabet_to_ipa_converts_stress(self):
        self.assertEqual(arpabet_to_ipa("T EH1 S T"), "/tˈɛst/")
        self.assertEqual(arpabet_to_ipa("R IY1 D"), "/rˈid/")

    def test_iter_cmudict_rows_merges_alternate_pronunciations(self):
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
                rows = list(iter_cmudict_rows(path))

        self.assertEqual(rows[0][:5], ("read", "read", "/rˈid/ /rˈɛd/", "en", "cmudict:word"))
        self.assertEqual(rows[0][5], 7.0)
        self.assertEqual(rows[1][:5], ("test", "test", "/tˈɛst/", "en", "cmudict:word"))
        self.assertEqual(rows[1][5], 6.0)

    def test_iter_jmdict_rows_maps_romaji_to_primary_surface(self):
        payload = """<?xml version="1.0" encoding="UTF-8"?>
<JMdict>
  <entry>
    <k_ele><keb>私</keb></k_ele>
    <r_ele><reb>わたし</reb></r_ele>
  </entry>
</JMdict>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "JMdict_e.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(payload)

            with patch("build_autocomplete_index.wordfreq_score", return_value=5.0):
                rows = list(iter_jmdict_rows(path))

        self.assertIn(("私", "私", "わたし", "ja", "jmdict:surface", 5.0), rows)
        self.assertIn(("わたし", "私", "わたし", "ja", "jmdict:reading", 5.0), rows)
        self.assertIn(("watashi", "私", "わたし", "ja", "jmdict:romaji", 5.0), rows)

    def test_iter_jmdict_rows_prefers_surface_frequency_over_shared_reading(self):
        payload = """<?xml version="1.0" encoding="UTF-8"?>
<JMdict>
  <entry>
    <k_ele><keb>私</keb></k_ele>
    <r_ele><reb>わたし</reb></r_ele>
  </entry>
</JMdict>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "JMdict_e.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(payload)

            def fake_wordfreq(word: str, lang: str) -> float:
                if word == "私":
                    return 9.0
                if word == "わたし":
                    return 2.0
                return 0.0

            with patch("build_autocomplete_index.wordfreq_score", side_effect=fake_wordfreq):
                rows = list(iter_jmdict_rows(path))

        self.assertTrue(all(row[5] == 9.0 for row in rows))


if __name__ == "__main__":
    unittest.main()
