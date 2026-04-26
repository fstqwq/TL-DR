import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from urllib.parse import quote

import cloudscraper
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
HTTP_TIMEOUT_SECONDS = 1.0
LOOKUP_SOURCES_TIMEOUT_SECONDS = 2.0
MAX_SOURCE_CHARS = 1200
MAX_TOTAL_CHARS = 3200
MAX_RAW_SOURCE_CHARS = 4000
WIKTIONARY_LANGUAGE_BY_CODE = {
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
}
WIKTIONARY_PARTS_OF_SPEECH = {
    "adjective",
    "adverb",
    "conjunction",
    "counter",
    "determiner",
    "interjection",
    "noun",
    "numeral",
    "particle",
    "phrase",
    "prefix",
    "preposition",
    "pronoun",
    "proper noun",
    "proverb",
    "suffix",
    "verb",
}
LOCAL_PROVIDER_NAMES = {
    "cc-cedict": "CC-CEDICT",
    "jmdict": "JMdict",
    "cmudict": "CMUdict",
}
LOCAL_PROVIDER_URLS = {
    "cc-cedict": "https://cc-cedict.org/wiki/",
    "jmdict": "https://www.edrdg.org/jmdict/j_jmdict.html",
    "cmudict": "https://github.com/cmusphinx/cmudict",
}


