import os
import json
from urllib.parse import quote
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# Setup configuration from environment variables.
# Run with command like:
# API_KEY=your_api_key BASE_URL=https://api.hyperbolic.xyz/v1/ RATE_LIMIT=60 python app.py
API_KEY = os.environ.get("API_KEY", None)
BASE_URL = os.environ.get("BASE_URL", "https://api.hyperbolic.xyz/v1/")
RATE_LIMIT = float(os.environ.get("RATE_LIMIT", "60"))  # requests per minute
CONFIG_PATH = os.environ.get("CONFIG_PATH", "public/config.json")

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

def load_models():
    default_models = {
        'openai/gpt-oss-120b': 'GPT OSS 120B',
        'openai/gpt-oss-20b': 'GPT OSS 20B',
        'meta-llama/Llama-3.3-70B-Instruct': 'Llama3.3 70B (FP8)',
        'Qwen/Qwen3-Next-80B-A3B-Instruct': 'Qwen3 Next 80BA3B Instruct',
        'Qwen/Qwen3-Next-80B-A3B-Thinking': 'Qwen3 Next 80BA3B Thinking',
        'Qwen/Qwen3-235B-A22B': 'Qwen3 235B A22B (FP8)',
        'deepseek-ai/DeepSeek-V3': 'DeepSeek V3 (FP8)',
    }
    
    if not os.path.exists(CONFIG_PATH):
        print(f"Config file not found at {CONFIG_PATH}, using default models.")
        return default_models

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
            if 'MODELS' in config and isinstance(config['MODELS'], list):
                return {m['id']: m['name'] for m in config['MODELS']}
            return default_models
    except Exception as e:
        print(f"Error loading config: {e}")
        return default_models

MODELS = load_models()
import re
def safe_json(text: str):
    split_flags = ['</think>', '<|message|>']
    for flag in split_flags:
        if flag in text:
            text = text.split(flag)[-1]
    if '```' in text:
        text = text.split('```')[1]
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return json.loads(m.group(0) if m else "{}")
    except Exception:
        return {}

def parse_autocomplete_suggestions(text: str):
    if not text:
        return []
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    suggestions = []
    for line in lines:
        line = re.sub(r"^[\s\-\*\d\.\)\(]+", "", line).strip()
        if not line:
            continue
        if line not in suggestions:
            suggestions.append(line)
        if len(suggestions) >= 3:
            break
    return suggestions

import time
last_query = -1
last_autocomplete_query = -1

def rate_limit():
    global last_query
    now = time.time()
    if last_query != -1 and now - last_query < 1 / RATE_LIMIT * 60:
        return False
    last_query = time.time()
    return True

def rate_limit_autocomplete():
    global last_autocomplete_query
    now = time.time()
    if last_autocomplete_query != -1 and now - last_autocomplete_query < 1 / RATE_LIMIT * 20:
        return False
    last_autocomplete_query = time.time()
    return True

scraper = cloudscraper.create_scraper()
from functools import lru_cache
@lru_cache(maxsize=128)
def fetch_first_kiji_text(word: str) -> str:
    """
    Fetch the Weblio page for the given word and return the text of the first element with class 'kiji'.
    Return an empty string if the request fails.
    """
    url = f"https://www.weblio.jp/content/{quote(word)}"
    resp = scraper.get(
        url,
        timeout=1,
    )
    if resp.status_code != 200:
        return ""
    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    kiji = soup.find(class_="kiji")
    if not kiji:
        return ""
    return kiji.get_text(strip=True, separator="")[:1000]

