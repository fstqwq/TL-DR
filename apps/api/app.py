import copy
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from json import JSONDecodeError
from typing import Deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from .api_helpers import (
        async_lookupdictionary_bundle,
        close_http_clients,
        create_openai_clients,
        parse_autocomplete_suggestions,
        preconnect_lookup_sources,
        safe_json,
    )
    from .local_autocomplete import LocalAutocomplete
    from .llm_payloads import (
        AUTOCOMPLETE_PROMPT,
        DICTIONARY_SCHEMA,
        LUCKY_SCHEMA,
        lucky_system_content,
        lookup_system_content,
        lookup_user_content,
    )
    from .runtime_config import (
        AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE,
        FAST_MODEL,
        AUTOCOMPLETE_INDEX_PATH,
        MAIN_RATE_LIMIT_PER_MINUTE,
        MODEL_PARAMS,
        MODEL_PROVIDERS,
        MODELS,
        PROVIDER_CONFIGS,
    )
except ImportError:
    from api_helpers import (
        async_lookupdictionary_bundle,
        close_http_clients,
        create_openai_clients,
        parse_autocomplete_suggestions,
        preconnect_lookup_sources,
        safe_json,
    )
    from local_autocomplete import LocalAutocomplete
    from llm_payloads import (
        AUTOCOMPLETE_PROMPT,
        DICTIONARY_SCHEMA,
        LUCKY_SCHEMA,
        lucky_system_content,
        lookup_system_content,
        lookup_user_content,
    )
    from runtime_config import (
        AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE,
        FAST_MODEL,
        AUTOCOMPLETE_INDEX_PATH,
        MAIN_RATE_LIMIT_PER_MINUTE,
        MODEL_PARAMS,
        MODEL_PROVIDERS,
        MODELS,
        PROVIDER_CONFIGS,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname).1s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

PROVIDER_CLIENTS = create_openai_clients(PROVIDER_CONFIGS)
LOCAL_AUTOCOMPLETE = LocalAutocomplete(AUTOCOMPLETE_INDEX_PATH)
MAX_AUTOCOMPLETE_INPUT_LENGTH = 128

_RATE_LIMIT_BUCKETS: dict[str, Deque[float]] = defaultdict(deque)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    started = time.perf_counter()
    loaded = LOCAL_AUTOCOMPLETE.preload()
    logging.info(
        "local_autocomplete_preload_complete loaded=%s elapsed_ms=%.1f",
        loaded,
        (time.perf_counter() - started) * 1000,
    )
    try:
        yield
    finally:
        await close_http_clients()


app = FastAPI(lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse_event(name: str, payload: object) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _client_for_model(model: str):
    provider_name = MODEL_PROVIDERS.get(model)
    if provider_name is None:
        raise RuntimeError(f"No provider configured for model '{model}'.")

    client = PROVIDER_CLIENTS.get(provider_name)
    if client is None:
        raise RuntimeError(f"Provider '{provider_name}' is not initialized.")
    return client


def _provider_for_model(model: str) -> str:
    provider_name = MODEL_PROVIDERS.get(model)
    if provider_name is None:
        raise RuntimeError(f"No provider configured for model '{model}'.")
    return provider_name


def _schema_for_endpoint(endpoint: str) -> tuple[str, dict] | None:
    if endpoint == "lookup":
        return "dictionary_entry", DICTIONARY_SCHEMA
    if endpoint == "generate_sentence":
        return "lucky_sentence", LUCKY_SCHEMA
    return None


def _normalize_response_format(model: str, endpoint: str, response_format: object) -> dict | None:
    if not isinstance(response_format, dict) or not response_format:
        return None

    response_type = response_format.get("type")
    if response_type != "json_schema":
        return copy.deepcopy(response_format)

    # Clarifai's OpenAI-compatible endpoint currently rejects response_format=json_schema
    # even when the schema is present. Falling back to prompt-constrained JSON keeps
    # the model usable without changing other providers.
    if _provider_for_model(model) == "clarifai":
        return None

    schema_ref = _schema_for_endpoint(endpoint)
    if schema_ref is None:
        return None

    schema_name, schema = schema_ref
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": schema,
        },
    }


