import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
API_DIR = ROOT_DIR / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

os.environ.setdefault("CONFIG_PATH", str(API_DIR / "config_example.json"))
os.environ.setdefault("API_KEY", "unit-test-key")
os.environ.setdefault("CLARIFAI_API_KEY", "unit-test-clarifai-key")

import runtime_config  # noqa: E402


class RuntimeConfigTestCase(unittest.TestCase):
    def test_load_model_params_returns_validated_params(self):
        config = {
            "models": [
                {
                    "id": "model-a",
                    "name": "Model A",
                    "params": {
                        "reasoning_effort": "none",
                        "temperature": 0.2,
                        "max_completion_tokens": 128,
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                        "response_format": {"type": "json_schema"},
                    },
                }
            ]
        }

        result = runtime_config.load_model_params(config)

        self.assertEqual(
            result,
            {
                "model-a": {
                    "reasoning_effort": "none",
                    "temperature": 0.2,
                    "max_completion_tokens": 128,
                    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    "response_format": {"type": "json_schema"},
                }
            },
        )

    def test_load_model_params_rejects_unknown_param_key(self):
        config = {
            "models": [
                {
                    "id": "model-a",
                    "name": "Model A",
                    "params": {
                        "thinking": False,
                    },
                }
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "is not supported"):
            runtime_config.load_model_params(config)

    def test_load_model_params_rejects_invalid_reasoning_effort(self):
        config = {
            "models": [
                {
                    "id": "model-a",
                    "name": "Model A",
                    "params": {
                        "reasoning_effort": "minimal",
                    },
                }
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "must be one of"):
            runtime_config.load_model_params(config)

    def test_load_model_params_rejects_invalid_response_format(self):
        config = {
            "models": [
                {
                    "id": "model-a",
                    "name": "Model A",
                    "params": {
                        "response_format": "json_schema",
                    },
                }
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "must be an object"):
            runtime_config.load_model_params(config)

    def test_load_provider_configs_resolves_env_named_in_api_key_field(self):
        config = {
            "providers": {
                "hyperbolic": {
                    "base_url": "https://api.hyperbolic.xyz/v1/",
                    "api_key": "HYPERBOLIC_API_KEY",
                }
            }
        }

        result = runtime_config.load_provider_configs(
            config,
            environ={"HYPERBOLIC_API_KEY": "secret-token"},
        )

        self.assertEqual(
            result,
            {
                "hyperbolic": {
                    "base_url": "https://api.hyperbolic.xyz/v1/",
                    "api_key": "secret-token",
                }
            },
        )

    def test_load_provider_configs_requires_existing_env_var(self):
        config = {
            "providers": {
                "hyperbolic": {
                    "base_url": "https://api.hyperbolic.xyz/v1/",
                    "api_key": "HYPERBOLIC_API_KEY",
                }
            }
        }

        with self.assertRaisesRegex(RuntimeError, "missing env var 'HYPERBOLIC_API_KEY'"):
            runtime_config.load_provider_configs(config, environ={})

    def test_load_model_providers_requires_every_model_mapping(self):
        models = {"model-a": "Model A"}
        providers = {"hyperbolic": {"base_url": "https://example.com", "api_key": "secret"}}
        config = {"model_providers": {}}

        with self.assertRaisesRegex(RuntimeError, "'model_providers' must be a non-empty object"):
            runtime_config.load_model_providers(config, models, providers, "model-a")

    def test_load_backend_config_requires_json_object(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(json.dumps(["not", "an", "object"]))
            temp_path = handle.name

        try:
            with self.assertRaisesRegex(RuntimeError, "root must be a JSON object"):
                runtime_config.load_backend_config(temp_path)
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
