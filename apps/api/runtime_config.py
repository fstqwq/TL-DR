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
MAIN_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT)))
AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT * 3)))


def load_models(config_path: str = CONFIG_PATH) -> Dict[str, str]:
    default_models = {
        "openai/gpt-oss-120b": "GPT OSS 120B",
        "openai/gpt-oss-20b": "GPT OSS 20B",
        "meta-llama/Llama-3.3-70B-Instruct": "Llama3.3 70B (FP8)",
        "Qwen/Qwen3-Next-80B-A3B-Instruct": "Qwen3 Next 80BA3B Instruct",
        "Qwen/Qwen3-Next-80B-A3B-Thinking": "Qwen3 Next 80BA3B Thinking",
        "Qwen/Qwen3-235B-A22B": "Qwen3 235B A22B (FP8)",
        "deepseek-ai/DeepSeek-V3": "DeepSeek V3 (FP8)",
    }

    if not os.path.exists(config_path):
        print(f"Config file not found at {config_path}, using default models.")
        return default_models

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            if "MODELS" in config and isinstance(config["MODELS"], list):
                return {m["id"]: m["name"] for m in config["MODELS"]}
            return default_models
    except Exception as e:
        print(f"Error loading config: {e}")
        return default_models


MODELS = load_models()
