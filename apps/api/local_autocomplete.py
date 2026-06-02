from __future__ import annotations

import bisect
import json
import logging
import lzma
import pickle
import re
import threading
import unicodedata
from array import array
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


KANA_DIGRAPHS = {
    "きゃ": "kya",
    "きゅ": "kyu",
    "きょ": "kyo",
    "しゃ": "sha",
    "しゅ": "shu",
    "しょ": "sho",
    "ちゃ": "cha",
    "ちゅ": "chu",
    "ちょ": "cho",
    "にゃ": "nya",
    "にゅ": "nyu",
    "にょ": "nyo",
    "ひゃ": "hya",
    "ひゅ": "hyu",
    "ひょ": "hyo",
    "みゃ": "mya",
    "みゅ": "myu",
    "みょ": "myo",
    "りゃ": "rya",
    "りゅ": "ryu",
    "りょ": "ryo",
    "ぎゃ": "gya",
    "ぎゅ": "gyu",
    "ぎょ": "gyo",
    "じゃ": "ja",
    "じゅ": "ju",
    "じょ": "jo",
    "びゃ": "bya",
    "びゅ": "byu",
    "びょ": "byo",
    "ぴゃ": "pya",
    "ぴゅ": "pyu",
    "ぴょ": "pyo",
}

KANA_SINGLE = {
    "あ": "a",
    "い": "i",
    "う": "u",
    "え": "e",
    "お": "o",
    "か": "ka",
    "き": "ki",
    "く": "ku",
    "け": "ke",
    "こ": "ko",
    "さ": "sa",
    "し": "shi",
    "す": "su",
    "せ": "se",
    "そ": "so",
    "た": "ta",
    "ち": "chi",
    "つ": "tsu",
    "て": "te",
    "と": "to",
    "な": "na",
    "に": "ni",
    "ぬ": "nu",
    "ね": "ne",
    "の": "no",
    "は": "ha",
    "ひ": "hi",
    "ふ": "fu",
    "へ": "he",
    "ほ": "ho",
    "ま": "ma",
    "み": "mi",
    "む": "mu",
    "め": "me",
    "も": "mo",
    "や": "ya",
    "ゆ": "yu",
    "よ": "yo",
    "ら": "ra",
    "り": "ri",
    "る": "ru",
    "れ": "re",
    "ろ": "ro",
    "わ": "wa",
    "を": "wo",
    "ん": "n",
    "が": "ga",
    "ぎ": "gi",
    "ぐ": "gu",
    "げ": "ge",
    "ご": "go",
    "ざ": "za",
    "じ": "ji",
    "ず": "zu",
    "ぜ": "ze",
    "ぞ": "zo",
    "だ": "da",
    "ぢ": "ji",
    "づ": "zu",
    "で": "de",
    "ど": "do",
    "ば": "ba",
    "び": "bi",
    "ぶ": "bu",
    "べ": "be",
    "ぼ": "bo",
    "ぱ": "pa",
    "ぴ": "pi",
    "ぷ": "pu",
    "ぺ": "pe",
    "ぽ": "po",
    "ぁ": "a",
    "ぃ": "i",
    "ぅ": "u",
    "ぇ": "e",
    "ぉ": "o",
    "ゎ": "wa",
}


