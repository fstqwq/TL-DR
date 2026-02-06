import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from urllib.parse import quote

import cloudscraper
from bs4 import BeautifulSoup
from openai import OpenAI

logger = logging.getLogger(__name__)
HTTP_TIMEOUT_SECONDS = 1.0
LOOKUP_SOURCES_TIMEOUT_SECONDS = 2.0
MAX_SOURCE_CHARS = 1200
MAX_TOTAL_CHARS = 3200


def create_openai_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url)


def heal_json_text(text: str) -> str:
    if not isinstance(text, str):
        return "{}"

    candidate = text.replace("\ufeff", "").strip()
    split_flags = ["</think>", "<|message|>"]
    for flag in split_flags:
        if flag in candidate:
            candidate = candidate.split(flag)[-1].strip()

    if "```" in candidate:
        fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", candidate, flags=re.IGNORECASE)
        if fenced:
            candidate = fenced[0].strip()
        else:
            candidate = candidate.replace("```", "").strip()

    start_obj = candidate.find("{")
    end_obj = candidate.rfind("}")
    start_arr = candidate.find("[")
    end_arr = candidate.rfind("]")

    parse_candidates = [candidate]
    if start_obj != -1 and end_obj > start_obj:
        parse_candidates.append(candidate[start_obj : end_obj + 1])
    if start_arr != -1 and end_arr > start_arr:
        parse_candidates.append(candidate[start_arr : end_arr + 1])

    for raw_candidate in parse_candidates:
        normalized = re.sub(r"^\s*json\s*", "", raw_candidate, flags=re.IGNORECASE).strip()
        if not normalized:
            continue

        # Some models return an extra wrapper layer: {{ ... }}.
        for _ in range(3):
            if normalized.startswith("{{") and normalized.endswith("}}"):
                normalized = normalized[1:-1].strip()
            elif normalized.startswith("[[") and normalized.endswith("]]"):
                normalized = normalized[1:-1].strip()

        normalized = re.sub(r",(\s*[}\]])", r"\1", normalized)

        if normalized.startswith('"') and normalized.endswith('"'):
            try:
                inner = json.loads(normalized)
                if isinstance(inner, str):
                    normalized = inner.strip()
            except Exception:
                pass

        try:
            json.loads(normalized)
            return normalized
        except Exception:
            continue

    return "{}"


def safe_json(text: str):
    healed = heal_json_text(text)
    try:
        return json.loads(healed)
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


def _http_get_text(url: str, source: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> str:
    started_at = time.perf_counter()
    logger.info("api_helper_request_start source=%s url=%s timeout=%.2fs", source, url, timeout)
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, timeout=timeout)
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "api_helper_request_end source=%s status=%s elapsed_ms=%.1f",
        source,
        response.status_code,
        elapsed_ms,
    )
    if response.status_code != 200:
        logger.warning("api_helper_request_non_200 source=%s status=%s", source, response.status_code)
        return ""
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text or ""


def _clean_wiktionary_markup(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r", "")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\{\{[^{}]{1,120}\}\}", "", cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[:30])[:MAX_SOURCE_CHARS]