def create_openai_client(api_key: str, base_url: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def create_openai_clients(provider_configs: dict[str, dict[str, str]]) -> dict[str, AsyncOpenAI]:
    return {
        provider_name: create_openai_client(
            provider_config["api_key"],
            provider_config["base_url"],
        )
        for provider_name, provider_config in provider_configs.items()
    }


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
    candidate = str(text).replace("\ufeff", "").strip()
    if "</think>" in candidate:
        candidate = candidate.split("</think>")[-1].strip()
    if candidate.startswith("<think>"):
        return []
    if "```" in candidate:
        fenced = re.findall(r"```(?:\w+)?\s*([\s\S]*?)```", candidate, flags=re.IGNORECASE)
        if fenced:
            candidate = fenced[0].strip()
        else:
            candidate = candidate.replace("```", "").strip()
    lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    suggestions = []
    for line in lines:
        line = re.sub(r"^[\s\-\*\d\.\)\(]+", "", line).strip()
        if not line:
            continue
        if line.startswith("<"):
            continue
        lowered = line.lower()
        if lowered.startswith(("input:", "language:", "output:", "suggestions:", "completion:", "example:")):
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
    content_type = str(response.headers.get("content-type", "")).lower()
    if "application/json" in content_type:
        response.encoding = "utf-8"
    elif not response.encoding:
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text or ""


def _format_wiktionary_preview(text: str, preferred_language: str = "auto") -> str:
    language_blocks = _wiktionary_language_blocks(text)
    if not language_blocks:
        return ""

    language_name, language_lines = _select_wiktionary_language_block(language_blocks, preferred_language)
    sections = _wiktionary_definition_sections(language_lines)
    if not sections:
        return ""

    output: list[str] = []
    for section in sections[:2]:
        definitions = [
            definition
            for definition in (
                _clean_wiktionary_definition(line)
                for line in section["lines"]
                if re.match(r"^#(?![:*#])\s*\S", line.strip())
            )
            if definition
        ]
        if not definitions:
            continue
        output.append(f"{language_name} · {section['title']}")
        output.extend(f"- {definition}" for definition in definitions[:6])

    return "\n".join(output)[:MAX_SOURCE_CHARS]


def _wiktionary_language_blocks(text: str) -> list[tuple[str, list[str]]]:
    lines = [line.rstrip() for line in str(text or "").replace("\r", "").splitlines()]
    blocks: list[tuple[str, list[str]]] = []
    current_name = ""
    current_lines: list[str] = []

    for line in lines:
        heading = re.match(r"^==\s*([^=]+?)\s*==\s*$", line.strip())
        if heading:
            if current_name:
                blocks.append((current_name, current_lines))
            current_name = heading.group(1).strip()
            current_lines = []
            continue
        if current_name:
            current_lines.append(line)

    if current_name:
        blocks.append((current_name, current_lines))
    return blocks


def _select_wiktionary_language_block(
    blocks: list[tuple[str, list[str]]],
    preferred_language: str,
) -> tuple[str, list[str]]:
    preferred_name = WIKTIONARY_LANGUAGE_BY_CODE.get(str(preferred_language or "").lower())
    if preferred_name:
        for name, lines in blocks:
            if name == preferred_name and _wiktionary_definition_sections(lines):
                return name, lines

    for name, lines in blocks:
        if _wiktionary_definition_sections(lines):
            return name, lines
    return blocks[0]


def _wiktionary_definition_sections(lines: list[str]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    active_title = ""
    active_level = 0
    active_lines: list[str] = []

    def flush() -> None:
        if active_title and _wiktionary_section_has_definitions(active_lines):
            sections.append({"title": active_title, "lines": active_lines[:]})

    for line in lines:
        heading = re.match(r"^(={3,6})\s*([^=]+?)\s*\1\s*$", line.strip())
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            normalized_title = title.lower()
            if active_title and level <= active_level:
                flush()
                active_title = ""
                active_level = 0
                active_lines = []
            if normalized_title in WIKTIONARY_PARTS_OF_SPEECH:
                active_title = title
                active_level = level
                active_lines = []
                continue
            if active_title and level <= active_level:
                continue

        if active_title:
            active_lines.append(line)

    flush()
    return sections


def _wiktionary_section_has_definitions(lines: list[str]) -> bool:
    return any(re.match(r"^#(?![:*#])\s*\S", line.strip()) for line in lines)


def _clean_wiktionary_definition(line: str) -> str:
    cleaned = re.sub(r"^#\s*", "", line.strip())
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"\{\{([^{}]{1,240})\}\}", _replace_wiktionary_template, cleaned)
    cleaned = re.sub(r"\{\{[^{}]{1,240}\}\}", "", cleaned)
    cleaned = cleaned.replace("'''", "").replace("''", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([.;:,\)])", r"\1", cleaned)
    cleaned = re.sub(r"(\()\s+", r"\1", cleaned)
    cleaned = cleaned.strip()
    if re.fullmatch(r"[.;:,]*", cleaned):
        return ""
    return cleaned


def _clean_wiktionary_template_value(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", cleaned)
    cleaned = cleaned.replace("'''", "").replace("''", "")
    return cleaned.strip()


def _wiktionary_template_args(template: str) -> tuple[str, list[str], dict[str, str]]:
    parts = [part.strip() for part in template.split("|")]
    if not parts:
        return "", [], {}
    name = parts[0].strip().lower().replace("_", " ")
    positional: list[str] = []
    named: dict[str, str] = {}
    for part in parts[1:]:
        if re.match(r"^[A-Za-z][A-Za-z0-9_-]*\s*=", part):
            key, value = part.split("=", 1)
            named[key.strip().lower()] = _clean_wiktionary_template_value(value)
        else:
            positional.append(_clean_wiktionary_template_value(part))
    return name, positional, named


def _term_after_language(positional: list[str]) -> str:
    if len(positional) >= 2:
        return positional[1]
    if positional:
        return positional[0]
    return ""


def _replace_wiktionary_template(match: re.Match[str]) -> str:
    name, positional, _named = _wiktionary_template_args(match.group(1))
    if not name:
        return ""

    if name in {"head", "en-noun", "ja-noun", "zh-noun", "ja-verb", "ja-adj", "wikipedia"}:
        return ""

    if name in {"l", "link", "m", "mention", "w"}:
        return _term_after_language(positional)

    if name in {"lb", "label", "q", "qualifier", "i", "gloss"}:
        labels = [value for value in positional[1:] if value]
        return f"({'; '.join(labels)})" if labels else ""

    if name == "hanja form of":
        term = positional[0] if positional else ""
        gloss = positional[1] if len(positional) > 1 else ""
        if term and gloss:
            return f"Hanja form of {term}: {gloss}"
        return f"Hanja form of {term}" if term else ""

    definition_templates = {
        "alt form": "Alternative form of",
        "alt form of": "Alternative form of",
        "alternative form of": "Alternative form of",
        "altcase": "Alternative letter-case form of",
        "abbreviation of": "Abbreviation of",
        "acronym of": "Acronym of",
        "initialism of": "Initialism of",
        "clipping of": "Clipping of",
        "contraction of": "Contraction of",
        "plural of": "Plural of",
        "singular of": "Singular of",
        "comparative of": "Comparative of",
        "superlative of": "Superlative of",
        "past of": "Past tense of",
        "present participle of": "Present participle of",
        "gerund of": "Gerund of",
        "misspelling of": "Misspelling of",
    }
    if name in definition_templates:
        term = _term_after_language(positional)
        return f"{definition_templates[name]} {term}" if term else definition_templates[name]

    if name == "inflection of":
        term = _term_after_language(positional)
        tags = [value for value in positional[2:] if value and value != ";"]
        suffix = f" ({', '.join(tags)})" if tags else ""
        return f"Inflection of {term}{suffix}" if term else ""

    return ""


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
    return "\n".join(parts)[:MAX_SOURCE_CHARS]


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
    return "\n".join(lines)[:MAX_SOURCE_CHARS]


def _format_wiktionary_raw(text: str, preferred_language: str = "auto") -> str:
    if not text:
        return ""
    return _format_wiktionary_preview(text, preferred_language=preferred_language)


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
    return content[:MAX_SOURCE_CHARS]


def _try_fetch_text(url: str, source: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> str:
    try:
        return _http_get_text(url, source=source, timeout=timeout)
    except Exception:
        logger.error("api_helper_request_failed source=%s url=%s", source, url)
        return ""


LOOKUP_SOURCE_SPECS = (
    {
        "id": "dictionaryapi",
        "name": "dictionaryapi.dev",
        "fetch_url": lambda word: f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}",
        "page_url": lambda word: f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}",
        "formatter": _format_dictionaryapi_payload,
    },
    {
        "id": "jisho",
        "name": "Jisho",
        "fetch_url": lambda word: f"https://jisho.org/api/v1/search/words?keyword={quote(word)}",
        "page_url": lambda word: f"https://jisho.org/search/{quote(word)}",
        "formatter": _format_jisho_payload,
    },
    {
        "id": "wiktionary",
        "name": "Wiktionary",
        "fetch_url": lambda word: f"https://en.wiktionary.org/w/index.php?title={quote(word)}&action=raw",
        "page_url": lambda word: f"https://en.wiktionary.org/wiki/{quote(word)}",
        "formatter": _format_wiktionary_raw,
    },
    {
        "id": "weblio",
        "name": "Weblio",
        "fetch_url": lambda word: f"https://www.weblio.jp/content/{quote(word)}",
        "page_url": lambda word: f"https://www.weblio.jp/content/{quote(word)}",
        "formatter": _format_weblio_html,
    },
)


async def _fetch_lookup_source_entry(
    spec: dict[str, object],
    word: str,
    preferred_language: str = "auto",
) -> dict[str, object]:
    source_id = str(spec["id"])
    fetch_url = spec["fetch_url"](word)
    raw = await asyncio.to_thread(_try_fetch_text, fetch_url, source_id)
    formatter = spec["formatter"]
    if callable(formatter) and source_id == "wiktionary":
        snippet = formatter(raw, preferred_language=preferred_language)
    else:
        snippet = formatter(raw) if callable(formatter) else ""

    result = {
        "id": source_id,
        "name": str(spec["name"]),
        "pageUrl": spec["page_url"](word),
        "fetchUrl": fetch_url,
        "preview": snippet,
    }
    if source_id == "wiktionary" and raw:
        result["raw"] = raw[:MAX_RAW_SOURCE_CHARS]
    return result


async def _lookupdictionary_async(word: str, preferred_language: str = "auto") -> dict[str, object]:
    logger.info("lookupdictionary_start word=%s preferred_language=%s", word, preferred_language)
    tasks = [
        asyncio.create_task(_fetch_lookup_source_entry(spec, word, preferred_language=preferred_language))
        for spec in LOOKUP_SOURCE_SPECS
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
    sources = []
    snippets = []
    for result in results:
        if isinstance(result, Exception):
            continue
        if isinstance(result, dict):
            preview = result.get("preview")
            has_preview = isinstance(preview, str) and bool(preview.strip())
            if not has_preview:
                continue
            sources.append(result)
            preview = result.get("preview")
            if isinstance(preview, str) and preview.strip():
                snippets.append(preview.strip())

    logger.info("lookupdictionary_finish word=%s snippets=%s", word, str(snippets))
    augmented_content = "\n\n".join(snippets)[:MAX_TOTAL_CHARS] if snippets else ""
    sources.sort(key=lambda item: str(item.get("id", "")))
    return {
        "augmented_content": augmented_content,
        "sources": sources,
    }


def _format_local_dictionary_snippet(entry: dict[str, object]) -> str:
    surface = str(entry.get("surface", "")).strip()
    reading = str(entry.get("reading", "")).strip()
    meaning = str(entry.get("meaning", "")).strip()
    if not surface or not meaning:
        return ""
    header = f"{surface} [{reading}]" if reading else surface
    return f"{header}\n{meaning}".strip()


def _local_lookup_bundle(word: str, local_autocomplete) -> dict[str, object]:
    if local_autocomplete is None:
        return {"augmented_content": "", "sources": []}
    try:
        suggestions = local_autocomplete.search(word, preferred_language="auto", limit=8)
        providers = local_autocomplete.providers() if hasattr(local_autocomplete, "providers") else {}
    except Exception:
        logger.exception("lookupdictionary_local_failed word=%s", word)
        return {"augmented_content": "", "sources": []}

    best_by_lang: dict[str, dict[str, object]] = {}
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        lang = str(suggestion.get("lang", "")).strip()
        if lang not in {"zh", "ja"}:
            continue
        meaning = str(suggestion.get("meaning", "")).strip()
        if not meaning or lang in best_by_lang:
            continue
        best_by_lang[lang] = suggestion

    local_sources: list[dict[str, object]] = []
    local_snippets: list[str] = []
    for lang in ("zh", "ja"):
        entry = best_by_lang.get(lang)
        if entry is None:
            continue
        provider_id = str(providers.get(lang, f"local-{lang}"))
        provider_name = LOCAL_PROVIDER_NAMES.get(provider_id, provider_id)
        provider_url = LOCAL_PROVIDER_URLS.get(provider_id, "")
        snippet = _format_local_dictionary_snippet(entry)
        if not snippet:
            continue
        local_sources.append(
            {
                "id": provider_id,
                "name": provider_name,
                "pageUrl": provider_url,
                "fetchUrl": provider_url,
                "preview": snippet[:MAX_SOURCE_CHARS],
            }
        )
        local_snippets.append(snippet)

    return {
        "augmented_content": "\n\n".join(local_snippets)[:MAX_TOTAL_CHARS] if local_snippets else "",
        "sources": local_sources,
    }


@lru_cache(maxsize=128)
def _lookupdictionary_remote_bundle(word: str, preferred_language: str = "auto") -> dict[str, object]:
    query = word.strip() if isinstance(word, str) else ""
    if not query:
        return {"augmented_content": "", "sources": []}
    normalized_language = preferred_language if preferred_language in {"en", "zh", "ja"} else "auto"
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_lookupdictionary_async(query, preferred_language=normalized_language))
    finally:
        loop.close()


def lookupdictionary_bundle(
    word: str,
    local_autocomplete=None,
    preferred_language: str = "auto",
) -> dict[str, object]:
    query = word.strip() if isinstance(word, str) else ""
    if not query:
        return {"augmented_content": "", "sources": []}

    normalized_language = preferred_language if preferred_language in {"en", "zh", "ja"} else "auto"
    remote_bundle = _lookupdictionary_remote_bundle(query, normalized_language)
    local_bundle = _local_lookup_bundle(query, local_autocomplete)

    local_sources = local_bundle.get("sources", [])
    remote_sources = remote_bundle.get("sources", [])
    local_content = str(local_bundle.get("augmented_content", "")).strip()
    remote_content = str(remote_bundle.get("augmented_content", "")).strip()
    parts = [part for part in (local_content, remote_content) if part]

    return {
        "augmented_content": "\n\n".join(parts)[:MAX_TOTAL_CHARS] if parts else "",
        "sources": [*local_sources, *remote_sources],
    }