@app.route('/api/lookup', methods=['POST'])
def lookup_word():
    if not API_KEY:
        return jsonify({"error": "API_KEY not configured on server"}), 500
    if not rate_limit():
        return jsonify({"error": "Rate limit exceeded."}), 429
    data = request.json
    timestamp = data.get('timestamp', 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    query = data.get('query')
    model = data.get('model')
    preferred_language = data.get('preferredLanguage', 'auto')
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        print("No query provided in the request.")
        return jsonify({"error": "No query provided"}), 400
    if model not in MODELS:
        print(f"Unsupported model requested: {model}")
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    try:
        # Initialize the OpenAI client pointing to Google's compatibility endpoint
        client = OpenAI(
            api_key=API_KEY,
            base_url="https://api.hyperbolic.xyz/v1/"
        )

        # Define the strict schema for the response
        dictionary_schema = {
            "type": "object",
            "properties": {
            "targetWord": {
                "type": "string",
                "description": "The word being queried. This must be the corrected/standardized version of the user input (e.g., if input is '预约する', this should be '予約する').",
            },
            "detectedLanguage": {
                "type": "string",
                "enum": ["zh", "en", "ja", "unknown"],
                "description": "The detected source language of the query.",
            },
            "origin": {
                "type": "string",
                "description": "If the target word is a Japanese Katakana loanword (Gairaigo), provide the original Western word (e.g. '(English) Television' for 'テレビ'). Otherwise return null.",
            },
            "definitions": {
                "type": "object",
                "properties": {
                "zh": {"type": "string", "description": "Definition/Translation in Chinese (Simplified)."},
                "en": {"type": "string", "description": "Definition/Translation in English."},
                "ja": {"type": "string", "description": "Definition/Translation in Japanese. If the word has Kanji form, include it."},
                },
                "required": ["zh", "en", "ja"],
            },
            "translations": {
                "type": "object",
                "description": "Direct translation of the target word into each language, with its specific pronunciation.",
                "properties": {
                "zh": {
                    "type": "object",
                    "properties": {
                    "word": {"type": "string", "description": "The word in Simplified Chinese (e.g. '苹果')."},
                    "pronunciation": {"type": "string", "description": "Pinyin with tones (e.g., 'píng guǒ')."}
                    },
                    "required": ["word", "pronunciation"]
                },
                "en": {
                    "type": "object",
                    "properties": {
                    "word": {"type": "string", "description": "The word in English (e.g. 'Apple')."},
                    "pronunciation": {"type": "string", "description": "IPA notation (e.g., '/ˈæp.əl/')."}
                    },
                    "required": ["word", "pronunciation"]
                },
                "ja": {
                    "type": "object",
                    "properties": {
                    "word": {"type": "string", "description": "The word in Japanese (e.g. 'リンゴ' or '林檎')."},
                    "pronunciation": {"type": "string", "description": "Hiragana reading (e.g., 'りんご')."}
                    },
                    "required": ["word", "pronunciation"]
                },
                },
                "required": ["zh", "en", "ja"],
            },
            "synonyms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of 1-3 synonyms for the target word in its detected language."
            },
            "antonyms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of 0-3 antonyms for the target word in its detected language (if applicable)."
            },
            "exampleSentence": {
                "type": "object",
                "properties": {
                "text": {"type": "string", "description": "A short, natural example sentence containing the word in its source language."},
                "translation": {"type": "string", "description": "Translation of the sentence into English (if source is not EN) or Chinese (if source is EN)."},
                },
            },
            },
            "required": ["targetWord", "detectedLanguage", "definitions", "translations", "synonyms", "antonyms"],
        }

        augmented_content = fetch_first_kiji_text(query)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system", 
                    "content": f"""You are a smart trilingual dictionary assistant. 
Step 1: Auto-Correction & Fuzzy Matching
- Detect if the input contains typos, mixed scripts, or is close to a known word.
- Example: "预约する" (mixed Chinese/Japanese) -> "予約する" (Japanese Standard).
- Example: "aple" (typo) -> "apple".
- Use the corrected/standardized word as the "targetWord" in the JSON output.

Step 2: Analysis
- Identify the language (Chinese, English, or Japanese). If the preferred language is specified (not 'auto'), try to interpret the query in that context. Only if it is clearly from another language, mark it as such.
- If the word is a Japanese Katakana loanword (Gairaigo), identify the original Western word and put it in the 'origin' field.
- Provide the definition/translation for ALL THREE languages. Be as accurate as dictinary entries, and as concise as possible.
- Provide the EQUIVALENT WORD and PRONUNCIATION for ALL THREE languages in the 'translations' object.
- For Chinese: 'word' is Hanzi, 'pronunciation' is Pinyin.
- For English: 'word' is the English term, 'pronunciation' is IPA.
- For Japanese: 'word' is the most common written form (Kanji/Kana), 'pronunciation' is Hiragana.
Please note the difference between Hanzi and Kanji: the same literals may have different meanings in Chinese and Japanese, so you must provide distinct translations for each language, in this case, translate based on meaning rather than literal wording. For example, "直前" means "immediately before" in Japanese but not a valid term in Chinese - provide appropriate Chinese equivalent like "即将发生之前" instead.
- Provide a list of synonyms and antonyms IN THE DETECTED LANGUAGE of the target word.
- Provide one short example sentence.
- Output MUST STRICTLY follow the provided JSON SCHEMA without any deviations. Start your response directly with the {{.
{json.dumps(dictionary_schema, ensure_ascii=False, indent=None)}
"""
                },
                {
                    "role": "user",
                    "content": f"Analyze the query: \"{query}\". User preferred language context: {preferred_language} (If 'auto', detect. If specified, bias interpretation towards this language)." + (f" Additionally, you can use the following content from dictionary about the word: {augmented_content}" if augmented_content else "")
                }
            ],
            temperature=0.1,
            response_format={
                "type": "json_schema"
            }
        )

        content = response.choices[0].message.content
        print(f"Raw response content: {content}")
        return jsonify(safe_json(content))

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/autocomplete', methods=['POST'])
def autocomplete():
    if not API_KEY:
        return jsonify({"error": "API_KEY not configured on server"}), 500
    if not rate_limit_autocomplete():
        return jsonify({"error": "Rate limit exceeded."}), 429
    data = request.json or {}
    timestamp = data.get('timestamp', 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    partial_input = data.get('partialInput') or data.get('partial_input') or ""
    partial_input = partial_input.strip()
    if not partial_input:
        return jsonify({"suggestions": []})
    model = data.get('model')
    if model not in MODELS:
        print(f"Unsupported model requested: {model}")
        return jsonify({"error": f"Model '{model}' not supported."}), 400

    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url="https://api.hyperbolic.xyz/v1/"
        )

        prompt = """You are an autocomplete function for a Chinese, English, Japanese dictionary. Input is a partial string, possibly misspelled or incomplete. Infer likely intended word completions. Be skeptical: only output suggestions when highly confident; otherwise output nothing. Output words only. One suggestion per line. At most three lines. Place the most possible answer at first. No numbering, no punctuation, no explanations. Each output must be a single word or fixed dictionary form. Consider possibility of Kana / Pinyin:
zhonggu
中国
natsuyas
夏休み
Output answer without thinking."""
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{partial_input}"}
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


