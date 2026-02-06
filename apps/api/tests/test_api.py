import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("API_KEY", "unit-test-key")
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")

import app as api_app  # noqa: E402


def make_chat_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def make_fake_client(create_fn):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=create_fn,
            )
        )
    )


class ApiEndpointsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_app.app.config["TESTING"] = True

    def setUp(self):
        self.client = api_app.app.test_client()
        self.model_id = next(iter(api_app.MODELS.keys()))

    def test_lookup_rejects_stale_timestamp(self):
        response = self.client.post(
            "/api/lookup",
            json={
                "query": "apple",
                "preferredLanguage": "en",
                "model": self.model_id,
                "timestamp": 0,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "Invalid request."})

    def test_lookup_success(self):
        fake_create = MagicMock(return_value=make_chat_response('{"targetWord":"apple"}'))
        fake_client = make_fake_client(fake_create)

        with (
            patch.object(api_app, "OPENAI_CLIENT", fake_client),
            patch.object(api_app, "lookupdictionary", return_value=""),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "apple",
                    "preferredLanguage": "en",
                    "model": self.model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["targetWord"], "apple")
        self.assertEqual(fake_create.call_count, 1)

    def test_autocomplete_includes_language_context(self):
        fake_create = MagicMock(return_value=make_chat_response("food\nbusiness card\nnoun"))
        fake_client = make_fake_client(fake_create)

        with patch.object(api_app, "OPENAI_CLIENT", fake_client):
            response = self.client.post(
                "/api/autocomplete",
                json={
                    "partialInput": "meishi",
                    "preferredLanguage": "zh",
                    "model": self.model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"suggestions": ["food", "business card", "noun"]})

        _, kwargs = fake_create.call_args
        self.assertIn("messages", kwargs)
        self.assertIn("Language: zh", kwargs["messages"][1]["content"])
        self.assertIn("Input: meishi", kwargs["messages"][1]["content"])

    def test_generate_sentence_requires_two_words(self):
        response = self.client.post(
            "/api/generate-sentence",
            json={
                "words": [{"word": "apple", "lang": "en"}],
                "model": self.model_id,
                "timestamp": int(time.time() * 1000),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "Not enough words provided."})


if __name__ == "__main__":
    unittest.main()