def _format_dictionaryapi_payload(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    if not isinstance(payload, list) or not payload:
        return ""
    first = payload[0] if isinstance(payload[0], dict) else {}
    if not first:
        return ""

    parts = []
    word = first.get("word")
    if isinstance(word, str) and word.strip():
        parts.append(f"word: {word.strip()}")

    phonetics = first.get("phonetics") if isinstance(first.get("phonetics"), list) else []
    phonetic_text = ""
    for item in phonetics:
        if isinstance(item, dict):
            maybe_text = item.get("text")
            if isinstance(maybe_text, str) and maybe_text.strip():
                phonetic_text = maybe_text.strip()
                break
    if phonetic_text:
        parts.append(f"phonetic: {phonetic_text}")

    meanings = first.get("meanings") if isinstance(first.get("meanings"), list) else []
    meaning_lines = []
    for meaning in meanings[:3]:
        if not isinstance(meaning, dict):
            continue
        pos = meaning.get("partOfSpeech")
        definitions = meaning.get("definitions") if isinstance(meaning.get("definitions"), list) else []
        definition_texts = []
        for item in definitions[:2]:
            if isinstance(item, dict):
                value = item.get("definition")
                if isinstance(value, str) and value.strip():
                    definition_texts.append(value.strip())
        if not definition_texts:
            continue
        prefix = f"{pos}: " if isinstance(pos, str) and pos.strip() else ""
        meaning_lines.append(prefix + "; ".join(definition_texts))
    if meaning_lines:
        parts.append("meanings: " + " | ".join(meaning_lines))

    if not parts:
        return ""
    return ("dictionaryapi.dev\n" + "\n".join(parts))[:MAX_SOURCE_CHARS]


def _format_jisho_payload(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return ""

    lines = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        japanese = item.get("japanese") if isinstance(item.get("japanese"), list) else []
        jp_text = ""
        if japanese and isinstance(japanese[0], dict):
            jp_word = japanese[0].get("word")
            jp_reading = japanese[0].get("reading")
            if isinstance(jp_word, str) and jp_word.strip():
                jp_text = jp_word.strip()
            elif isinstance(jp_reading, str) and jp_reading.strip():
                jp_text = jp_reading.strip()
        senses = item.get("senses") if isinstance(item.get("senses"), list) else []
        en_defs = []
        if senses and isinstance(senses[0], dict):
            defs = senses[0].get("english_definitions")
            if isinstance(defs, list):
                en_defs = [d.strip() for d in defs if isinstance(d, str) and d.strip()][:3]
        if not jp_text and not en_defs:
            continue
        if en_defs:
            lines.append(f"{jp_text}: {', '.join(en_defs)}" if jp_text else ", ".join(en_defs))
        else:
            lines.append(jp_text)

    if not lines:
        return ""
    return ("jisho.org\n" + "\n".join(lines))[:MAX_SOURCE_CHARS]


def _format_wiktionary_raw(text: str) -> str:
    if not text:
        return ""
    marker_candidates = ("==English==", "==Japanese==", "==Chinese==")
    for marker in marker_candidates:
        idx = text.find(marker)
        if idx >= 0:
            text = text[idx : idx + MAX_SOURCE_CHARS]
            break
    else:
        text = text[:MAX_SOURCE_CHARS]
    cleaned = _clean_wiktionary_markup(text)
    if not cleaned:
        return ""
    return ("wiktionary(raw)\n" + cleaned)[:MAX_SOURCE_CHARS]


def _format_weblio_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    kiji = soup.find(class_="kiji")
    if not kiji:
        return ""
    content = kiji.get_text(strip=True, separator="")
    if not content:
        return ""
    return ("weblio\n" + content[:MAX_SOURCE_CHARS])[:MAX_SOURCE_CHARS]


def _try_fetch_text(url: str, source: str) -> str:
    try:
        return _http_get_text(url, source=source)
    except Exception:
        logger.error("api_helper_request_failed source=%s url=%s", source, url)
        return ""


async def _fetch_dictionaryapi_source(word: str) -> str:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
    text = await asyncio.to_thread(_try_fetch_text, url, "dictionaryapi")
    return _format_dictionaryapi_payload(text)


async def _fetch_jisho_source(word: str) -> str:
    url = f"https://jisho.org/api/v1/search/words?keyword={quote(word)}"
    text = await asyncio.to_thread(_try_fetch_text, url, "jisho")
    return _format_jisho_payload(text)


async def _fetch_wiktionary_source(word: str) -> str:
    url = f"https://en.wiktionary.org/w/index.php?title={quote(word)}&action=raw"
    text = await asyncio.to_thread(_try_fetch_text, url, "wiktionary")
    return _format_wiktionary_raw(text)


async def _fetch_weblio_source(word: str) -> str:
    url = f"https://www.weblio.jp/content/{quote(word)}"
    text = await asyncio.to_thread(_try_fetch_text, url, "weblio")
    return _format_weblio_html(text)


async def _lookupdictionary_async(word: str) -> str:
    logger.info("lookupdictionary_start word=%s", word)
    tasks = [
        asyncio.create_task(_fetch_dictionaryapi_source(word)),
        asyncio.create_task(_fetch_jisho_source(word)),
        asyncio.create_task(_fetch_wiktionary_source(word)),
        asyncio.create_task(_fetch_weblio_source(word)),
    ]
    done, pending = await asyncio.wait(tasks, timeout=LOOKUP_SOURCES_TIMEOUT_SECONDS)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning("lookupdictionary_timeout_cancelled pending=%d word=%s", len(pending), word)

    results = []
    for task in done:
        try:
            results.append(task.result())
        except Exception as exc:
            results.append(exc)
    snippets = []
    for result in results:
        if isinstance(result, Exception):
            continue
        if isinstance(result, str) and result.strip():
            snippets.append(result.strip())

    logger.info("lookupdictionary_finish word=%s snippets=%s", word, str(snippets))
    if not snippets:
        return ""
    return "\n\n".join(snippets)[:MAX_TOTAL_CHARS]


@lru_cache(maxsize=128)
def lookupdictionary(word: str) -> str:
    query = word.strip() if isinstance(word, str) else ""
    if not query:
        return ""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_lookupdictionary_async(query))
    finally:
        loop.close()