def ascii_fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_query(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = text.replace("’", "'").replace("'", "")
    text = ascii_fold(text)
    kept: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in {" ", "ー", "々", "〆", "〇", "ヶ", "〜"}:
            kept.append(ch)
    return "".join(kept).replace(" ", "")


def normalize_preferred_language(value: str | None) -> str:
    if value in {"zh", "en", "ja"}:
        return value
    return "auto"


def detect_script(text: str) -> str:
    has_han = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    has_hira = any("\u3040" <= ch <= "\u309f" for ch in text)
    has_kata = any("\u30a0" <= ch <= "\u30ff" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text)
    count = sum((has_han, has_hira, has_kata, has_latin))
    if count > 1:
        return "mixed"
    if has_han:
        return "han"
    if has_hira:
        return "hiragana"
    if has_kata:
        return "katakana"
    if has_latin:
        return "latin"
    return "other"


def katakana_to_hiragana(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def kana_to_romaji(text: str) -> str:
    hira = katakana_to_hiragana(text)
    out: list[str] = []
    i = 0
    while i < len(hira):
        pair = hira[i : i + 2]
        if pair in KANA_DIGRAPHS:
            out.append(KANA_DIGRAPHS[pair])
            i += 2
            continue
        ch = hira[i]
        if ch == "っ":
            nxt = KANA_DIGRAPHS.get(hira[i + 1 : i + 3]) or KANA_SINGLE.get(hira[i + 1 : i + 2], "")
            if nxt:
                out.append(nxt[0])
            i += 1
            continue
        if ch == "ー":
            if out:
                for last in reversed(out[-1]):
                    if last in "aeiou":
                        out.append(last)
                        break
            i += 1
            continue
        out.append(KANA_SINGLE.get(ch, ch))
        i += 1
    return "".join(out)


def split_query_segments(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).strip()
    raw_tokens = [token for token in re.split(r"\s+", text) if token]
    segments: list[str] = []
    for token in raw_tokens:
        current = ""
        current_script = None
        for ch in token:
            if ch.isspace():
                continue
            script = detect_script(ch)
            if current and script != current_script:
                segments.append(current)
                current = ch
                current_script = script
            else:
                current += ch
                current_script = script
        if current:
            segments.append(current)
    return segments or ([text] if text else [])


JAPANESE_C_ROMAJI_RULES = [
    ("cu", "ku"),
    ("co", "ko"),
]


def japanese_latin_query_variants(text: str, limit: int = 8) -> list[str]:
    variants: set[str] = {text}
    queue = [text]
    while queue and len(variants) < limit:
        current = queue.pop(0)
        for src, dst in JAPANESE_C_ROMAJI_RULES:
            if src not in current:
                continue
            changed = current.replace(src, dst)
            if changed == current or changed in variants:
                continue
            variants.add(changed)
            queue.append(changed)
            if len(variants) >= limit:
                break
    variants.discard(text)
    return list(variants)


def query_variants(text: str) -> list[str]:
    variants = [text]
    segments = split_query_segments(text)
    if len(segments) > 1:
        joined_romaji_parts: list[str] = []
        changed = False
        for segment in segments:
            script = detect_script(segment)
            if script in {"hiragana", "katakana"}:
                joined_romaji_parts.append(kana_to_romaji(segment))
                changed = True
            else:
                joined_romaji_parts.append(segment)
        if changed:
            joined_romaji = "".join(joined_romaji_parts)
            if joined_romaji and joined_romaji not in variants:
                variants.append(joined_romaji)
    for seed in list(variants):
        for variant in japanese_latin_query_variants(seed):
            if variant not in variants:
                variants.append(variant)
    return variants


LATIN_TYPO_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
TYPO_VARIANT_LIMIT = 512
TYPO_ROW_LIMIT = 64
COVERAGE_BONUS_MAX = 12.0
MAX_TYPO_NEIGHBOR_INPUT_LENGTH = 128


def typo_neighbors(text: str, limit: int = TYPO_VARIANT_LIMIT) -> list[tuple[str, float]]:
    normalized = normalize_query(text)
    if not normalized or detect_script(normalized) != "latin":
        return []
    if len(normalized) > MAX_TYPO_NEIGHBOR_INPUT_LENGTH:
        return []

    variants: list[tuple[str, float]] = []
    seen: set[str] = {normalized}

    def add(value: str, penalty: float) -> None:
        if not value or value in seen or len(variants) >= limit:
            return
        seen.add(value)
        variants.append((value, penalty))

    for i in range(len(normalized) - 1):
        swapped = list(normalized)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        add("".join(swapped), 1.0)

    for i in range(len(normalized)):
        for ch in LATIN_TYPO_ALPHABET:
            if ch == normalized[i]:
                continue
            add(normalized[:i] + ch + normalized[i + 1 :], 2.0)

    for i in range(len(normalized)):
        add(normalized[:i] + normalized[i + 1 :], 2.0)

    for i in range(len(normalized) + 1):
        for ch in LATIN_TYPO_ALPHABET:
            add(normalized[:i] + ch + normalized[i:], 2.0)

    return variants


def split_query_segments_with_spans(text: str) -> list[tuple[str, tuple[int, int]]]:
    text = unicodedata.normalize("NFKC", text).strip()
    raw_tokens = [token for token in re.split(r"\s+", text) if token]
    segments: list[tuple[str, tuple[int, int]]] = []
    cursor = 0
    for token in raw_tokens:
        current = ""
        current_script = None
        for ch in token:
            if ch.isspace():
                continue
            script = detect_script(ch)
            if current and script != current_script:
                normalized = normalize_query(current)
                if normalized:
                    start = cursor
                    cursor += len(normalized)
                    segments.append((current, (start, cursor)))
                current = ch
                current_script = script
            else:
                current += ch
                current_script = script
        if current:
            normalized = normalize_query(current)
            if normalized:
                start = cursor
                cursor += len(normalized)
                segments.append((current, (start, cursor)))
    if not segments and text:
        normalized = normalize_query(text)
        if normalized:
            return [(text, (0, len(normalized)))]
    return segments


def allow_row_for_script(row: dict[str, object], script: str) -> bool:
    source = str(row["source"])
    lang = str(row["lang"])
    if script == "latin":
        return lang == "en" or source.startswith("cc-cedict:pinyin") or source.startswith("jmdict:romaji")
    if script in {"hiragana", "katakana"}:
        return lang == "ja"
    return True


def rank_candidate(
    row: dict[str, object],
    query_norm: str,
    typo_penalty: float = 0.0,
    preferred_language: str = "auto",
) -> float:
    score = -float(row.get("posting_rank", 0))
    alias_norm = str(row["alias_norm"])
    lang = str(row["lang"])
    preferred_language = normalize_preferred_language(preferred_language)

    if alias_norm.startswith(query_norm):
        score += 20.0
        score -= min(10.0, max(0, len(alias_norm) - len(query_norm)) * 0.9)
    score -= typo_penalty

    if preferred_language != "auto" and lang == preferred_language:
        score += 6.0

    return score


@dataclass
class CompactIndex:
    aliases: list[str]
    postings: list[list[tuple[int, str]]]
    entries: list[dict[str, str]]
    meta: dict[str, object]


PACKED_INDEX_FORMAT = "packed-index-v1"
LANG_TO_CODE = {"zh": 1, "ja": 2, "en": 3}
CODE_TO_LANG = ("", "zh", "ja", "en")


class PackedAliases:
    def __init__(self, blob: bytes, offsets: array):
        self.blob = blob
        self.offsets = offsets

    def __len__(self) -> int:
        return max(0, len(self.offsets) - 1)

    def __getitem__(self, index: int | slice) -> str | list[str]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self[pos] for pos in range(start, stop, step)]
        start = int(self.offsets[index])
        end = int(self.offsets[index + 1])
        return self.blob[start:end].decode("utf-8")


@dataclass
class PackedIndex:
    aliases: PackedAliases
    posting_offsets: array
    posting_entry_ids: array
    posting_source_ids: array
    sources: list[str]
    surfaces: list[str]
    readings: list[str]
    meanings: list[str]
    lang_codes: bytes
    meta: dict[str, object]

    @property
    def entry_count(self) -> int:
        return len(self.surfaces)


IndexLike = CompactIndex | PackedIndex


def _array_from(value: object, typecode: str) -> array:
    if isinstance(value, array) and value.typecode == typecode:
        return value
    return array(typecode, value if isinstance(value, list) else [])


def _make_packed_aliases(aliases: list[str]) -> PackedAliases:
    offsets = array("I", [0])
    parts: list[bytes] = []
    total = 0
    for alias in aliases:
        encoded = alias.encode("utf-8")
        parts.append(encoded)
        total += len(encoded)
        offsets.append(total)
    return PackedAliases(b"".join(parts), offsets)


def _pack_entry_fields(entries: list[tuple[str, str, str, str]]) -> tuple[list[str], list[str], list[str], bytes]:
    surfaces: list[str] = []
    readings: list[str] = []
    meanings: list[str] = []
    lang_codes = bytearray()
    for surface, reading, lang, meaning in entries:
        surfaces.append(surface)
        readings.append(reading)
        meanings.append(meaning)
        lang_codes.append(LANG_TO_CODE.get(lang, 0))
    return surfaces, readings, meanings, bytes(lang_codes)


def _build_packed_index(
    entries: list[tuple[str, str, str, str]],
    alias_buckets: dict[str, list[tuple[int, int]]],
    sources: list[str],
    meta: dict[str, object],
) -> PackedIndex:
    aliases = sorted(alias_buckets)
    posting_offsets = array("I", [0])
    posting_entry_ids = array("I")
    posting_source_ids = array("H")

    for alias in aliases:
        for entry_id, source_id in alias_buckets[alias]:
            posting_entry_ids.append(entry_id)
            posting_source_ids.append(source_id)
        posting_offsets.append(len(posting_entry_ids))

    surfaces, readings, meanings, lang_codes = _pack_entry_fields(entries)
    return PackedIndex(
        aliases=_make_packed_aliases(aliases),
        posting_offsets=posting_offsets,
        posting_entry_ids=posting_entry_ids,
        posting_source_ids=posting_source_ids,
        sources=sources,
        surfaces=surfaces,
        readings=readings,
        meanings=meanings,
        lang_codes=lang_codes,
        meta=dict(meta),
    )


def load_compact_index(path: Path) -> IndexLike:
    with lzma.open(path, "rb") as handle:
        prefix = handle.read(64).lstrip()
        handle.seek(0)
        if prefix.startswith((b"{", b"[")):
            payload = json.loads(handle.read().decode("utf-8"))
            return _load_json_compact_index(payload)

        payload = pickle.load(handle)
        if isinstance(payload, dict) and payload.get("format") == PACKED_INDEX_FORMAT:
            return _load_packed_compact_index(payload)
        return _load_legacy_compact_index(payload)


def _load_packed_compact_index(payload: dict[str, object]) -> PackedIndex:
    aliases = payload.get("aliases")
    postings = payload.get("postings")
    entries = payload.get("entries")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    sources = payload.get("sources")
    if not isinstance(aliases, dict) or not isinstance(postings, dict) or not isinstance(entries, dict):
        raise ValueError("invalid packed compact index")
    if not isinstance(sources, list):
        raise ValueError("invalid packed compact index: sources missing")

    alias_blob = aliases.get("blob")
    lang_codes = entries.get("lang_codes")
    if not isinstance(alias_blob, bytes):
        raise ValueError("invalid packed compact index: alias blob missing")
    if not isinstance(lang_codes, (bytes, bytearray)):
        raise ValueError("invalid packed compact index: lang codes missing")

    surfaces = entries.get("surfaces")
    readings = entries.get("readings")
    meanings = entries.get("meanings")
    if not isinstance(surfaces, list) or not isinstance(readings, list) or not isinstance(meanings, list):
        raise ValueError("invalid packed compact index: entries missing")

    return PackedIndex(
        aliases=PackedAliases(alias_blob, _array_from(aliases.get("offsets"), "I")),
        posting_offsets=_array_from(postings.get("offsets"), "I"),
        posting_entry_ids=_array_from(postings.get("entry_ids"), "I"),
        posting_source_ids=_array_from(postings.get("source_ids"), "H"),
        sources=[str(source) for source in sources],
        surfaces=[str(surface) for surface in surfaces],
        readings=[str(reading) for reading in readings],
        meanings=[str(meaning) for meaning in meanings],
        lang_codes=bytes(lang_codes),
        meta=dict(meta),
    )


def _load_json_compact_index(payload: dict[str, object]) -> IndexLike:
    raw_entries = payload.get("entries")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if not isinstance(raw_entries, list):
        raise ValueError("invalid compact index: entries missing")

    entries: list[tuple[str, str, str, str]] = []
    alias_buckets: dict[str, list[tuple[int, int]]] = {}
    sources: list[str] = []
    source_ids: dict[str, int] = {}

    def source_id_for(source: str) -> int:
        existing = source_ids.get(source)
        if existing is not None:
            return existing
        source_id = len(sources)
        source_ids[source] = source_id
        sources.append(source)
        return source_id

    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        surface = str(raw_entry.get("surface", "")).strip()
        reading = str(raw_entry.get("reading", "")).strip()
        lang = str(raw_entry.get("lang", "")).strip()
        meaning = str(raw_entry.get("meaning", "")).strip()
        aliases_by_source = raw_entry.get("aliases")
        if not surface or lang not in {"zh", "ja", "en"}:
            continue

        entries.append((surface, reading, lang, meaning))
        entry_id = len(entries) - 1

        if not isinstance(aliases_by_source, dict):
            continue
        for source, alias_values in aliases_by_source.items():
            if not isinstance(source, str) or not isinstance(alias_values, list):
                continue
            source_id = source_id_for(source)
            seen_for_source: set[str] = set()
            for alias in alias_values:
                alias_norm = normalize_query(str(alias))
                if not alias_norm or alias_norm in seen_for_source:
                    continue
                seen_for_source.add(alias_norm)
                alias_buckets.setdefault(alias_norm, []).append((entry_id, source_id))

    return _build_packed_index(entries, alias_buckets, sources, dict(meta))


def _load_legacy_compact_index(payload: dict[str, object]) -> IndexLike:
    raw_entries = payload.get("entries")
    raw_postings = payload.get("postings")
    raw_sources = payload.get("sources")
    raw_aliases = payload.get("aliases")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if not isinstance(raw_entries, list) or not isinstance(raw_postings, list) or not isinstance(raw_sources, list) or not isinstance(raw_aliases, list):
        raise ValueError("invalid legacy compact index")

    entries = [(str(surface), str(reading), str(lang), "") for surface, reading, lang in raw_entries]
    sources = [str(source) for source in raw_sources]
    posting_offsets = array("I", [0])
    posting_entry_ids = array("I")
    posting_source_ids = array("H")
    for bucket in raw_postings:
        for entry_id, source_id, _score100 in bucket:
            posting_entry_ids.append(int(entry_id))
            posting_source_ids.append(int(source_id))
        posting_offsets.append(len(posting_entry_ids))

    surfaces, readings, meanings, lang_codes = _pack_entry_fields(entries)
    return PackedIndex(
        aliases=_make_packed_aliases([str(alias) for alias in raw_aliases]),
        posting_offsets=posting_offsets,
        posting_entry_ids=posting_entry_ids,
        posting_source_ids=posting_source_ids,
        sources=sources,
        surfaces=surfaces,
        readings=readings,
        meanings=meanings,
        lang_codes=lang_codes,
        meta=dict(meta),
    )


def _rows_for_packed_alias_range(index: PackedIndex, start: int, end: int, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for alias_pos in range(start, end):
        alias_norm = index.aliases[alias_pos]
        posting_start = int(index.posting_offsets[alias_pos])
        posting_end = int(index.posting_offsets[alias_pos + 1])
        for posting_rank, posting_pos in enumerate(range(posting_start, posting_end)):
            entry_id = int(index.posting_entry_ids[posting_pos])
            source_id = int(index.posting_source_ids[posting_pos])
            lang_code = index.lang_codes[entry_id] if entry_id < len(index.lang_codes) else 0
            rows.append(
                {
                    "entry_id": entry_id,
                    "alias_norm": alias_norm,
                    "surface": index.surfaces[entry_id],
                    "reading": index.readings[entry_id],
                    "meaning": index.meanings[entry_id],
                    "lang": CODE_TO_LANG[lang_code] if lang_code < len(CODE_TO_LANG) else "",
                    "source": index.sources[source_id] if source_id < len(index.sources) else "",
                    "posting_rank": posting_rank,
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def _rows_for_alias_range(index: IndexLike, start: int, end: int, limit: int) -> list[dict[str, object]]:
    if isinstance(index, PackedIndex):
        return _rows_for_packed_alias_range(index, start, end, limit)

    rows: list[dict[str, object]] = []
    for pos in range(start, end):
        alias_norm = index.aliases[pos]
        for posting_rank, (entry_id, source) in enumerate(index.postings[pos]):
            entry = index.entries[entry_id]
            rows.append(
                {
                    "entry_id": entry_id,
                    "alias_norm": alias_norm,
                    "surface": entry["surface"],
                    "reading": entry["reading"],
                    "meaning": entry.get("meaning", ""),
                    "lang": entry["lang"],
                    "source": source,
                    "posting_rank": posting_rank,
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def prefix_rows(index: IndexLike, query_norm: str, limit: int) -> list[dict[str, object]]:
    upper = query_norm + "\U0010FFFF"
    start = bisect.bisect_left(index.aliases, query_norm)
    end = bisect.bisect_left(index.aliases, upper)
    return _rows_for_alias_range(index, start, end, limit)

def _collect_prefix_matches(
    index: IndexLike,
    query_text: str,
    preferred_language: str = "auto",
    limit: int = 50,
    typo_penalty: float = 0.0,
) -> dict[int, dict[str, object]]:
    query_norm = normalize_query(query_text)
    script = detect_script(query_text)
    merged: dict[int, dict[str, object]] = {}

    for row in prefix_rows(index, query_norm, 1000):
        if not allow_row_for_script(row, script):
            continue
        key = int(row["entry_id"])
        score = rank_candidate(row, query_norm, typo_penalty=typo_penalty, preferred_language=preferred_language)
        bucket = merged.get(key)
        if bucket is None or score > float(bucket["score"]):
            merged[key] = {
                "entry_id": key,
                "surface": row["surface"],
                "reading": row["reading"],
                "meaning": row.get("meaning", ""),
                "lang": row["lang"],
                "source": row["source"],
                "score": score,
            }
        if len(merged) >= limit:
            break

    return merged


def search_single_segment(
    index: IndexLike,
    query: str,
    preferred_language: str = "auto",
    limit: int = 3,
) -> list[dict[str, object]]:
    preferred_language = normalize_preferred_language(preferred_language)

    merged = _collect_prefix_matches(
        index,
        query,
        preferred_language=preferred_language,
        limit=max(50, limit),
    )

    if not merged:
        for neighbor, typo_penalty in typo_neighbors(query):
            neighbor_matches = _collect_prefix_matches(
                index,
                neighbor,
                preferred_language=preferred_language,
                limit=TYPO_ROW_LIMIT,
                typo_penalty=typo_penalty,
            )
            for key, item in neighbor_matches.items():
                bucket = merged.get(key)
                if bucket is None or float(item["score"]) > float(bucket["score"]):
                    merged[key] = item

    ranked = list(merged.values())
    ranked.sort(key=lambda item: (-float(item["score"]), str(item["surface"])))
    return ranked[:limit]


def search_compact_index(
    index: IndexLike,
    query: str,
    preferred_language: str = "auto",
    limit: int = 3,
) -> list[dict[str, object]]:
    preferred_language = normalize_preferred_language(preferred_language)
    variants = query_variants(query)
    segments = split_query_segments(query)
    if len(variants) > 1 or len(segments) > 1:
        query_norm = normalize_query(query)
        total_query_len = max(1, len(query_norm))
        merged: dict[int, dict[str, object]] = {}
        search_requests: list[tuple[str, set[int]]] = [(query, set(range(total_query_len)))]
        seen_requests: set[tuple[str, tuple[int, ...]]] = set()
        seen_requests.add((query, tuple(range(total_query_len))))

        for variant in variants[1:]:
            if variant == query:
                continue
            request_key = (variant, tuple(range(total_query_len)))
            if request_key in seen_requests:
                continue
            seen_requests.add(request_key)
            search_requests.append((variant, set(range(total_query_len))))

        if len(segments) > 1:
            for segment, (start, end) in split_query_segments_with_spans(query):
                if segment == query:
                    continue
                coverage_points = set(range(start, end))
                request_key = (segment, tuple(sorted(coverage_points)))
                if request_key in seen_requests:
                    continue
                seen_requests.add(request_key)
                search_requests.append((segment, coverage_points))

        for search_input, coverage_points in search_requests:
            coverage_bonus = (len(coverage_points) / total_query_len) * COVERAGE_BONUS_MAX
            for item in search_single_segment(index, search_input, preferred_language=preferred_language, limit=50):
                key = int(item["entry_id"])
                bucket = merged.get(key)
                item_base_score = float(item["score"])
                if bucket is None:
                    merged[key] = {
                        "entry_id": key,
                        "surface": item["surface"],
                        "reading": item["reading"],
                        "meaning": item.get("meaning", ""),
                        "lang": item["lang"],
                        "source": item["source"],
                        "base_score": item_base_score,
                        "coverage_points": set(coverage_points),
                        "coverage_len": len(coverage_points),
                        "score": item_base_score + coverage_bonus,
                    }
                else:
                    combined_points = set(bucket["coverage_points"]) | set(coverage_points)
                    bucket["coverage_points"] = combined_points
                    bucket["coverage_len"] = len(combined_points)
                    bucket["base_score"] = max(float(bucket["base_score"]), item_base_score)
                    bucket["score"] = float(bucket["base_score"]) + (
                        (len(combined_points) / total_query_len) * COVERAGE_BONUS_MAX
                    )

        ranked = list(merged.values())
        ranked.sort(
            key=lambda item: (
                -float(item["score"]),
                -int(item.get("coverage_len", 0)),
                str(item["surface"]),
            )
        )
        return ranked[:limit]

    return search_single_segment(index, query, preferred_language=preferred_language, limit=limit)


class LocalAutocomplete:
    def __init__(self, index_path: str | Path | None):
        self.index_path = Path(index_path) if index_path else None
        self._lock = threading.Lock()
        self._index: IndexLike | None = None
        self._load_attempted = False

    def preload(self) -> bool:
        if self.index_path is None:
            logger.info("local_autocomplete_index_disabled")
            return False
        return self._ensure_index(raise_on_failure=True) is not None

    def search(self, query: str, preferred_language: str = "auto", limit: int = 3) -> list[dict[str, str]]:
        normalized_query = query.strip() if isinstance(query, str) else ""
        if not normalized_query:
            return []
        index = self._ensure_index()
        if index is None:
            return []
        results = search_compact_index(
            index,
            normalized_query,
            preferred_language=preferred_language,
            limit=max(1, min(limit, 10)),
        )
        return [
            {
                "surface": str(item["surface"]),
                "reading": str(item.get("reading", "")),
                "meaning": str(item.get("meaning", "")),
                "lang": str(item["lang"]),
            }
            for item in results[:limit]
        ]

    def providers(self) -> dict[str, str]:
        index = self._ensure_index()
        if index is None:
            return {}
        providers = index.meta.get("providers")
        if not isinstance(providers, dict):
            return {}
        return {
            str(lang): str(provider)
            for lang, provider in providers.items()
            if isinstance(lang, str) and isinstance(provider, str)
        }

    def _ensure_index(self, *, raise_on_failure: bool = False) -> IndexLike | None:
        if self._index is not None:
            return self._index
        if self._load_attempted:
            if raise_on_failure:
                raise RuntimeError(f"Local autocomplete index is unavailable: {self.index_path}")
            return None
        with self._lock:
            if self._index is not None:
                return self._index
            if self._load_attempted:
                if raise_on_failure:
                    raise RuntimeError(f"Local autocomplete index is unavailable: {self.index_path}")
                return None
            self._load_attempted = True
            if self.index_path is None or not self.index_path.exists():
                logger.info("local_autocomplete_index_missing path=%s", self.index_path)
                if raise_on_failure:
                    raise FileNotFoundError(f"Local autocomplete index is missing: {self.index_path}")
                return None
            try:
                self._index = load_compact_index(self.index_path)
                logger.info(
                    "local_autocomplete_index_loaded path=%s aliases=%s entries=%s",
                    self.index_path,
                    len(self._index.aliases),
                    self._index.entry_count if isinstance(self._index, PackedIndex) else len(self._index.entries),
                )
            except Exception as exc:
                logger.exception("local_autocomplete_index_failed path=%s", self.index_path)
                self._index = None
                if raise_on_failure:
                    raise RuntimeError(f"Failed to load local autocomplete index: {self.index_path}") from exc
            return self._index