@app.route('/api/generate-sentence', methods=['POST'])
def generate_sentence():
    if not API_KEY:
        return jsonify({"error": "API_KEY not configured on server"}), 500
    if not rate_limit():
        return jsonify({"error": "Rate limit exceeded."}), 429

    data = request.json
    timestamp = data.get('timestamp', 0)
    if abs(time.time() - timestamp / 1000) > 15:
        return jsonify({"error": "Invalid request."}), 403
    words = data.get('words', [])
    model = data.get('model')

    if not words or len(words) < 2:
        return jsonify({"error": "Not enough words provided."}), 400

    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url="https://api.hyperbolic.xyz/v1/"
        )

        lucky_schema = {
            "type": "object",
            "properties": {
                "usedWords": { 
                    "type": "array", 
                    "items": { "type": "string" },
                    "description": "List of the specific words from the input list that were successfully used." 
                },
                "content": {
                    "type": "object",
                    "properties": {
                        "zh": { 
                            "type": "object",
                            "properties": { "text": { "type": "string" }, "pronunciation": {"type": "string", "description": "Pinyin with tones (e.g., 'píng guǒ')."} },
                            "required": ["text", "pronunciation"]
                        },
                        "en": { 
                            "type": "object",
                            "properties": { "text": { "type": "string" }, "pronunciation": {"type": "string", "description": "IPA notation (e.g., '/ˈæp.əl/')."} },
                            "required": ["text", "pronunciation"]
                        },
                        "ja": { 
                            "type": "object",
                            "properties": { "text": { "type": "string" }, "pronunciation": {"type": "string", "description": "Hiragana reading (e.g., 'りんご')."} },
                            "required": ["text", "pronunciation"]
                        },
                    },
                    "required": ["zh", "en", "ja"],
                },
            },
            "required": ["usedWords", "content"],
        }

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"""You are a creative language tutor.
Task: Create a single coherent, creative, or funny sentence that incorporates as many of the provided words as possible.
The input words can be in any of the three languages: Chinese (Simplified), English, or Japanese. When forming the sentence, you may need to adjust word forms, tenses, or use synonyms to ensure naturalness, and ensure the sentence is fully coherent in the target language.
Please note the difference between Hanzi and Kanji: the same literals may have different meanings in Chinese and Japanese, so you must provide distinct translations for each language, in this case, translate based on meaning rather than direcly using the literal wording. For example, "直前" means "immediately before" in Japanese but not a valid term in Chinese - provide appropriate Chinese equivalent like "即将发生之前" instead when forming the Chinese sentence.

Output: 
1. The sentence in English, Chinese (Simplified), and Japanese.
2. Pronunciations for all 3.
3. A list of which input words were successfully used.

Output MUST STRICTLY follow the provided JSON SCHEMA. Start your response directly with the {{.
{json.dumps(lucky_schema, ensure_ascii=False, indent=None)}
"""
                },
                {
                    "role": "user",
                    "content": f"Input Words: {json.dumps(words, ensure_ascii=False, indent=None)}"
                }
            ],
            response_format={ "type": "json_schema" }
        )

        content = response.choices[0].message.content
        print(f"Lucky response: {content}")
        return jsonify(safe_json(content))

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="127.0.0.1", debug=False, port=5000)
