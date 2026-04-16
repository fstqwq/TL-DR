# API Backend

The Flask backend for TL;DR. It serves the dictionary lookup API and exposes separate local and LLM autocomplete endpoints.

## ⚙️ Configuration

The backend reads its config from `apps/api/config.json` by default. You can override the path with `CONFIG_PATH`:

```bash
export CONFIG_PATH="/absolute/path/to/tldr-api.json"
```

The config file shape is:

```json
{
  "models": [
    { "id": "deepseek-ai/DeepSeek-V3-0324", "name": "DeepSeek V3 0324" }
  ],
  "fast_model": "deepseek-ai/DeepSeek-V3-0324",
  "model_providers": {
    "deepseek-ai/DeepSeek-V3-0324": "hyperbolic"
  },
  "providers": {
    "hyperbolic": {
      "base_url": "https://api.hyperbolic.xyz/v1/",
      "api_key": "HYPERBOLIC_API_KEY"
    }
  }
}
```

> [!IMPORTANT]
> - `providers.<name>.api_key` is the **name of an environment variable**, not the raw API key.
> - Every model in `models` must also appear in `model_providers`.
> - `fast_model` must also appear in `models` and `model_providers`.

### Frontend Config

`apps/web/public/config.json` controls the browser-side settings (`BACKEND_URL`, `MODELS`). The backend does not read that file — keep the frontend `MODELS` list aligned with the backend config manually, otherwise the browser may offer a model that the backend rejects.

## 🚀 Running

From the repo root:

```bash
export API_KEY="your_api_key"  # for the default sample config
export RATE_LIMIT="60"      # requests per minute, optional
python apps/api/app.py
```

You should see `Running on http://127.0.0.1:5000`.

If your `providers` config uses a different environment variable name, export that name instead.

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `CONFIG_PATH` | Path to backend config file | `apps/api/config.json` |
| `API_KEY` | LLM provider API key for the default sample config | — |
| `RATE_LIMIT` | Max requests per minute | — |
| `LOCAL_LEXICON_PATH` | Path to local autocomplete index | `apps/api/data/lexicon.json.xz` |

### Production Deployment

For public deployments, do **not** expose the Flask dev server directly. Use a WSGI server (e.g. Gunicorn) behind a reverse proxy (e.g. Nginx), and consider customizing the authentication logic in `app.py`.

## 📖 Local Autocomplete

An optional offline dictionary index that provides instant suggestions without an LLM round-trip.

- **Code:** `local_autocomplete.py`
- **Generated file:** `data/lexicon.json.xz` (JSON + xz, not committed to git)
- If the file is missing, the backend still starts — `/api/autocomplete/local` returns an empty list.

Local `zh/ja` dictionary entries are also used to augment `/api/lookup` results when available.

### Building the Index

```bash
pip install -r apps/api/requirements-build.txt
python apps/api/scripts/build_autocomplete_index.py
```

The build script will:
1. Check for existing source data files in `apps/api/data/`
2. Download any missing source files
3. Build the ranked index → `apps/api/data/lexicon.json.xz`

Each entry stores: `surface`, `reading`, `lang`, `meaning`, and alias groups. The backend rebuilds the in-memory alias index at startup.

### Source Datasets

| Dataset | Local File | License |
|---|---|---|
| [CC-CEDICT](https://cc-cedict.org/wiki/) | `data/cc-cedict.txt.gz` | CC BY-SA 4.0 |
| [JMdict](https://www.edrdg.org/edrdg/licence.html) | `data/JMdict_e.gz` | CC BY-SA 4.0 |
| [CMUdict](https://github.com/cmusphinx/cmudict) | `data/cmudict.dict` | BSD-2-Clause |
| [wordfreq](https://github.com/rspeer/wordfreq/) | pip package | Apache-2.0 |

> [!WARNING]
> **Windows users:** `wordfreq[cjk]` pulls in `mecab-python3`, which requires the Microsoft Visual C++ Redistributable. A successful `pip install` alone is not enough — verify with:
> ```bash
> python -c "from wordfreq import zipf_frequency; print(zipf_frequency('私', 'ja'))"
> ```

## 🔌 API Endpoints

### `POST /api/lookup`

Dictionary lookup with LLM translation. Returns a `text/event-stream` with events in this order:

1. `progress` (`stage=augment`)
2. `sources`
3. `progress` (`stage=generate`)
4. `result`

When local dictionary data is available, lookup augmentation includes matching `zh/ja` entries in this format:

```text
surface [reading]
meaning
```

### `POST /api/autocomplete/local`

Local dictionary autocomplete (no LLM call).

**Request:**
```json
{
  "partialInput": "oyasu",
  "preferredLanguage": "ja",
  "timestamp": 1710000000000
}
```

**Response:**
```json
{
  "suggestions": [
    {"surface": "おやすみ", "reading": "おやすみ", "meaning": "- good night", "lang": "ja"}
  ]
}
```

### `POST /api/autocomplete/llm`

LLM-powered autocomplete suggestions.

**Request:**
```json
{
  "partialInput": "oyasu",
  "preferredLanguage": "ja",
  "timestamp": 1710000000000
}
```

**Response:**
```json
{
  "suggestions": ["おやすみ", "おやす", "おやすみなさい"]
}
```
