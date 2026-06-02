import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("CONFIG_PATH", str(API_DIR / "config_example.json"))
os.environ.setdefault("API_KEY", "unit-test-key")
os.environ.setdefault("CEREBRAS_API_KEY", "unit-test-cerebras-key")
os.environ.setdefault("CLARIFAI_API_KEY", "unit-test-clarifai-key")
os.environ.setdefault("LOCAL_LEXICON_PATH", "")
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
    def setUp(self):
        api_app._RATE_LIMIT_BUCKETS.clear()
        self.client = TestClient(api_app.app)
        self.model_id = next(iter(api_app.MODELS.keys()))

    def test_lifespan_preloads_local_autocomplete_and_closes_http_clients(self):
        with (
            patch.object(api_app.LOCAL_AUTOCOMPLETE, "preload", return_value=True) as preload_mock,
            patch.object(api_app, "close_http_clients", AsyncMock()) as close_mock,
            TestClient(api_app.app),
        ):
            pass

        preload_mock.assert_called_once_with()
        close_mock.assert_awaited_once_with()

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
        self.assertEqual(response.json(), {"error": "Invalid request."})

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
            patch.object(api_app, "_client_for_model", return_value=fake_client) as client_selector,
            patch.object(
                api_app,
                "async_lookupdictionary_bundle",
                AsyncMock(return_value={"augmented_content": "", "sources": fake_sources}),
            ) as lookup_bundle_mock,
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
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        events = parse_sse_events(response.text)
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
        client_selector.assert_called_once_with(self.model_id)
        lookup_bundle_mock.assert_awaited_once_with(
            "apple",
            local_autocomplete=api_app.LOCAL_AUTOCOMPLETE,
            preferred_language="en",
        )

    def test_lookup_applies_model_params_and_expands_json_schema(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"apple"}'))
        fake_client = make_fake_client(fake_create)
        model_id = "deepseek-ai/DeepSeek-V3-0324"

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.object(
                api_app,
                "async_lookupdictionary_bundle",
                AsyncMock(return_value={"augmented_content": "", "sources": []}),
            ),
            patch.dict(
                api_app.MODELS,
                {model_id: "DeepSeek V3 0324"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PROVIDERS,
                {model_id: "default"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PARAMS,
                {model_id: {"reasoning_effort": "low", "response_format": {"type": "json_schema"}}},
                clear=False,
            ),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "apple",
                    "preferredLanguage": "en",
                    "model": model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = fake_create.call_args
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["temperature"], 0.1)
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "dictionary_entry")
        self.assertEqual(kwargs["response_format"]["json_schema"]["schema"], api_app.DICTIONARY_SCHEMA)

    def test_lookup_drops_json_schema_for_clarifai_models(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"apple"}'))
        fake_client = make_fake_client(fake_create)
        model_id = "https://clarifai.com/openai/chat-completion/models/gpt-oss-120b/versions/770a9a1af221402dac8977b0186f4604"

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.object(
                api_app,
                "async_lookupdictionary_bundle",
                AsyncMock(return_value={"augmented_content": "", "sources": []}),
            ),
            patch.dict(
                api_app.MODELS,
                {model_id: "GPT OSS 120B (Clarifai)"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PROVIDERS,
                {model_id: "clarifai"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PARAMS,
                {model_id: {"response_format": {"type": "json_schema"}}},
                clear=False,
            ),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "apple",
                    "preferredLanguage": "en",
                    "model": model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = fake_create.call_args
        self.assertNotIn("response_format", kwargs)

    def test_lookup_defaults_to_json_schema_for_non_clarifai_models(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"apple"}'))
        fake_client = make_fake_client(fake_create)
        model_id = "deepseek-ai/DeepSeek-V3-0324"

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.object(
                api_app,
                "async_lookupdictionary_bundle",
                AsyncMock(return_value={"augmented_content": "", "sources": []}),
            ),
            patch.dict(api_app.MODEL_PARAMS, {model_id: {}}, clear=False),
            patch.dict(api_app.MODELS, {model_id: "DeepSeek V3 0324"}, clear=False),
            patch.dict(api_app.MODEL_PROVIDERS, {model_id: "default"}, clear=False),
        ):
            response = self.client.post(
                "/api/lookup",
                json={
                    "query": "apple",
                    "preferredLanguage": "en",
                    "model": model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = fake_create.call_args
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "dictionary_entry")

    def test_lookup_handles_unicode_llm_content_without_console_encoding_failure(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"targetWord":"オーケストラレーション"}'))
        fake_client = make_fake_client(fake_create)

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.object(
                api_app,
                "async_lookupdictionary_bundle",
                AsyncMock(return_value={"augmented_content": "", "sources": []}),
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
            )

        self.assertEqual(response.status_code, 200)
        events = parse_sse_events(response.text)
        self.assertEqual(events[-1], ("result", {"targetWord": "オーケストラレーション"}))

    def test_preconnect_ignores_body_and_warms_all_sources(self):
        fake_payload = {
            "dictionaryapi": {"status": 200, "elapsedMs": 10.0},
            "jisho": {"status": 200, "elapsedMs": 200.0},
            "wiktionary": {"status": 200, "elapsedMs": 300.0},
            "weblio": {"status": 200, "elapsedMs": 100.0},
        }

        with patch.object(api_app, "preconnect_lookup_sources", AsyncMock(return_value=fake_payload)) as preconnect_mock:
            response = self.client.post(
                "/api/preconnect",
                json={"sources": ["jisho"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "sources": fake_payload})
        preconnect_mock.assert_awaited_once_with()

    def test_lookup_helper_filters_failed_sources(self):
        fake_specs = (
            {"id": "ok", "name": "Ok"},
            {"id": "unavailable", "name": "Unavailable"},
            {"id": "empty", "name": "Empty"},
        )

        async def fake_fetch(spec, word, preferred_language="auto"):
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
                "surface": "测试",
                "reading": "cè shì",
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
        self.assertIn("测试 [cè shì]", result["sources"][0]["preview"])
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

        fake_client = MagicMock()
        fake_client.get.return_value = FakeResponse()
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_client

        with patch.object(api_helpers.httpx, "Client", return_value=fake_context):
            text = api_helpers._http_get_text(
                "https://api.dictionaryapi.dev/api/v2/entries/en/previous",
                source="dictionaryapi",
                timeout=1.0,
            )

        self.assertIn("/ˈpɹiːvɪəs/", text)
        self.assertNotIn("脌", text)

    def test_http_clients_use_uniform_browser_user_agent_and_wiktionary_http2(self):
        created = []

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                created.append(kwargs)

        with patch.object(api_helpers.httpx, "AsyncClient", FakeAsyncClient):
            api_helpers._ASYNC_HTTP_CLIENTS.clear()
            api_helpers._http_client("jisho")
            api_helpers._http_client("wiktionary")

        self.assertEqual(created[0]["headers"]["User-Agent"], api_helpers.BROWSER_USER_AGENT)
        self.assertEqual(created[1]["headers"]["User-Agent"], api_helpers.BROWSER_USER_AGENT)
        self.assertFalse(created[0]["http2"])
        self.assertTrue(created[1]["http2"])
        api_helpers._ASYNC_HTTP_CLIENTS.clear()

    def test_preconnect_lookup_sources_reports_source_errors(self):
        async def fake_preconnect(spec):
            source_id = spec["id"]
            if source_id == "jisho":
                raise RuntimeError("reset")
            return source_id, {"status": 200, "elapsedMs": 1.0}

        with patch.object(api_helpers, "_preconnect_lookup_source", side_effect=fake_preconnect):
            result = asyncio.run(api_helpers.preconnect_lookup_sources())

        self.assertEqual(set(result), {"dictionaryapi", "jisho", "wiktionary", "weblio"})
        self.assertEqual(result["dictionaryapi"]["status"], 200)
        self.assertIn("reset", result["jisho"]["error"])

    def test_wiktionary_formatter_preserves_definition_templates(self):
        raw = "\n".join(
            [
                "==English==",
                "===Phrase===",
                "{{head|en|phrase}}",
                "# {{lb|en|chiefly|Internet slang}} {{alt form|en|tl;dr}}.",
            ]
        )

        formatted = api_helpers._format_wiktionary_raw(raw)

        self.assertEqual(
            formatted,
            "English · Phrase\n- (chiefly; Internet slang) Alternative form of tl;dr.",
        )
        self.assertNotIn("# .", formatted)
        self.assertNotIn("{{", formatted)

    def test_wiktionary_formatter_keeps_multiple_definition_sections(self):
        raw = "\n".join(
            [
                "==English==",
                "===Alternative forms===",
                "* {{alter|en|Angell|q=surname}}",
                "===Pronunciation===",
                "* {{IPA|en|/ˈeɪn.d͡ʒəl/}}",
                "===Noun===",
                "{{en-proper noun|s}}",
                "# {{altcase|en|angel}}.",
                "===Proper noun===",
                "{{en-proper noun|s}}",
                "# A male given name from Latin {{m|la|Angelus}}; or an anglicized spelling of {{m|es|Ángel}}.",
            ]
        )

        formatted = api_helpers._format_wiktionary_raw(raw, preferred_language="en")

        self.assertEqual(
            formatted,
            "\n".join(
                [
                    "English · Noun",
                    "- Alternative letter-case form of angel.",
                    "English · Proper noun",
                    "- A male given name from Latin Angelus; or an anglicized spelling of Ángel.",
                ]
            ),
        )
        self.assertNotIn("Pronunciation", formatted)

    def test_wiktionary_formatter_selects_target_language_definitions(self):
        raw = "\n".join(
            [
                "==Chinese==",
                "===Pronunciation===",
                "{{zh-pron|m=tiānshǐ}}",
                "===Noun===",
                "{{head|zh|noun}}",
                "# [[angel]]",
                "# {{lb|zh|obsolete}} [[envoy]] sent by [[Heaven]] or [[Son of Heaven]]; [[imperial]] or [[heavenly]] [[emissary]]",
                "==Japanese==",
                "===Etymology===",
                "From {{der|ja|ltc|sort=てんし|-}} {{ltc-l|天使}}.",
                "===Pronunciation===",
                "{{ja-pron|てんし|acc=1}}",
                "===Noun===",
                "{{ja-noun|てんし}}",
                "# an [[angel]]",
                "#: {{ja-usex|'''天%使'''と[[悪%魔]]|'''^てん%し''' と ^あく%ま}}",
                "# an [[imperial]] [[messenger]] or [[envoy]]",
                "# a [[messenger]] or [[envoy]] from [[heaven]]",
                "# {{lb|ja|sort=てんし|metaphor}} someone who is [[kind]] and [[pure]]; an [[angel]]",
                "====Quotations====",
                "* See [[Citations:天使]].",
                "==Korean==",
                "===Noun===",
                "# {{hanja form of|천사|[[angel]]}}",
            ]
        )

        formatted = api_helpers._format_wiktionary_raw(raw, preferred_language="ja")

        self.assertEqual(
            formatted,
            "\n".join(
                [
                    "Japanese · Noun",
                    "- an angel",
                    "- an imperial messenger or envoy",
                    "- a messenger or envoy from heaven",
                    "- (metaphor) someone who is kind and pure; an angel",
                ]
            ),
        )
        self.assertNotIn("Etymology", formatted)
        self.assertNotIn("Pronunciation", formatted)
        self.assertNotIn("Korean", formatted)
        self.assertNotIn("ja-usex", formatted)

        chinese = api_helpers._format_wiktionary_raw(raw, preferred_language="zh")
        self.assertEqual(
            chinese,
            "\n".join(
                [
                    "Chinese · Noun",
                    "- angel",
                    "- (obsolete) envoy sent by Heaven or Son of Heaven; imperial or heavenly emissary",
                ]
            ),
        )

    def test_wiktionary_source_keeps_raw_separate_from_preview(self):
        raw = "==English==\n===Phrase===\n{{head|en|phrase}}\n# {{alt form|en|tl;dr}}."
        spec = next(item for item in api_helpers.LOOKUP_SOURCE_SPECS if item["id"] == "wiktionary")

        with patch.object(api_helpers, "_try_fetch_text_async", AsyncMock(return_value=raw)):
            result = asyncio.run(api_helpers._fetch_lookup_source_entry(spec, "tldr", preferred_language="en"))

        self.assertEqual(result["preview"], "English · Phrase\n- Alternative form of tl;dr.")
        self.assertEqual(result["raw"], raw)
        self.assertIn("{{head|en|phrase}}", result["raw"])

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
            response.json(),
            {"suggestions": [{"surface": "美食", "reading": "měi shí", "lang": "zh"}]},
        )
        fake_local.search.assert_called_once_with("meishi", preferred_language="zh", limit=3)

    def test_autocomplete_llm_returns_json(self):
        fake_create = AsyncMock(return_value=make_chat_response("<think>ignored</think>\nfood\nbusiness card\nnoun"))
        fake_client = make_fake_client(fake_create)

        with patch.object(api_app, "_client_for_model", return_value=fake_client) as client_selector:
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
            response.json(),
            {"suggestions": ["food", "business card", "noun"]},
        )

        _, kwargs = fake_create.call_args
        self.assertIn("messages", kwargs)
        self.assertIn("Language: zh", kwargs["messages"][1]["content"])
        self.assertIn("Input: meishi", kwargs["messages"][1]["content"])
        client_selector.assert_called_once_with(api_app.FAST_MODEL)

    def test_autocomplete_llm_ignores_response_format_and_fixed_limits_override_model_params(self):
        fake_create = AsyncMock(return_value=make_chat_response("food"))
        fake_client = make_fake_client(fake_create)

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.dict(
                api_app.MODEL_PARAMS,
                {
                    api_app.FAST_MODEL: {
                        "reasoning_effort": "low",
                        "response_format": {"type": "json_schema"},
                        "temperature": 0.8,
                        "max_tokens": 99,
                        "max_completion_tokens": 128,
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    }
                },
                clear=False,
            ),
        ):
            response = self.client.post(
                "/api/autocomplete/llm",
                json={
                    "partialInput": "meishi",
                    "preferredLanguage": "zh",
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = fake_create.call_args
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["max_tokens"], 32)
        self.assertEqual(kwargs["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("max_completion_tokens", kwargs)

    def test_autocomplete_rejects_overly_long_partial_input(self):
        response = self.client.post(
            "/api/autocomplete/local",
            json={
                "partialInput": "a" * 129,
                "preferredLanguage": "en",
                "timestamp": int(time.time() * 1000),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"suggestions": []})

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
        self.assertEqual(response.json(), {"error": "Not enough words provided."})

    def test_generate_sentence_rejects_unknown_model(self):
        response = self.client.post(
            "/api/generate-sentence",
            json={
                "words": [{"word": "apple", "lang": "en"}, {"word": "test", "lang": "en"}],
                "model": "unknown-model",
                "timestamp": int(time.time() * 1000),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Model 'unknown-model' not supported."})

    def test_generate_sentence_applies_model_params_and_expands_json_schema(self):
        fake_create = AsyncMock(return_value=make_chat_response('{"usedWords":["apple"],"content":{"zh":{"text":"??","pronunciation":"p?ng gu?"},"en":{"text":"apple","pronunciation":"/??p.?l/"},"ja":{"text":"???","pronunciation":"???"}}}'))
        fake_client = make_fake_client(fake_create)
        model_id = "deepseek-ai/DeepSeek-V3-0324"

        with (
            patch.object(api_app, "_client_for_model", return_value=fake_client),
            patch.dict(
                api_app.MODELS,
                {model_id: "DeepSeek V3 0324"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PROVIDERS,
                {model_id: "default"},
                clear=False,
            ),
            patch.dict(
                api_app.MODEL_PARAMS,
                {
                    model_id: {
                        "reasoning_effort": "low",
                        "response_format": {"type": "json_schema"},
                    }
                },
                clear=False,
            ),
        ):
            response = self.client.post(
                "/api/generate-sentence",
                json={
                    "words": [{"word": "apple", "lang": "en"}, {"word": "test", "lang": "en"}],
                    "model": model_id,
                    "timestamp": int(time.time() * 1000),
                },
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = fake_create.call_args
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertEqual(kwargs["response_format"]["json_schema"]["name"], "lucky_sentence")
        self.assertEqual(kwargs["response_format"]["json_schema"]["schema"], api_app.LUCKY_SCHEMA)


if __name__ == "__main__":
    unittest.main()
