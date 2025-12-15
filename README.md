<div align="center">
    <a href="https://github.com/fstqwq/TL-DR">
        <img src="./public/favicon.svg" alt="TL;DR Logo" width="100" height="100"/>
    </a>
</div>

# Tri-Lingual Dictionary Remastered (TL;DR)

An application that translates words between Chinese, English, and Japanese. It is designed to be useful for multi-language learners, including features like pronunciation, fuzzy search, history, random sentence generation, and vocabulary quizzes.

> Who needs a traditional dictionary when you have a Large Language Model? In the year of 2025, many translation apps have turned into LLM-powered applications. However, some of them will charge you subscription fees or limit your usage. At the same time, using chatbots directly --- like ChatGPT or Gemini --- is very heavy, and chatbots do not always provide desired information in a single response unless you carefully craft your prompts.
>
> Of course, this project is also vibe coded by [Gemini 3.0 Pro](https://aistudio.google.com/apps).

This project aims to provide a free and open-source alternative for tri-lingual dictionary needs --- at the cost of using your own LLM API key, which should be inexpensive nowadays.

You can try the demo [here](http://anon.fstqwq.pw/). Please be gentle, as my wallet is crying.

## Features
*   **Auto-Correction:** Empowered by LLM, it suggests corrections for misspelled words.
*   **Pronunciation:** Browser native TTS (Text-To-Speech).
*   **History:** Saves recent searches to LocalStorage.
*   **"I'm Feeling Lucky":** Random sentence generation based on recent searches.
*   **Pop Quiz:** Memorize vocabulary with spaced repetition quizzes.

## Known Issues

*   The pronunciation feature for certain languages may not work on some platforms, for example, Chinese Android devices like Xiaomi will not support Japanese TTS. To fix this, you may consider installing Google TTS (Speech Recognition & Synthesis) from Play Store.
*   The LLM may not return correct results, especially the pronunciations for words with multiple readings in Chinese and Japanese. The system TTS may also mispronounce some words.

## Deployment

### Frontend Setup

Create `public/config.json` based on `config_example.json`.
*   **BACKEND_URL**: The URL of the backend API. For local usage, this should be `http://127.0.0.1:5000`.
*   **MODELS**: A list of available LLM models.

Then, run the following command to build the frontend:
```bash
npm run build
```
Place the contents of the `dist` folder on your web server.

### Backend Setup

1.  **Install Python requirements:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the Backend Server:**
    ```bash
    API_KEY=your_api_key_here BASE_URL=https://api.your-llm-provider.com/ RATE_LIMIT=60 CONFIG_PATH=./path/to/your/config.json python app.py
    ```
    *You should see "Running on http://127.0.0.1:5000"*

3. **For public usage:**
    If you decide to deploy the backend server for public usage, consider modifying the authentication logic in `app.py` and use a WSGI server like Gunicorn. At least, you should not expose it directly without a reverse proxy like Nginx.