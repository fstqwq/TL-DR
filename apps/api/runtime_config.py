import json
import os
from typing import Dict

# Setup configuration from environment variables.
# Run with command like:
# API_KEY=your_api_key BASE_URL=https://api.hyperbolic.xyz/v1/ RATE_LIMIT=60 python apps/api/app.py
API_KEY = os.environ.get("API_KEY", None)
BASE_URL = os.environ.get("BASE_URL", "https://api.hyperbolic.xyz/v1/")
RATE_LIMIT = float(os.environ.get("RATE_LIMIT", "60"))  # requests per minute
RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
DEFAULT_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "web", "public", "config.json")
)
CONFIG_PATH = os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH)
AUTOCOMPLETE_INDEX_PATH = os.environ.get(
    "AUTOCOMPLETE_INDEX_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "autocomplete.compact.xz")),
)
MAIN_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT)))
AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT * 3)))
DEFAULT_MODELS = {
    "openai/gpt-oss-120b": "GPT OSS 120B",
    "openai/gpt-oss-20b": "GPT OSS 20B",
    "meta-llama/Llama-3.3-70B-Instruct": "Llama3.3 70B (FP8)",
    "Qwen/Qwen3-Next-80B-A3B-Instruct": "Qwen3 Next 80BA3B Instruct",
    "Qwen/Qwen3-Next-80B-A3B-Thinking": "Qwen3 Next 80BA3B Thinking",
    "Qwen/Qwen3-235B-A22B": "Qwen3 235B A22B (FP8)",
    "deepseek-ai/DeepSeek-V3": "DeepSeek V3 (FP8)",
}


def load_web_config(config_path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(config_path):
        print(f"Config file not found at {config_path}, using default models.")
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}


def load_models(config: dict | None = None) -> Dict[str, str]:
    config = config or {}
    models = config.get("MODELS")
    if isinstance(models, list):
        valid_models = {
            m["id"]: m["name"]
            for m in models
            if isinstance(m, dict) and isinstance(m.get("id"), str) and isinstance(m.get("name"), str)
        }
        if valid_models:
            return valid_models
    return DEFAULT_MODELS


def load_fast_model(config: dict, models: Dict[str, str]) -> str:
    configured = os.environ.get("FAST_MODEL")
    if not configured and isinstance(config.get("FAST_MODEL"), str):
        configured = config["FAST_MODEL"]
    if configured in models:
        return configured
    return next(iter(models.keys()))


WEB_CONFIG = load_web_config()
MODELS = load_models(WEB_CONFIG)
FAST_MODEL = load_fast_model(WEB_CONFIG, MODELS)
