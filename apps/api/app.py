import asyncio
import copy
import json
import logging
import time

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

try:
    from .api_helpers import (
        create_openai_clients,
        lookupdictionary_bundle,
        parse_autocomplete_suggestions,
        safe_json,
    )
    from .local_autocomplete import LocalAutocomplete
    from .limiter_setup import attach_global_limiter
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
        RATE_LIMIT_STORAGE_URI,
    )
except ImportError:
    from api_helpers import (
        create_openai_clients,
        lookupdictionary_bundle,
        parse_autocomplete_suggestions,
        safe_json,
    )
    from local_autocomplete import LocalAutocomplete
    from limiter_setup import attach_global_limiter
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
        RATE_LIMIT_STORAGE_URI,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname).1s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests
main_limit, autocomplete_limit = attach_global_limiter(
    app,
    storage_uri=RATE_LIMIT_STORAGE_URI,
    main_limit_per_minute=MAIN_RATE_LIMIT_PER_MINUTE,
    autocomplete_limit_per_minute=AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE,
)
PROVIDER_CLIENTS = create_openai_clients(PROVIDER_CONFIGS)
LOCAL_AUTOCOMPLETE = LocalAutocomplete(AUTOCOMPLETE_INDEX_PATH)


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


def _parse_autocomplete_request():
    data = request.json or {}
    timestamp = data.get("timestamp", 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return None, jsonify({"error": "Invalid request."}), 403

    partial_input = (data.get("partialInput") or data.get("partial_input") or "").strip()
    preferred_language = data.get("preferredLanguage", "auto")
    return {
        "partial_input": partial_input,
        "preferred_language": preferred_language,
    }, None, None


def _autocomplete_user_content(preferred_language: str, partial_input: str) -> str:
    return (f"Language: {preferred_language}\n" if preferred_language != "auto" else "") + f"Input: {partial_input}"


@app.route("/api/lookup", methods=["POST"])
@main_limit
def lookup_word():
    data = request.json or {}
    timestamp = data.get("timestamp", 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    query = data.get("query")
    model = data.get("model")
    preferred_language = data.get("preferredLanguage", "auto")
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        logging.warning("lookup_missing_query")
        return jsonify({"error": "No query provided"}), 400
    if model not in MODELS:
        logging.warning("lookup_unsupported_model model=%s", model)
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    client = _client_for_model(model)

    @stream_with_context
    def generate():
        async def fetch_lookup_result() -> object:
            request_kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": lookup_system_content()},
                    {"role": "user", "content": lookup_user_content(query, preferred_language, augmented_content)},
                ],
            }
            request_kwargs.update(_model_request_params(model, "lookup"))
            request_kwargs["temperature"] = 0.1
            return await client.chat.completions.create(**request_kwargs)

        try:
            yield _sse_event(
                "progress",
                {"stage": "augment", "message": "Collecting dictionary context"},
            )
            lookup_bundle = lookupdictionary_bundle(query, local_autocomplete=LOCAL_AUTOCOMPLETE)
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
            response = asyncio.run(fetch_lookup_result())

            content = response.choices[0].message.content
            logging.info("lookup_response_received query=%s content_length=%d", query, len(content or ""))
            yield _sse_event("result", safe_json(content))
        except Exception as exc:
            logging.exception("lookup_generate_failed query=%s", query)
            yield _sse_event("error", {"stage": "generate", "message": str(exc)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/autocomplete/local", methods=["POST"])
@autocomplete_limit
def autocomplete_local():
    parsed, error_response, status_code = _parse_autocomplete_request()
    if error_response is not None:
        return error_response, status_code

    partial_input = parsed["partial_input"]
    preferred_language = parsed["preferred_language"]
    logging.info(
        "autocomplete_local_request preferred_language=%s input_length=%d",
        preferred_language,
        len(partial_input),
    )

    if not partial_input:
        return jsonify({"suggestions": []})

    try:
        suggestions = LOCAL_AUTOCOMPLETE.search(
            partial_input,
            preferred_language=preferred_language,
            limit=3,
        )
    except Exception as exc:
        logging.exception("local_autocomplete_failed query=%s", partial_input)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"suggestions": suggestions})


@app.route("/api/autocomplete/llm", methods=["POST"])
@autocomplete_limit
def autocomplete_llm():
    parsed, error_response, status_code = _parse_autocomplete_request()
    if error_response is not None:
        return error_response, status_code

    partial_input = parsed["partial_input"]
    preferred_language = parsed["preferred_language"]
    logging.info(
        "autocomplete_llm_request preferred_language=%s input_length=%d",
        preferred_language,
        len(partial_input),
    )

    if not partial_input:
        return jsonify({"suggestions": []})

    client = _client_for_model(FAST_MODEL)

    async def fetch_api_suggestions() -> list[str]:
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
        return parse_autocomplete_suggestions(content)

    try:
        suggestions = asyncio.run(fetch_api_suggestions())
    except Exception as exc:
        logging.exception("api_autocomplete_failed query=%s", partial_input)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"suggestions": suggestions})


@app.route("/api/generate-sentence", methods=["POST"])
@main_limit
def generate_sentence():
    data = request.json
    timestamp = data.get("timestamp", 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    words = data.get("words", [])
    model = data.get("model")

    if not words or len(words) < 2:
        return jsonify({"error": "Not enough words provided."}), 400
    if model not in MODELS:
        logging.warning("generate_sentence_unsupported_model model=%s", model)
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    try:
        client = _client_for_model(model)

        async def fetch_sentence_result() -> object:
            request_kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": lucky_system_content()},
                    {"role": "user", "content": f"Input Words: {json.dumps(words, ensure_ascii=False, indent=None)}"},
                ],
            }
            request_kwargs.update(_model_request_params(model, "generate_sentence"))
            return await client.chat.completions.create(**request_kwargs)

        response = asyncio.run(fetch_sentence_result())

        content = response.choices[0].message.content
        logging.info("lucky_response_received word_count=%d content_length=%d", len(words), len(content or ""))
        return jsonify(safe_json(content))

    except Exception as e:
        logging.exception("generate_sentence_failed")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False, port=5000)
