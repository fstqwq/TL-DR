from __future__ import annotations

import bisect
import logging
import lzma
import pickle
import re
import threading
import unicodedata
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
    score = float(row["score"])
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
    postings: list[list[tuple[int, int, int]]]
    surfaces: list[tuple[str, str]]
    sources: list[str]
    meta: dict[str, object]


def load_compact_index(path: Path) -> CompactIndex:
    with lzma.open(path, "rb") as handle:
        payload = pickle.load(handle)
    return CompactIndex(
        aliases=payload["aliases"],
        postings=payload["postings"],
        surfaces=payload["surfaces"],
        sources=payload["sources"],
        meta=payload["meta"],
    )


def _rows_for_alias_range(index: CompactIndex, start: int, end: int, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pos in range(start, end):
        alias_norm = index.aliases[pos]
        for surface_id, source_id, score100 in index.postings[pos]:
            surface, lang = index.surfaces[surface_id]
            rows.append(
                {
                    "alias_norm": alias_norm,
                    "surface": surface,
                    "lang": lang,
                    "source": index.sources[source_id],
                    "score": score100 / 100.0,
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def prefix_rows(index: CompactIndex, query_norm: str, limit: int) -> list[dict[str, object]]:
    upper = query_norm + "\U0010FFFF"
    start = bisect.bisect_left(index.aliases, query_norm)
    end = bisect.bisect_left(index.aliases, upper)
    return _rows_for_alias_range(index, start, end, limit)

def _collect_prefix_matches(
    index: CompactIndex,
    query_text: str,
    preferred_language: str = "auto",
    limit: int = 50,
    typo_penalty: float = 0.0,
) -> dict[tuple[str, str], dict[str, object]]:
    query_norm = normalize_query(query_text)
    script = detect_script(query_text)
    merged: dict[tuple[str, str], dict[str, object]] = {}

    for row in prefix_rows(index, query_norm, 1000):
        if not allow_row_for_script(row, script):
            continue
        key = (str(row["surface"]), str(row["lang"]))
        score = rank_candidate(row, query_norm, typo_penalty=typo_penalty, preferred_language=preferred_language)
        bucket = merged.get(key)
        if bucket is None or score > float(bucket["score"]):
            merged[key] = {
                "surface": row["surface"],
                "lang": row["lang"],
                "source": row["source"],
                "score": score,
            }
        if len(merged) >= limit:
            break

    return merged


def search_single_segment(
    index: CompactIndex,
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
    index: CompactIndex,
    query: str,
    preferred_language: str = "auto",
    limit: int = 3,
) -> list[dict[str, object]]:
    preferred_language = normalize_preferred_language(preferred_language)
    variants = query_variants(query)
    segments = split_query_segments(query)
    if len(variants) > 1 or len(segments) > 1:
        merged: dict[tuple[str, str], dict[str, object]] = {}
        search_inputs = [query]
        search_inputs.extend(variant for variant in variants[1:] if variant != query)
        if len(segments) > 1:
            search_inputs.extend(segment for segment in segments if segment != query)

        for search_input in search_inputs:
            for item in search_single_segment(index, search_input, preferred_language=preferred_language, limit=50):
                key = (str(item["surface"]), str(item["lang"]))
                bucket = merged.get(key)
                if bucket is None:
                    merged[key] = {
                        "surface": item["surface"],
                        "lang": item["lang"],
                        "source": item["source"],
                        "score": float(item["score"]),
                    }
                else:
                    bucket["score"] = max(float(bucket["score"]), float(item["score"]))

        ranked = list(merged.values())
        ranked.sort(key=lambda item: (-float(item["score"]), str(item["surface"])))
        return ranked[:limit]

    return search_single_segment(index, query, preferred_language=preferred_language, limit=limit)


class LocalAutocomplete:
    def __init__(self, index_path: str | Path | None):
        self.index_path = Path(index_path) if index_path else None
        self._lock = threading.Lock()
        self._index: CompactIndex | None = None
        self._load_attempted = False

    def search(self, query: str, preferred_language: str = "auto", limit: int = 3) -> list[str]:
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
        return [str(item["surface"]) for item in results[:limit]]

    def _ensure_index(self) -> CompactIndex | None:
        if self._index is not None:
            return self._index
        if self._load_attempted:
            return None
        with self._lock:
            if self._index is not None:
                return self._index
            if self._load_attempted:
                return None
            self._load_attempted = True
            if self.index_path is None or not self.index_path.exists():
                logger.info("local_autocomplete_index_missing path=%s", self.index_path)
                return None
            try:
                self._index = load_compact_index(self.index_path)
                logger.info(
                    "local_autocomplete_index_loaded path=%s aliases=%s surfaces=%s",
                    self.index_path,
                    len(self._index.aliases),
                    len(self._index.surfaces),
                )
            except Exception:
                logger.exception("local_autocomplete_index_failed path=%s", self.index_path)
                self._index = None
            return self._index
