import json
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

try:
    from .api_helpers import (
        create_openai_client,
        lookupdictionary,
        parse_autocomplete_suggestions,
        safe_json,
    )
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
        BASE_URL,
        MAIN_RATE_LIMIT_PER_MINUTE,
        MODELS,
        RATE_LIMIT_STORAGE_URI,
    )
except ImportError:
    from api_helpers import (
        create_openai_client,
        lookupdictionary,
        parse_autocomplete_suggestions,
        safe_json,
    )
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


@app.route("/api/lookup", methods=["POST"])
@main_limit
def lookup_word():
    data = request.json
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

    try:
        client = OPENAI_CLIENT
        augmented_content = lookupdictionary(query)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": lookup_system_content()},
                {"role": "user", "content": lookup_user_content(query, preferred_language, augmented_content)},
            ],
            temperature=0.1,
            response_format={"type": "json_schema"},
        )

        content = response.choices[0].message.content
        print(f"Raw response content: {content}")
        return jsonify(safe_json(content))

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


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
    model = data.get("model")
    if model not in MODELS:
        print(f"Unsupported model requested: {model}")
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    try:
        client = OPENAI_CLIENT
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": AUTOCOMPLETE_PROMPT},
                {"role": "user", "content": (f"Language: {preferred_language}\n" if preferred_language != "auto" else "") + f"Input: {partial_input}"},
            ],
            temperature=0,
            max_tokens=32,
        )

        content = response.choices[0].message.content or ""
        suggestions = parse_autocomplete_suggestions(content)
        return jsonify({"suggestions": suggestions})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


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
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": lucky_system_content()},
                {"role": "user", "content": f"Input Words: {json.dumps(words, ensure_ascii=False, indent=None)}"},
            ],
            response_format={"type": "json_schema"},
        )

        content = response.choices[0].message.content
        print(f"Lucky response: {content}")
        return jsonify(safe_json(content))

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False, port=5000)
