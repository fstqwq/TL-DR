import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from api_helpers import heal_json_text, safe_json  # noqa: E402


class ApiHelpersTestCase(unittest.TestCase):
    def test_heal_json_text_handles_double_outer_braces(self):
        raw = """
        {{
          "targetWord": "任せて",
          "detectedLanguage": "ja"
        }}
        """
        healed = heal_json_text(raw)
        parsed = safe_json(raw)

        self.assertTrue(healed.startswith("{"))
        self.assertEqual(parsed.get("targetWord"), "任せて")
        self.assertEqual(parsed.get("detectedLanguage"), "ja")

    def test_safe_json_handles_code_fence(self):
        raw = """```json
        {"targetWord":"apple","detectedLanguage":"en"}
        ```"""
        parsed = safe_json(raw)
        self.assertEqual(parsed.get("targetWord"), "apple")
        self.assertEqual(parsed.get("detectedLanguage"), "en")

    def test_safe_json_heals_trailing_comma(self):
        raw = '{"targetWord":"apple","detectedLanguage":"en",}'
        parsed = safe_json(raw)
        self.assertEqual(parsed.get("targetWord"), "apple")
        self.assertEqual(parsed.get("detectedLanguage"), "en")


if __name__ == "__main__":
    unittest.main()
