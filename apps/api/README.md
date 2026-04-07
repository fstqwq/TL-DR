# API Backend

This backend serves the normal dictionary API, and it exposes separate local and LLM autocomplete endpoints.

## Local autocomplete file

The local autocomplete code is in:

```text
apps/api/local_autocomplete.py
```

At runtime it looks for this generated file by default:

```text
apps/api/data/lexicon.json.xz
```

You can override the path with:

```text
LOCAL_LEXICON_PATH=/absolute/path/to/lexicon.json.xz
```

The backend still accepts the old `AUTOCOMPLETE_INDEX_PATH` env var for compatibility, but `LOCAL_LEXICON_PATH` is the preferred name now.

If the file is missing, the backend still starts. `/api/autocomplete/local` still works, but it returns an empty list.

The generated artifact is now `JSON+xz`, not pickle. It stores ranked dictionary entries with `surface`, `reading`, `lang`, `meaning`, and per-entry alias groups. The backend rebuilds the in-memory alias index at startup.

## How to build the local autocomplete file

Install the extra build dependency first:

```bash
pip install -r apps/api/requirements-build.txt
```

Then run the build script from the repo root:

```bash
python apps/api/scripts/build_autocomplete_index.py
```

What this script does:

- checks whether the required source data files already exist in `apps/api/data/`
- downloads missing source data files
- verifies the downloaded files
- builds the local autocomplete index
- writes the result to `apps/api/data/lexicon.json.xz`

The build uses these datasets and local files:

- `CC-CEDICT`
  - local file: `apps/api/data/cc-cedict.txt.gz`
- `JMdict`
  - local file: `apps/api/data/JMdict_e.gz`
- `CMUdict`
  - local file: `apps/api/data/cmudict.dict`
- `wordfreq`
  - Python package installed from `apps/api/requirements-build.txt`
  - used with CJK extras so Chinese and Japanese frequency lookups work during the build-time ranking pass

The build environment must install the CJK extras from `apps/api/requirements-build.txt`:

```bash
pip install "wordfreq[cjk]"
```

Without the `cjk` extras, Japanese frequency lookups can fail at build time.

On Windows, `wordfreq[cjk]` pulls in `mecab-python3` for Japanese tokenization. The upstream `mecab-python3` wheels also require the Microsoft Visual C++ Redistributable, so a successful `pip install` is not sufficient by itself. Verify the runtime with:

```bash
python -c "from wordfreq import zipf_frequency; print(zipf_frequency('私', 'ja'))"
```

## Source data and licenses

- `CC-CEDICT`
  - download source: `https://cc-cedict.org/editor/editor_export_cedict.php?c=gz`
  - license: `CC BY-SA 4.0`
  - page: `https://cc-cedict.org/wiki/`

- `JMdict`
  - download source: `ftp://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz`
  - license: `CC BY-SA 4.0`
  - page: `https://www.edrdg.org/edrdg/licence.html`

- `CMUdict`
  - download source: `https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict`
  - license: `BSD-2-Clause`
  - page: `https://github.com/cmusphinx/cmudict`

- `wordfreq`
  - download source: `https://pypi.org/project/wordfreq/`
  - license: `Apache-2.0`
  - page: `https://github.com/rspeer/wordfreq/`

## Running the backend

Example on bash, from the repo root:

```bash
export API_KEY="your_api_key"
export BASE_URL="https://api.hyperbolic.xyz/v1/"
export RATE_LIMIT="60"
python apps/api/app.py
```

If you want to use a different local autocomplete file path:

```bash
export LOCAL_LEXICON_PATH="/absolute/path/to/lexicon.json.xz"
python apps/api/app.py
```

## Autocomplete endpoints

### `POST /api/autocomplete/local`

Request body:

```json
{
  "partialInput": "oyasu",
  "preferredLanguage": "ja",
  "timestamp": 1710000000000
}
```

Response type:

```json
{
  "suggestions": [
    {"surface": "おやすみ", "reading": "おやすみ", "meaning": "- good night", "lang": "ja"}
  ]
}
```

### `POST /api/autocomplete/llm`

Request body:

```json
{
  "partialInput": "oyasu",
  "preferredLanguage": "ja",
  "timestamp": 1710000000000
}
```

Response type:

```json
{
  "suggestions": ["おやすみ", "おやす", "おやすみなさい"]
}
```

### `POST /api/lookup`

Response type:

```text
text/event-stream
```

Event order:

1. `progress` with `stage=augment`
2. `sources`
3. `progress` with `stage=generate`
4. `result`

Lookup augmentation now also includes the local `zh/ja` dictionary entries when available. The local snippet format is:

```text
surface [reading]
meaning
```

## Frontend config

`apps/web/public/config.json` still controls:

- `BACKEND_URL`
- `MODELS`
- `FAST_MODEL`

`FAST_MODEL` is only used by backend autocomplete. The frontend no longer sends a `model` field for autocomplete requests.
