import json
import os
from typing import Dict

RATE_LIMIT = float(os.environ.get("RATE_LIMIT", "60"))  # requests per minute
RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
DEFAULT_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "config.json"))
CONFIG_PATH = os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH)
AUTOCOMPLETE_INDEX_PATH = os.environ.get(
    "LOCAL_LEXICON_PATH",
    os.environ.get(
        "AUTOCOMPLETE_INDEX_PATH",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "lexicon.json.xz")),
    ),
)
MAIN_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT)))
AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE = max(1, int(round(RATE_LIMIT * 3)))


def _require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Invalid backend config: '{field_name}' must be a non-empty string.")
    return value.strip()


def load_backend_config(config_path: str = CONFIG_PATH) -> dict:
    if not os.path.exists(config_path):
        raise RuntimeError(
            f"Backend config file not found at {config_path}. "
            "Create it from apps/api/config_example.json or set CONFIG_PATH."
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Failed to load backend config from {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Invalid backend config: root must be a JSON object.")
    return data


def load_models(config: dict | None = None) -> Dict[str, str]:
    config = config or {}
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise RuntimeError("Invalid backend config: 'models' must be a non-empty list.")

    valid_models: Dict[str, str] = {}
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise RuntimeError(f"Invalid backend config: models[{index}] must be an object.")
        model_id = _require_non_empty_string(model.get("id"), f"models[{index}].id")
        model_name = _require_non_empty_string(model.get("name"), f"models[{index}].name")
        if model_id in valid_models:
            raise RuntimeError(f"Invalid backend config: duplicate model id '{model_id}'.")
        valid_models[model_id] = model_name
    return valid_models


def load_fast_model(config: dict, models: Dict[str, str]) -> str:
    fast_model = _require_non_empty_string(config.get("fast_model"), "fast_model")
    if fast_model not in models:
        raise RuntimeError(f"Invalid backend config: fast_model '{fast_model}' is not listed in models.")
    return fast_model


def load_provider_configs(config: dict, environ: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    environ = environ or os.environ
    providers = config.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise RuntimeError("Invalid backend config: 'providers' must be a non-empty object.")

    resolved: dict[str, dict[str, str]] = {}
    for provider_name, provider in providers.items():
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise RuntimeError("Invalid backend config: provider names must be non-empty strings.")
        if not isinstance(provider, dict):
            raise RuntimeError(f"Invalid backend config: providers.{provider_name} must be an object.")
        base_url = _require_non_empty_string(provider.get("base_url"), f"providers.{provider_name}.base_url")
        api_key_env_name = _require_non_empty_string(provider.get("api_key"), f"providers.{provider_name}.api_key")
        api_key = environ.get(api_key_env_name)
        if not api_key:
            raise RuntimeError(
                f"Invalid backend config: providers.{provider_name}.api_key points to missing env var '{api_key_env_name}'."
            )
        resolved[provider_name.strip()] = {
            "base_url": base_url,
            "api_key": api_key,
        }
    return resolved


def load_model_providers(
    config: dict,
    models: Dict[str, str],
    providers: dict[str, dict[str, str]],
    fast_model: str,
) -> dict[str, str]:
    mapping = config.get("model_providers")
    if not isinstance(mapping, dict) or not mapping:
        raise RuntimeError("Invalid backend config: 'model_providers' must be a non-empty object.")

    resolved: dict[str, str] = {}
    for model_id in models:
        provider_name = mapping.get(model_id)
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise RuntimeError(f"Invalid backend config: missing provider mapping for model '{model_id}'.")
        provider_name = provider_name.strip()
        if provider_name not in providers:
            raise RuntimeError(
                f"Invalid backend config: model '{model_id}' references unknown provider '{provider_name}'."
            )
        resolved[model_id] = provider_name

    for model_id in mapping:
        if model_id not in models:
            raise RuntimeError(
                f"Invalid backend config: model_providers contains unsupported model '{model_id}'."
            )

    if fast_model not in resolved:
        raise RuntimeError(f"Invalid backend config: fast_model '{fast_model}' has no provider mapping.")
    return resolved


BACKEND_CONFIG = load_backend_config()
MODELS = load_models(BACKEND_CONFIG)
FAST_MODEL = load_fast_model(BACKEND_CONFIG, MODELS)
PROVIDER_CONFIGS = load_provider_configs(BACKEND_CONFIG)
MODEL_PROVIDERS = load_model_providers(BACKEND_CONFIG, MODELS, PROVIDER_CONFIGS, FAST_MODEL)
