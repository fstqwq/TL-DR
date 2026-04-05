# API Backend

This backend serves the normal dictionary API, and it can also use a local autocomplete index file before asking the remote LLM.

## Local autocomplete file

The local autocomplete code is in:

```text
apps/api/local_autocomplete.py
```

At runtime it looks for this generated file by default:

```text
apps/api/data/autocomplete.compact.xz
```

You can override the path with:

```text
AUTOCOMPLETE_INDEX_PATH=/absolute/path/to/autocomplete.compact.xz
```

If the file is missing, the backend still starts. `/api/autocomplete` still works, but the first `local` SSE event returns an empty list.

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
- writes the result to `apps/api/data/autocomplete.compact.xz`

The build uses these datasets and local files:

- `CC-CEDICT`
  - local file: `apps/api/data/cc-cedict.txt.gz`
- `JMdict`
  - local file: `apps/api/data/JMdict_e.gz`
- `SCOWL`
  - local file: `apps/api/data/scowl-2020.12.07.tar.gz`
- `wordfreq`
  - Python package installed from `apps/api/requirements-build.txt`
  - used with CJK extras so Chinese and Japanese frequency lookups work during the build

The script also requires the Python package `wordfreq[cjk]` from `apps/api/requirements-build.txt`.

## Source data and licenses

- `CC-CEDICT`
  - download source: `https://cc-cedict.org/editor/editor_export_cedict.php?c=gz`
  - license: `CC BY-SA 4.0`
  - page: `https://cc-cedict.org/wiki/`

- `JMdict`
  - download source: `ftp://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz`
  - license: `CC BY-SA 4.0`
  - page: `https://www.edrdg.org/edrdg/licence.html`

- `SCOWL`
  - download source: `https://downloads.sourceforge.net/wordlist/scowl-2020.12.07.tar.gz`
  - license: `SCOWL copyright notice / permissive license in the tarball Copyright file`
  - page: `http://wordlist.aspell.net/`

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
export AUTOCOMPLETE_INDEX_PATH="/absolute/path/to/autocomplete.compact.xz"
python apps/api/app.py
```

## SSE endpoints

### `POST /api/autocomplete`

Request body:

```json
{
  "partialInput": "oyasu",
  "preferredLanguage": "ja",
  "timestamp": 1710000000000
}
```

Response type:

```text
text/event-stream
```

Event order:

1. `local`
2. `api`

Example:

```text
event: local
data: {"suggestions":["おやすみ","おやすみなさい"]}

event: api
data: {"suggestions":["おやすみ","おやす","おやすみなさい"]}
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

## Frontend config

`apps/web/public/config.json` still controls:

- `BACKEND_URL`
- `MODELS`
- `FAST_MODEL`

`FAST_MODEL` is only used by backend autocomplete. The frontend no longer sends a `model` field for `/api/autocomplete`.
