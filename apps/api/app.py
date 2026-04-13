import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

try:
    from .api_helpers import (
        create_openai_client,
        lookupdictionary_bundle,
        parse_autocomplete_suggestions,
        safe_json,
    )
    from .local_autocomplete import LocalAutocomplete
    from .limiter_setup import attach_global_limiter
    from .llm_payloads import (
        AUTOCOMPLETE_PROMPT,
        lucky_system_content,
        lookup_system_content,
        lookup_user_content,
    )
    from .runtime_config import (
        API_KEY,
        AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE,
        FAST_MODEL,
        AUTOCOMPLETE_INDEX_PATH,
        BASE_URL,
        MAIN_RATE_LIMIT_PER_MINUTE,
        MODELS,
        RATE_LIMIT_STORAGE_URI,
    )
except ImportError:
    from api_helpers import (
        create_openai_client,
        lookupdictionary_bundle,
        parse_autocomplete_suggestions,
        safe_json,
    )
    from local_autocomplete import LocalAutocomplete
    from limiter_setup import attach_global_limiter
    from llm_payloads import (
        AUTOCOMPLETE_PROMPT,
        lucky_system_content,
        lookup_system_content,
        lookup_user_content,
    )
    from runtime_config import (
        API_KEY,
        AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE,
        FAST_MODEL,
        AUTOCOMPLETE_INDEX_PATH,
        BASE_URL,
        MAIN_RATE_LIMIT_PER_MINUTE,
        MODELS,
        RATE_LIMIT_STORAGE_URI,
    )

import logging

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
assert API_KEY, "API_KEY must be set."
OPENAI_CLIENT = create_openai_client(API_KEY, BASE_URL)
LOCAL_AUTOCOMPLETE = LocalAutocomplete(AUTOCOMPLETE_INDEX_PATH)
AUTOCOMPLETE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="autocomplete-api")
MAX_AUTOCOMPLETE_INPUT_LENGTH = 128


def _sse_event(name: str, payload: object) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
        print("No query provided in the request.")
        return jsonify({"error": "No query provided"}), 400
    if model not in MODELS:
        print(f"Unsupported model requested: {model}")
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    client = OPENAI_CLIENT

    @stream_with_context
    def generate():
        async def fetch_lookup_result() -> object:
            return await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": lookup_system_content()},
                    {"role": "user", "content": lookup_user_content(query, preferred_language, augmented_content)},
                ],
                temperature=0.1,
                response_format={"type": "json_schema"},
            )

        try:
            yield _sse_event(
                "progress",
                {"stage": "augment", "message": "Collecting dictionary context"},
            )
            lookup_bundle = lookupdictionary_bundle(query)
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
            print(f"Raw response content: {content}")
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


@app.route("/api/autocomplete", methods=["POST"])
@autocomplete_limit
def autocomplete():
    data = request.json or {}
    timestamp = data.get("timestamp", 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    partial_input = data.get("partialInput") or data.get("partial_input") or ""
    preferred_language = data.get("preferredLanguage", "auto")
    print(f"Autocomplete request received. Preferred language: {preferred_language}, Partial input: {partial_input}")
    partial_input = partial_input.strip()
    if not partial_input:
        return jsonify({"suggestions": []})
    if len(partial_input) > MAX_AUTOCOMPLETE_INPUT_LENGTH:
        return jsonify({"suggestions": []}), 400

    client = OPENAI_CLIENT

    @stream_with_context
    def generate():
        async def fetch_api_suggestions() -> list[str]:
            response = await client.chat.completions.create(
                model=FAST_MODEL,
                messages=[
                    {"role": "system", "content": AUTOCOMPLETE_PROMPT},
                    {
                        "role": "user",
                        "content": (f"Language: {preferred_language}\n" if preferred_language != "auto" else "")
                        + f"Input: {partial_input}",
                    },
                ],
                temperature=0,
                max_tokens=32,
            )
            content = response.choices[0].message.content or ""
            return parse_autocomplete_suggestions(content)

        api_future = AUTOCOMPLETE_EXECUTOR.submit(lambda: asyncio.run(fetch_api_suggestions()))
        local_suggestions: list[str] = []
        try:
            local_suggestions = LOCAL_AUTOCOMPLETE.search(
                partial_input,
                preferred_language=preferred_language,
                limit=3,
            )
        except Exception as exc:
            logging.exception("local_autocomplete_failed query=%s", partial_input)
            yield _sse_event("error", {"stage": "local", "message": str(exc)})
        yield _sse_event("local", {"suggestions": local_suggestions})

        api_suggestions: list[str] = []
        try:
            api_suggestions = api_future.result()
        except Exception as exc:
            logging.exception("api_autocomplete_failed query=%s", partial_input)
            yield _sse_event("error", {"stage": "api", "message": str(exc)})
        yield _sse_event("api", {"suggestions": api_suggestions})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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

    try:
        client = OPENAI_CLIENT
        async def fetch_sentence_result() -> object:
            return await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": lucky_system_content()},
                    {"role": "user", "content": f"Input Words: {json.dumps(words, ensure_ascii=False, indent=None)}"},
                ],
                response_format={"type": "json_schema"},
            )

        response = asyncio.run(fetch_sentence_result())

        content = response.choices[0].message.content
        print(f"Lucky response: {content}")
        return jsonify(safe_json(content))

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False, port=5000)
