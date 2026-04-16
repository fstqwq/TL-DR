<div align="center">
    <a href="https://github.com/fstqwq/TL-DR">
        <img src="./apps/web/public/favicon.svg" alt="TL;DR Logo" width="100" height="100"/>
    </a>
</div>

# TL;DR — Tri-Lingual Dictionary Remastered

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A free, open-source dictionary that translates words between **Chinese**, **English**, and **Japanese** — powered by the LLM of your choice.

> 🌐 **[Try the live demo](https://anon.fstqwq.pw/)**

Many translation apps have turned into LLM-powered services with subscription fees or usage limits. Using chatbots directly is heavy and requires careful prompting. TL;DR gives you a clean dictionary interface backed by any OpenAI-compatible LLM API — at the cost of your own API key, which should be inexpensive nowadays.

## Features

- 🔍 **Smart Lookup** — Translates between Chinese, English, and Japanese with LLM-powered auto-correction for misspelled words.
- 🗣️ **Pronunciation** — Built-in text-to-speech using your browser's native TTS engine.
- 🕒 **Search History** — Recent searches are saved locally in your browser.
- 🎲 **"I'm Feeling Lucky"** — Generates a random sentence based on your recent searches.
- 📝 **Pop Quiz** — Memorize vocabulary with spaced repetition quizzes, inspired by Anki.
- ⚡ **Local Autocomplete** — Optional offline dictionary index for instant suggestions (no LLM round-trip needed).

## Quick Start

### Prerequisites

- [Node.js](https://nodejs.org/) (for building the frontend)
- [Python 3](https://www.python.org/) (for the backend)
- An API key from any OpenAI-compatible LLM provider

### 1. Clone & Install

```bash
git clone https://github.com/fstqwq/TL-DR.git
cd TL-DR
cd apps/web && npm install && cd ../..
pip install -r apps/api/requirements.txt
```

### 2. Configure

**Frontend** — Copy the example config and edit it:

```bash
cp apps/web/config_example.json apps/web/public/config.json
```

Set `BACKEND_URL` to `http://127.0.0.1:5000` for local use, and adjust the `MODELS` list to match the models you have access to.

**Backend** — Edit `apps/api/config.json` to add your LLM provider(s). Each provider needs a `base_url` and the *name* of an environment variable that holds your API key (not the key itself). See [apps/api/README.md](apps/api/README.md) for the full config reference.

### 3. Run

```bash
# Terminal 1 — Backend
API_KEY=your_api_key_here python apps/api/app.py

# Terminal 2 — Frontend (dev mode)
npm run dev
```

The frontend dev server will print a local URL (usually `http://localhost:3000`). Open it in your browser and start searching!

### Building for Production

```bash
npm run build
```

The output in `apps/web/dist` can be served by any static file server (Nginx, Caddy, etc.). For public deployments, consider placing the backend behind a reverse proxy — see [apps/api/README.md](apps/api/README.md) for details.

## Known Issues

- **TTS on some Android devices** — Chinese Android devices (e.g. Xiaomi) may not support Japanese TTS. Installing [Google TTS](https://play.google.com/store/apps/details?id=com.google.android.tts) from Play Store can fix this.
- **LLM accuracy** — The LLM may return incorrect results, especially pronunciations for words with multiple readings in Chinese and Japanese.

## License

[MIT](LICENSE) for code.

## Acknowledgments

This project uses the following open data sources for its local dictionary by default:

- [CC-CEDICT](https://cc-cedict.org/wiki/) (CC BY-SA 4.0) — Chinese-English dictionary
- [JMdict](https://www.edrdg.org/edrdg/licence.html) (CC BY-SA 4.0) — Japanese-English dictionary
- [CMUdict](https://github.com/cmusphinx/cmudict) (BSD-2-Clause) — English pronunciation dictionary