def _model_request_params(model: str, endpoint: str, *, include_response_format: bool = True) -> dict:
    params = copy.deepcopy(MODEL_PARAMS.get(model, {}))

    if include_response_format:
        if "response_format" in params:
            raw_response_format = params.get("response_format")
        elif endpoint in {"lookup", "generate_sentence"}:
            raw_response_format = {"type": "json_schema"}
        else:
            raw_response_format = None
        normalized_response_format = _normalize_response_format(model, endpoint, raw_response_format)
        if normalized_response_format is None:
            params.pop("response_format", None)
        else:
            params["response_format"] = normalized_response_format
    else:
        params.pop("response_format", None)

    if endpoint == "autocomplete":
        params.pop("temperature", None)
        params.pop("max_tokens", None)
        params.pop("max_completion_tokens", None)

    return params


async def _request_json(request: Request) -> dict:
    try:
        data = await request.json()
    except (JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _timestamp_is_valid(timestamp: object) -> bool:
    if not isinstance(timestamp, (int, float)):
        return False
    return abs(time.time() - timestamp / 1000) <= 15


def _rate_limit_response(scope: str, limit_per_minute: int) -> JSONResponse | None:
    now = time.monotonic()
    bucket = _RATE_LIMIT_BUCKETS[scope]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit_per_minute:
        return JSONResponse({"error": "Rate limit exceeded."}, status_code=429)
    bucket.append(now)
    return None


def _autocomplete_user_content(preferred_language: str, partial_input: str) -> str:
    return (f"Language: {preferred_language}\n" if preferred_language != "auto" else "") + f"Input: {partial_input}"


async def _parse_autocomplete_request(request: Request):
    data = await _request_json(request)
    timestamp = data.get("timestamp", 0)
    if not _timestamp_is_valid(timestamp):
        return None, JSONResponse({"error": "Invalid request."}, status_code=403)

    partial_input = (data.get("partialInput") or data.get("partial_input") or "").strip()
    preferred_language = data.get("preferredLanguage", "auto")
    return {
        "partial_input": partial_input,
        "preferred_language": preferred_language,
    }, None


@app.post("/api/lookup")
async def lookup_word(request: Request):
    limited = _rate_limit_response("main", MAIN_RATE_LIMIT_PER_MINUTE)
    if limited is not None:
        return limited

    data = await _request_json(request)
    timestamp = data.get("timestamp", 0)
    if not _timestamp_is_valid(timestamp):
        return JSONResponse({"error": "Invalid request."}, status_code=403)

    query = data.get("query")
    model = data.get("model")
    preferred_language = data.get("preferredLanguage", "auto")
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        logging.warning("lookup_missing_query")
        return JSONResponse({"error": "No query provided"}, status_code=400)
    if model not in MODELS:
        logging.warning("lookup_unsupported_model model=%s", model)
        return JSONResponse({"error": f"Model '{model}' not supported."}, status_code=400)

    client = _client_for_model(model)

    async def generate():
        try:
            yield _sse_event(
                "progress",
                {"stage": "augment", "message": "Collecting dictionary context"},
            )
            lookup_bundle = await async_lookupdictionary_bundle(
                query,
                local_autocomplete=LOCAL_AUTOCOMPLETE,
                preferred_language=preferred_language,
            )
            augmented_content = str(lookup_bundle.get("augmented_content", ""))
            yield _sse_event(
                "sources",
                {"sources": lookup_bundle.get("sources", [])},
            )
        except Exception as exc:
            logging.exception("lookup_augment_failed query=%s", query)
            yield _sse_event("error", {"stage": "augment", "message": str(exc)})
            return

        try:
            yield _sse_event(
                "progress",
                {"stage": "generate", "message": "Generating dictionary entry"},
            )
            request_kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": lookup_system_content()},
                    {"role": "user", "content": lookup_user_content(query, preferred_language, augmented_content)},
                ],
            }
            request_kwargs.update(_model_request_params(model, "lookup"))
            request_kwargs["temperature"] = 0.1
            response = await client.chat.completions.create(**request_kwargs)

            content = response.choices[0].message.content
            logging.info("lookup_response_received query=%s content_length=%d", query, len(content or ""))
            yield _sse_event("result", safe_json(content))
        except Exception as exc:
            logging.exception("lookup_generate_failed query=%s", query)
            yield _sse_event("error", {"stage": "generate", "message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/preconnect")
async def preconnect(request: Request):
    limited = _rate_limit_response("preconnect", AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE)
    if limited is not None:
        return limited

    # The request body is intentionally ignored. Preconnect always warms every
    # configured remote source so frontend callers do not need source policy.
    await _request_json(request)
    return JSONResponse({"ok": True, "sources": await preconnect_lookup_sources()})


@app.post("/api/autocomplete/local")
async def autocomplete_local(request: Request):
    limited = _rate_limit_response("autocomplete", AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE)
    if limited is not None:
        return limited

    parsed, error_response = await _parse_autocomplete_request(request)
    if error_response is not None:
        return error_response

    partial_input = parsed["partial_input"]
    preferred_language = parsed["preferred_language"]
    logging.info(
        "autocomplete_local_request preferred_language=%s input_length=%d",
        preferred_language,
        len(partial_input),
    )

    if not partial_input:
        return JSONResponse({"suggestions": []})
    if len(partial_input) > MAX_AUTOCOMPLETE_INPUT_LENGTH:
        return JSONResponse({"suggestions": []}, status_code=400)

    try:
        suggestions = LOCAL_AUTOCOMPLETE.search(
            partial_input,
            preferred_language=preferred_language,
            limit=3,
        )
    except Exception as exc:
        logging.exception("local_autocomplete_failed query=%s", partial_input)
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({"suggestions": suggestions})


@app.post("/api/autocomplete/llm")
async def autocomplete_llm(request: Request):
    limited = _rate_limit_response("autocomplete", AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE)
    if limited is not None:
        return limited

    parsed, error_response = await _parse_autocomplete_request(request)
    if error_response is not None:
        return error_response

    partial_input = parsed["partial_input"]
    preferred_language = parsed["preferred_language"]
    logging.info(
        "autocomplete_llm_request preferred_language=%s input_length=%d",
        preferred_language,
        len(partial_input),
    )

    if not partial_input:
        return JSONResponse({"suggestions": []})

    client = _client_for_model(FAST_MODEL)

    try:
        request_kwargs = {
            "model": FAST_MODEL,
            "messages": [
                {"role": "system", "content": AUTOCOMPLETE_PROMPT},
                {"role": "user", "content": _autocomplete_user_content(preferred_language, partial_input)},
            ],
        }
        request_kwargs.update(_model_request_params(FAST_MODEL, "autocomplete", include_response_format=False))
        request_kwargs["temperature"] = 0
        request_kwargs["max_tokens"] = 32
        response = await client.chat.completions.create(**request_kwargs)
        content = response.choices[0].message.content or ""
        suggestions = parse_autocomplete_suggestions(content)
    except Exception as exc:
        logging.exception("api_autocomplete_failed query=%s", partial_input)
        return JSONResponse({"error": str(exc)}, status_code=500)

    return JSONResponse({"suggestions": suggestions})


@app.post("/api/generate-sentence")
async def generate_sentence(request: Request):
    limited = _rate_limit_response("main", MAIN_RATE_LIMIT_PER_MINUTE)
    if limited is not None:
        return limited

    data = await _request_json(request)
    timestamp = data.get("timestamp", 0)
    if not _timestamp_is_valid(timestamp):
        return JSONResponse({"error": "Invalid request."}, status_code=403)
    words = data.get("words", [])
    model = data.get("model")

    if not words or len(words) < 2:
        return JSONResponse({"error": "Not enough words provided."}, status_code=400)
    if model not in MODELS:
        logging.warning("generate_sentence_unsupported_model model=%s", model)
        return JSONResponse({"error": f"Model '{model}' not supported."}, status_code=400)

    try:
        client = _client_for_model(model)
        request_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": lucky_system_content()},
                {"role": "user", "content": f"Input Words: {json.dumps(words, ensure_ascii=False, indent=None)}"},
            ],
        }
        request_kwargs.update(_model_request_params(model, "generate_sentence"))
        response = await client.chat.completions.create(**request_kwargs)

        content = response.choices[0].message.content
        logging.info("lucky_response_received word_count=%d content_length=%d", len(words), len(content or ""))
        return JSONResponse(safe_json(content))

    except Exception as exc:
        logging.exception("generate_sentence_failed")
        return JSONResponse({"error": str(exc)}, status_code=500)
