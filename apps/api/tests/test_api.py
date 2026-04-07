import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("API_KEY", "unit-test-key")
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")

import app as api_app  # noqa: E402
import api_helpers  # noqa: E402


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


def parse_sse_events(payload: str):
    events = []
    for chunk in payload.split("\n\n"):
        block = chunk.strip()
        if not block:
            continue
        event_name = "message"
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        data = json.loads("\n".join(data_lines)) if data_lines else None
        events.append((event_name, data))
    return events


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

    def test_lookup_streams_progress_then_result(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"apple"}'))
        fake_client = make_fake_client(fake_create)
        fake_sources = [
            {
                "id": "wiktionary",
                "name": "Wiktionary",
                "pageUrl": "https://en.wiktionary.org/wiki/apple",
                "fetchUrl": "https://en.wiktionary.org/w/index.php?title=apple&action=raw",
                "preview": "apple",
            }
        ]

        with (
            patch.object(api_app, "OPENAI_CLIENT", fake_client),
            patch.object(
                api_app,
                "lookupdictionary_bundle",
                return_value={"augmented_content": "", "sources": fake_sources},
            ),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "apple",
                    "preferredLanguage": "en",
                    "model": self.model_id,
                    "timestamp": int(time.time() * 1000),
                },
                buffered=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        events = parse_sse_events(response.get_data(as_text=True))
        self.assertEqual(
            events,
            [
                ("progress", {"stage": "augment", "message": "Collecting dictionary context"}),
                ("sources", {"sources": fake_sources}),
                ("progress", {"stage": "generate", "message": "Generating dictionary entry"}),
                ("result", {"targetWord": "apple"}),
            ],
        )
        self.assertEqual(fake_create.call_count, 1)

    def test_lookup_handles_unicode_llm_content_without_console_encoding_failure(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"オーケストラ・アレンジャー"}'))
        fake_client = make_fake_client(fake_create)

        with (
            patch.object(api_app, "OPENAI_CLIENT", fake_client),
            patch.object(
                api_app,
                "lookupdictionary_bundle",
                return_value={"augmented_content": "", "sources": []},
            ),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "orchestrator",
                    "preferredLanguage": "en",
                    "model": self.model_id,
                    "timestamp": int(time.time() * 1000),
                },
                buffered=True,
            )

        self.assertEqual(response.status_code, 200)
        events = parse_sse_events(response.get_data(as_text=True))
        self.assertEqual(events[-1], ("result", {"targetWord": "オーケストラ・アレンジャー"}))

    def test_lookup_helper_filters_failed_sources(self):
        fake_specs = (
            {"id": "ok", "name": "Ok"},
            {"id": "unavailable", "name": "Unavailable"},
            {"id": "empty", "name": "Empty"},
        )

        async def fake_fetch(spec, word):
            source_id = spec["id"]
            if source_id == "ok":
                return {
                    "id": "ok",
                    "name": "Ok",
                    "pageUrl": "https://example.com/ok",
                    "fetchUrl": "https://example.com/ok.raw",
                    "preview": "useful preview",
                }
            if source_id == "unavailable":
                return {
                    "id": "unavailable",
                    "name": "Unavailable",
                    "pageUrl": "https://example.com/unavailable",
                    "fetchUrl": "https://example.com/unavailable.raw",
                    "preview": "",
                }
            return {
                "id": "empty",
                "name": "Empty",
                "pageUrl": "https://example.com/empty",
                "fetchUrl": "https://example.com/empty.raw",
                "preview": "   ",
            }

        with (
            patch.object(api_helpers, "LOOKUP_SOURCE_SPECS", fake_specs),
            patch.object(api_helpers, "_fetch_lookup_source_entry", AsyncMock(side_effect=fake_fetch)),
        ):
            result = asyncio.run(api_helpers._lookupdictionary_async("apple"))

        self.assertEqual(
            result,
            {
                "augmented_content": "useful preview",
                "sources": [
                    {
                        "id": "ok",
                        "name": "Ok",
                        "pageUrl": "https://example.com/ok",
                        "fetchUrl": "https://example.com/ok.raw",
                        "preview": "useful preview",
                    }
                ],
            },
        )

    def test_lookup_bundle_merges_local_dictionary_entry(self):
        fake_local = MagicMock()
        fake_local.search.return_value = [
            {
                "surface": "\u6d4b\u8bd5",
                "reading": "c\u00e8 sh\u00ec",
                "meaning": "- test\n- examine",
                "lang": "zh",
            }
        ]
        fake_local.providers.return_value = {"zh": "cc-cedict", "ja": "jmdict", "en": "cmudict"}

        with patch.object(
            api_helpers,
            "_lookupdictionary_remote_bundle",
            return_value={
                "augmented_content": "remote preview",
                "sources": [
                    {
                        "id": "wiktionary",
                        "name": "Wiktionary",
                        "pageUrl": "https://en.wiktionary.org/wiki/test",
                        "fetchUrl": "https://en.wiktionary.org/w/index.php?title=test&action=raw",
                        "preview": "remote preview",
                    }
                ],
            },
        ):
            result = api_helpers.lookupdictionary_bundle("ceshi", local_autocomplete=fake_local)

        self.assertEqual(result["sources"][0]["id"], "cc-cedict")
        self.assertIn("\u6d4b\u8bd5 [c\u00e8 sh\u00ec]", result["sources"][0]["preview"])
        self.assertIn("- test", result["augmented_content"])
        self.assertIn("remote preview", result["augmented_content"])
        fake_local.search.assert_called_once_with("ceshi", preferred_language="auto", limit=8)

    def test_http_get_text_uses_utf8_for_json_responses(self):
        class FakeResponse:
            def __init__(self):
                self.status_code = 200
                self.headers = {"content-type": "application/json; charset=utf-8"}
                self.apparent_encoding = "mac_iceland"
                self.encoding = "utf-8"
                self.content = b'[{"word":"previous","phonetic":"/\xcb\x88p\xc9\xb9i\xcb\x90v\xc9\xaa\xc9\x99s/"}]'

            @property
            def text(self):
                return self.content.decode(self.encoding or "utf-8", errors="replace")

        fake_scraper = MagicMock()
        fake_scraper.get.return_value = FakeResponse()

        with patch.object(api_helpers.cloudscraper, "create_scraper", return_value=fake_scraper):
            text = api_helpers._http_get_text(
                "https://api.dictionaryapi.dev/api/v2/entries/en/previous",
                source="dictionaryapi",
                timeout=1.0,
            )

        self.assertIn("/ˈpɹiːvɪəs/", text)
        self.assertNotIn("À", text)

    def test_autocomplete_local_returns_json(self):
        fake_local = MagicMock()
        fake_local.search.return_value = [{"surface": "美食", "reading": "měi shí", "lang": "zh"}]

        with patch.object(api_app, "LOCAL_AUTOCOMPLETE", fake_local):
            response = self.client.post(
                "/api/autocomplete/local",
                json={
                    "partialInput": "meishi",
                    "preferredLanguage": "zh",
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"suggestions": [{"surface": "美食", "reading": "měi shí", "lang": "zh"}]},
        )
        fake_local.search.assert_called_once_with("meishi", preferred_language="zh", limit=3)

    def test_autocomplete_llm_returns_json(self):
        fake_create = AsyncMock(return_value=make_chat_response("<think>ignored</think>\nfood\nbusiness card\nnoun"))
        fake_client = make_fake_client(fake_create)

        with patch.object(api_app, "OPENAI_CLIENT", fake_client):
            response = self.client.post(
                "/api/autocomplete/llm",
                json={
                    "partialInput": "meishi",
                    "preferredLanguage": "zh",
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"suggestions": ["food", "business card", "noun"]},
        )

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
