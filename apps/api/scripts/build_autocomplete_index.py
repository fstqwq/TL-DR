from __future__ import annotations

import gzip
import json
import lzma
import pickle
import re
import sys
import tempfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from array import array
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
API_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


CEDICT_RE = re.compile(r"^(?P<trad>\S+)\s+(?P<simp>\S+)\s+\[(?P<pinyin>.+?)\]\s+/(?P<defs>.+)/$")
CMUDICT_ALT_RE = re.compile(r"\(\d+\)$")
DATA_DIR = API_DIR / "data"
CEDICT_PATH = DATA_DIR / "cc-cedict.txt.gz"
JMDICT_PATH = DATA_DIR / "JMdict_e.gz"
CMUDICT_PATH = DATA_DIR / "cmudict.dict"
OUTPUT_PATH = DATA_DIR / "lexicon.json.xz"
PACKED_INDEX_FORMAT = "packed-index-v1"
LANG_TO_CODE = {"zh": 1, "ja": 2, "en": 3}

DATASET_DOWNLOADS = {
    "cedict": {
        "path": CEDICT_PATH,
        "url": "https://cc-cedict.org/editor/editor_export_cedict.php?c=gz",
        "encoding": None,
    },
    "jmdict": {
        "path": JMDICT_PATH,
        "url": "ftp://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
        "encoding": None,
    },
    "cmudict": {
        "path": CMUDICT_PATH,
        "url": "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict",
        "encoding": None,
    },
}


def build_proxy_opener() -> urllib.request.OpenerDirector:
    proxies = dict(urllib.request.getproxies())
    http_proxy = proxies.get("http")
    if http_proxy:
        proxies.setdefault("https", http_proxy)
        proxies.setdefault("ftp", http_proxy)
    if proxies:
        print(f"[proxy] {json.dumps(proxies, ensure_ascii=False)}")
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def build_compact_index_from_entries(
    entries: Iterable[tuple[dict[str, object], float]],
    output_path: Path,
    *,
    meta_extra: dict[str, object] | None = None,
) -> dict[str, object]:
    prepared: list[tuple[float, str, str, str, str, dict[str, list[str]]]] = []
    alias_count = 0
    source_names: set[str] = set()

    for entry, score in entries:
        surface = str(entry.get("surface", "")).strip()
        reading = str(entry.get("reading", "")).strip()
        lang = str(entry.get("lang", "")).strip()
        meaning = str(entry.get("meaning", "")).strip()
        raw_aliases = entry.get("aliases")
        if not surface or lang not in {"zh", "ja", "en"} or not isinstance(raw_aliases, dict):
            continue

        alias_map: dict[str, list[str]] = {}
        for source, alias_values in raw_aliases.items():
            if not isinstance(source, str) or not source:
                continue
            if not isinstance(alias_values, list):
                continue
            normalized = dedupe_preserve_order(
                normalize_query(str(alias))
                for alias in alias_values
                if isinstance(alias, str) and alias.strip()
            )
            if not normalized:
                continue
            alias_map[source] = normalized
            source_names.add(source)
            alias_count += len(normalized)

        if not alias_map:
            continue

        prepared.append((float(score), lang, surface, reading, meaning, alias_map))

    prepared.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    entries_payload = [
        {
            "surface": surface,
            "reading": reading,
            "lang": lang,
            "meaning": meaning,
            "aliases": alias_map,
        }
        for _, lang, surface, reading, meaning, alias_map in prepared
    ]

    meta: dict[str, object] = {
        "version": 4,
        "source": "direct_entries",
        "format": PACKED_INDEX_FORMAT,
        "entry_count": len(entries_payload),
        "alias_count": alias_count,
        "source_count": len(source_names),
        "providers": {
            "zh": "cc-cedict",
            "ja": "jmdict",
            "en": "cmudict",
        },
    }
    if meta_extra:
        meta.update(meta_extra)

    source_ids: dict[str, int] = {}
    sources: list[str] = []
    alias_buckets: dict[str, list[tuple[int, int]]] = {}
    surfaces: list[str] = []
    readings: list[str] = []
    meanings: list[str] = []
    lang_codes = bytearray()

    def source_id_for(source: str) -> int:
        existing = source_ids.get(source)
        if existing is not None:
            return existing
        source_id = len(sources)
        source_ids[source] = source_id
        sources.append(source)
        return source_id

    for entry_id, entry in enumerate(entries_payload):
        surfaces.append(str(entry["surface"]))
        readings.append(str(entry["reading"]))
        meanings.append(str(entry["meaning"]))
        lang_codes.append(LANG_TO_CODE.get(str(entry["lang"]), 0))
        for source, alias_values in entry["aliases"].items():
            source_id = source_id_for(str(source))
            for alias in alias_values:
                alias_buckets.setdefault(str(alias), []).append((entry_id, source_id))

    aliases = sorted(alias_buckets)
    alias_offsets = array("I", [0])
    alias_parts: list[bytes] = []
    alias_total = 0
    posting_offsets = array("I", [0])
    posting_entry_ids = array("I")
    posting_source_ids = array("H")

    for alias in aliases:
        encoded = alias.encode("utf-8")
        alias_parts.append(encoded)
        alias_total += len(encoded)
        alias_offsets.append(alias_total)
        for entry_id, source_id in alias_buckets[alias]:
            posting_entry_ids.append(entry_id)
            posting_source_ids.append(source_id)
        posting_offsets.append(len(posting_entry_ids))

    payload = {
        "format": PACKED_INDEX_FORMAT,
        "meta": meta,
        "aliases": {
            "blob": b"".join(alias_parts),
            "offsets": alias_offsets,
        },
        "postings": {
            "offsets": posting_offsets,
            "entry_ids": posting_entry_ids,
            "source_ids": posting_source_ids,
        },
        "entries": {
            "surfaces": surfaces,
            "readings": readings,
            "meanings": meanings,
            "lang_codes": bytes(lang_codes),
        },
        "sources": sources,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(output_path, "wb", preset=9) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return meta


def download_file(url: str, destination: Path, *, encoding: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {destination.name} <- {url}")
    with tempfile.NamedTemporaryFile(delete=False, dir=str(destination.parent), suffix=".part") as tmp:
        tmp_path = Path(tmp.name)

    request = urllib.request.Request(url, headers={"User-Agent": "TL-DR-build/1.0"})
    try:
        opener = build_proxy_opener()
        with opener.open(request, timeout=120) as response:
            payload = response.read()
        with tmp_path.open("wb") as handle:
            handle.write(payload)
        tmp_path.replace(destination)
        print(f"[download] ok {destination}")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def verify_cedict(path: Path) -> None:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            if "[" in line and "/" in line:
                return
    raise RuntimeError(f"{path.name} does not look like a valid CC-CEDICT export")


def verify_jmdict(path: Path) -> None:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        head = handle.read(16384)
    if "<!DOCTYPE JMdict" not in head and "<JMdict" not in head:
        raise RuntimeError(f"{path.name} does not look like a valid JMdict file")


def verify_cmudict(path: Path) -> None:
    with path.open("rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith(";;;"):
                continue
            if re.match(r"^\S+\s+[A-Z]", stripped):
                return
    raise RuntimeError(f"{path.name} does not look like a valid CMUdict file")


def verify_dataset(kind: str, path: Path) -> None:
    if kind == "cedict":
        verify_cedict(path)
    elif kind == "jmdict":
        verify_jmdict(path)
    elif kind == "cmudict":
        verify_cmudict(path)
    else:
        raise ValueError(f"Unknown dataset kind: {kind}")


def ensure_required_sources() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for kind, info in DATASET_DOWNLOADS.items():
        path = info["path"]
        if not path.exists():
            download_file(str(info["url"]), path, encoding=info["encoding"])
        else:
            print(f"[source] present {path}")
        print(f"[verify] {kind} -> {path}")
        verify_dataset(kind, path)
        print(f"[verify] ok {kind}")


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


def generate_fuzzy_variants(text: str, rules: list[tuple[str, str]], limit: int = 12) -> set[str]:
    variants = {text}
    queue = [text]
    while queue and len(variants) < limit:
        current = queue.pop(0)
        for src, dst in rules:
            if src not in current:
                continue
            changed = current.replace(src, dst)
            if changed not in variants:
                variants.add(changed)
                queue.append(changed)
                if len(variants) >= limit:
                    break
        if len(variants) >= limit:
            break
    return variants


def try_import_wordfreq():
    from wordfreq import zipf_frequency  # type: ignore
    return zipf_frequency


@lru_cache(maxsize=1_000_000)
def wordfreq_score(word: str, lang: str) -> float:
    zipf_frequency = try_import_wordfreq()
    try:
        score = float(zipf_frequency(word, lang))
    except Exception:
        return 0.0
    return max(score, 0.0)


ARPABET_TO_IPA = {
    "AA": "ɑ",
    "AE": "æ",
    "AH": "ʌ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "EH": "ɛ",
    "ER": "ɝ",
    "EY": "eɪ",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "IH": "ɪ",
    "IY": "i",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "P": "p",
    "R": "r",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "UH": "ʊ",
    "UW": "u",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}
ARPABET_VOWELS = {
    "AA",
    "AE",
    "AH",
    "AO",
    "AW",
    "AY",
    "EH",
    "ER",
    "EY",
    "IH",
    "IY",
    "OW",
    "OY",
    "UH",
    "UW",
}


def arpabet_to_ipa(pronunciation: str) -> str:
    pieces: list[str] = []
    for token in pronunciation.strip().split():
        match = re.fullmatch(r"([A-Z]+)([012])?", token)
        if not match:
            continue
        phone, stress = match.groups()
        ipa = ARPABET_TO_IPA.get(phone)
        if ipa is None:
            continue
        if phone in ARPABET_VOWELS:
            if stress == "1":
                ipa = "ˈ" + ipa
            elif stress == "2":
                ipa = "ˌ" + ipa
        pieces.append(ipa)
    if not pieces:
        return ""
    return f"/{''.join(pieces)}/"


def normalize_cmudict_word(raw: str) -> str:
    base = CMUDICT_ALT_RE.sub("", raw.strip())
    return base.lower()


PINYIN_TONE_MARKS = {
    "a": ("a", "ā", "á", "ǎ", "à"),
    "e": ("e", "ē", "é", "ě", "è"),
    "i": ("i", "ī", "í", "ǐ", "ì"),
    "o": ("o", "ō", "ó", "ǒ", "ò"),
    "u": ("u", "ū", "ú", "ǔ", "ù"),
    "ü": ("ü", "ǖ", "ǘ", "ǚ", "ǜ"),
}


def apply_pinyin_tone(base: str, tone: str) -> str:
    if not base or tone not in {"1", "2", "3", "4"}:
        return base

    target_index = -1
    if "a" in base:
        target_index = base.index("a")
    elif "e" in base:
        target_index = base.index("e")
    elif "ou" in base:
        target_index = base.index("o")
    else:
        for index in range(len(base) - 1, -1, -1):
            if base[index] in PINYIN_TONE_MARKS:
                target_index = index
                break

    if target_index < 0:
        return base

    vowel = base[target_index]
    marked = PINYIN_TONE_MARKS[vowel][int(tone)]
    return f"{base[:target_index]}{marked}{base[target_index + 1 :]}"


def normalize_pinyin(raw: str) -> tuple[str, str, str]:
    text = unicodedata.normalize("NFKC", raw).lower()
    text = text.replace("u:", "ü").replace("v", "ü")
    tokens = re.findall(r"[a-zü]+[0-5]?", text)

    display_tokens: list[str] = []
    alias_tokens: list[str] = []
    for token in tokens:
        match = re.fullmatch(r"([a-zü]+)([0-5]?)", token)
        if not match:
            continue
        base, tone = match.groups()
        if not base:
            continue
        display_tokens.append(apply_pinyin_tone(base, tone))
        alias_tokens.append(base)

    display = " ".join(display_tokens).strip()
    alias_text = " ".join(alias_tokens).strip()
    u_form = alias_text.replace("ü", "u")
    v_form = alias_text.replace("ü", "v")
    return display, u_form, v_form


def pinyin_syllables(text: str) -> list[str]:
    return [part for part in text.split() if part]


PINYIN_FUZZY_RULES = [
    ("zh", "z"),
    ("ch", "c"),
    ("sh", "s"),
    ("eng", "en"),
    ("ing", "in"),
    ("ang", "an"),
    ("ong", "on"),
    ("ian", "iang"),
    ("uan", "uang"),
    ("n", "l"),
    ("l", "n"),
]


def pinyin_variants(text: str) -> set[str]:
    compact = normalize_query(text)
    variants = {compact}
    variants.update(generate_fuzzy_variants(compact, PINYIN_FUZZY_RULES))
    return {item for item in variants if item}


def chinese_mixed_aliases(surface: str, spaced_pinyin: str) -> set[str]:
    syllables = pinyin_syllables(spaced_pinyin)
    if len(surface) != len(syllables):
        return set()
    if len(surface) < 2 or len(surface) > 4:
        return set()
    if any(not ("\u4e00" <= ch <= "\u9fff") for ch in surface):
        return set()

    aliases: set[str] = set()
    total = 1 << len(surface)
    for mask in range(1, total - 1):
        parts: list[str] = []
        has_han = False
        has_latin = False
        for i, ch in enumerate(surface):
            if mask & (1 << i):
                parts.append(ch)
                has_han = True
            else:
                parts.append(syllables[i])
                has_latin = True
        if has_han and has_latin:
            aliases.add(normalize_query("".join(parts)))
    return {alias for alias in aliases if alias}


def katakana_to_hiragana(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


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
    "ゔぁ": "va",
    "ゔぃ": "vi",
    "ゔぇ": "ve",
    "ゔぉ": "vo",
    "ゔゅ": "vyu",
    "てぃ": "ti",
    "でぃ": "di",
    "とぅ": "tu",
    "どぅ": "du",
    "ふぁ": "fa",
    "ふぃ": "fi",
    "ふぇ": "fe",
    "ふぉ": "fo",
    "しぇ": "she",
    "じぇ": "je",
    "ちぇ": "che",
    "つぁ": "tsa",
    "つぃ": "tsi",
    "つぇ": "tse",
    "つぉ": "tso",
    "うぃ": "wi",
    "うぇ": "we",
    "うぉ": "wo",
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
    "ゐ": "wi",
    "ゑ": "we",
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
            next_pair = hira[i + 1 : i + 3]
            nxt = KANA_DIGRAPHS.get(next_pair) or KANA_SINGLE.get(hira[i + 1 : i + 2], "")
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


def romaji_variants(text: str) -> set[str]:
    base = kana_to_romaji(text)
    variants = {base}
    simplified = base.replace("aa", "a").replace("ii", "i").replace("uu", "u")
    simplified = simplified.replace("ee", "e").replace("ou", "o").replace("oo", "o")
    variants.add(simplified)
    fuzzy_rules = [
        ("shi", "si"),
        ("chi", "ti"),
        ("tsu", "tu"),
        ("ji", "zi"),
        ("fu", "hu"),
        ("ku", "cu"),
        ("ko", "co"),
        ("sha", "sya"),
        ("shu", "syu"),
        ("sho", "syo"),
        ("cha", "tya"),
        ("chu", "tyu"),
        ("cho", "tyo"),
    ]
    for seed in list(variants):
        variants.update(generate_fuzzy_variants(seed, fuzzy_rules))
    return {item for item in variants if item}


def format_cedict_meaning(definitions: str) -> str:
    parts = dedupe_preserve_order(
        segment.strip()
        for segment in definitions.split("/")
        if isinstance(segment, str) and segment.strip()
    )
    return "\n".join(f"- {part}" for part in parts)


def format_jmdict_meaning(entry: ET.Element) -> str:
    lines: list[str] = []
    for sense in entry.findall("./sense"):
        glosses = dedupe_preserve_order(
            gloss.text.strip()
            for gloss in sense.findall("./gloss")
            if gloss.text and gloss.text.strip()
        )
        if not glosses:
            continue
        labels = dedupe_preserve_order(
            node.text.strip()
            for tag in ("pos", "field", "misc", "s_inf")
            for node in sense.findall(f"./{tag}")
            if node.text and node.text.strip()
        )
        body = "; ".join(glosses)
        if labels:
            lines.append(f"- ({'; '.join(labels)}) {body}")
        else:
            lines.append(f"- {body}")
    return "\n".join(lines)


def iter_cedict_entries(path: Path) -> Iterable[tuple[dict[str, object], float]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = CEDICT_RE.match(line)
            if not match:
                continue
            trad = match.group("trad")
            simp = match.group("simp")
            reading, pinyin_u, pinyin_v = normalize_pinyin(match.group("pinyin"))
            meaning = format_cedict_meaning(match.group("defs"))
            entry_score = max(wordfreq_score(simp, "zh"), wordfreq_score(trad, "zh"))

            alias_map: dict[str, list[str]] = {
                "cc-cedict:surface": dedupe_preserve_order([trad, simp]),
            }
            if pinyin_u:
                alias_map["cc-cedict:pinyin"] = [pinyin_u]
                fuzzy = sorted(pinyin_variants(pinyin_u) - {normalize_query(pinyin_u)})
                if fuzzy:
                    alias_map["cc-cedict:pinyin-fuzzy"] = fuzzy
                mixed = sorted(chinese_mixed_aliases(simp, pinyin_u))
                if mixed:
                    alias_map["cc-cedict:mixed"] = mixed
            if pinyin_v and pinyin_v != pinyin_u:
                alias_map["cc-cedict:pinyin-v"] = [pinyin_v]
                fuzzy_v = sorted(pinyin_variants(pinyin_v) - {normalize_query(pinyin_v)})
                if fuzzy_v:
                    alias_map["cc-cedict:pinyin-v-fuzzy"] = fuzzy_v

            yield (
                {
                    "surface": simp,
                    "reading": reading,
                    "lang": "zh",
                    "meaning": meaning,
                    "aliases": alias_map,
                },
                entry_score,
            )


def iter_jmdict_entries(path: Path) -> Iterable[tuple[dict[str, object], float]]:
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",))
        for _, elem in context:
            if elem.tag != "entry":
                continue
            kebs = dedupe_preserve_order(node.text.strip() for node in elem.findall("./k_ele/keb") if node.text)
            rebs = dedupe_preserve_order(node.text.strip() for node in elem.findall("./r_ele/reb") if node.text)
            display = kebs[0] if kebs else (rebs[0] if rebs else "")
            reading = rebs[0] if rebs else ""
            meaning = format_jmdict_meaning(elem)
            if not display:
                elem.clear()
                continue

            entry_score = max((wordfreq_score(keb, "ja") for keb in kebs), default=0.0)
            if not kebs:
                entry_score = max((wordfreq_score(reb, "ja") for reb in rebs), default=0.0)

            alias_map: dict[str, list[str]] = {}
            if kebs:
                alias_map["jmdict:surface"] = kebs
            if rebs:
                alias_map["jmdict:reading"] = rebs
                romaji_aliases: list[str] = []
                romaji_fuzzy_aliases: list[str] = []
                for reb in rebs:
                    base_romaji = kana_to_romaji(reb)
                    for romaji in sorted(romaji_variants(reb)):
                        normalized = normalize_query(romaji)
                        if not normalized:
                            continue
                        if romaji == base_romaji:
                            romaji_aliases.append(normalized)
                        else:
                            romaji_fuzzy_aliases.append(normalized)
                if romaji_aliases:
                    alias_map["jmdict:romaji"] = dedupe_preserve_order(romaji_aliases)
                if romaji_fuzzy_aliases:
                    alias_map["jmdict:romaji-fuzzy"] = dedupe_preserve_order(romaji_fuzzy_aliases)

            yield (
                {
                    "surface": display,
                    "reading": reading,
                    "lang": "ja",
                    "meaning": meaning,
                    "aliases": alias_map,
                },
                entry_score,
            )
            elem.clear()


def iter_cmudict_entries(path: Path) -> Iterable[tuple[dict[str, object], float]]:
    current_word = ""
    current_readings: list[str] = []

    def flush() -> Iterable[tuple[dict[str, object], float]]:
        if not current_word or not current_readings:
            return []
        reading = " ".join(current_readings)
        return [
            (
                {
                    "surface": current_word,
                    "reading": reading,
                    "lang": "en",
                    "meaning": "",
                    "aliases": {
                        "cmudict:word": [current_word],
                    },
                },
                wordfreq_score(current_word, "en"),
            )
        ]

    with path.open("rt", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";;;"):
                continue
            match = re.match(r"^(?P<word>\S+)\s+(?P<pron>.+)$", line)
            if not match:
                continue
            raw_word = match.group("word")
            pronunciation = match.group("pron")
            word = normalize_cmudict_word(raw_word)
            ipa = arpabet_to_ipa(pronunciation)
            if not word or not ipa:
                continue
            if current_word and word != current_word:
                yield from flush()
                current_word = word
                current_readings = [ipa]
                continue
            if not current_word:
                current_word = word
            if ipa not in current_readings:
                current_readings.append(ipa)
        yield from flush()


def iter_cedict_rows(path: Path) -> Iterable[tuple[str, str, str, str, str, float]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = CEDICT_RE.match(line)
            if not match:
                continue
            trad = match.group("trad")
            simp = match.group("simp")
            reading, pinyin_u, pinyin_v = normalize_pinyin(match.group("pinyin"))
            entry_score = max(wordfreq_score(simp, "zh"), wordfreq_score(trad, "zh"))
            display = simp

            for surface in {simp, trad}:
                yield (
                    normalize_query(surface),
                    display,
                    reading,
                    "zh",
                    "cc-cedict:surface",
                    entry_score,
                )

            if pinyin_u:
                normalized = normalize_query(pinyin_u)
                yield (normalized, display, reading, "zh", "cc-cedict:pinyin", entry_score)
                for variant in pinyin_variants(pinyin_u):
                    if variant != normalized:
                        yield (variant, display, reading, "zh", "cc-cedict:pinyin-fuzzy", entry_score)
                for alias in chinese_mixed_aliases(display, pinyin_u):
                    yield (alias, display, reading, "zh", "cc-cedict:mixed", entry_score)
            if pinyin_v and pinyin_v != pinyin_u:
                normalized = normalize_query(pinyin_v)
                yield (normalized, display, reading, "zh", "cc-cedict:pinyin-v", entry_score)
                for variant in pinyin_variants(pinyin_v):
                    if variant != normalized:
                        yield (variant, display, reading, "zh", "cc-cedict:pinyin-v-fuzzy", entry_score)


def iter_jmdict_rows(path: Path) -> Iterable[tuple[str, str, str, str, str, float]]:
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",))
        for _, elem in context:
            if elem.tag != "entry":
                continue
            kebs = [node.text.strip() for node in elem.findall("./k_ele/keb") if node.text]
            rebs = [node.text.strip() for node in elem.findall("./r_ele/reb") if node.text]
            display = kebs[0] if kebs else (rebs[0] if rebs else "")
            reading = rebs[0] if rebs else ""
            if not display:
                elem.clear()
                continue
            if kebs:
                entry_score = max(wordfreq_score(keb, "ja") for keb in kebs)
            else:
                entry_score = max((wordfreq_score(reb, "ja") for reb in rebs), default=0.0)

            for keb in kebs:
                yield (
                    normalize_query(keb),
                    display,
                    reading,
                    "ja",
                    "jmdict:surface",
                    entry_score,
                )

            for reb in rebs:
                yield (
                    normalize_query(reb),
                    display,
                    reading,
                    "ja",
                    "jmdict:reading",
                    entry_score,
                )
                base_romaji = kana_to_romaji(reb)
                for romaji in romaji_variants(reb):
                    yield (
                        normalize_query(romaji),
                        display,
                        reading,
                        "ja",
                        "jmdict:romaji" if romaji == base_romaji else "jmdict:romaji-fuzzy",
                        entry_score,
                    )
            elem.clear()


def iter_cmudict_rows(path: Path) -> Iterable[tuple[str, str, str, str, str, float]]:
    current_word = ""
    current_readings: list[str] = []

    def flush() -> Iterable[tuple[str, str, str, str, str, float]]:
        if not current_word or not current_readings:
            return []
        reading = " ".join(current_readings)
        return [(
            normalize_query(current_word),
            current_word,
            reading,
            "en",
            "cmudict:word",
            wordfreq_score(current_word, "en"),
        )]

    with path.open("rt", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";;;"):
                continue
            match = re.match(r"^(?P<word>\S+)\s+(?P<pron>.+)$", line)
            if not match:
                continue
            raw_word = match.group("word")
            pronunciation = match.group("pron")
            word = normalize_cmudict_word(raw_word)
            ipa = arpabet_to_ipa(pronunciation)
            if not word or not ipa:
                continue
            if current_word and word != current_word:
                yield from flush()
                current_word = word
                current_readings = [ipa]
                continue
            if not current_word:
                current_word = word
            if ipa not in current_readings:
                current_readings.append(ipa)
        yield from flush()


def iter_all_rows(
    cedict_path: Path,
    jmdict_path: Path,
    cmudict_path: Path,
) -> tuple[Iterable[tuple[str, str, str, str, str, float]], Counter[str], dict[str, object]]:
    counts = Counter()
    meta = {
        "cedict_path": str(cedict_path),
        "jmdict_path": str(jmdict_path),
        "cmudict_path": str(cmudict_path),
    }

    def wrapped_rows() -> Iterable[tuple[str, str, str, str, str, float]]:
        source_iters = (
            ("cedict", iter_cedict_rows(cedict_path)),
            ("jmdict", iter_jmdict_rows(jmdict_path)),
            ("cmudict", iter_cmudict_rows(cmudict_path)),
        )
        for source_name, rows in source_iters:
            for alias_norm, surface, reading, lang, source, score in rows:
                if not alias_norm or not surface:
                    continue
                counts[f"{source_name}_rows"] += 1
                counts[f"{lang}_rows"] += 1
                yield alias_norm, surface, reading, lang, source, score

    return wrapped_rows(), counts, meta


def iter_all_entries(
    cedict_path: Path,
    jmdict_path: Path,
    cmudict_path: Path,
) -> tuple[Iterable[tuple[dict[str, object], float]], Counter[str], dict[str, object]]:
    counts = Counter()
    meta = {
        "cedict_path": str(cedict_path),
        "jmdict_path": str(jmdict_path),
        "cmudict_path": str(cmudict_path),
    }

    def wrapped_entries() -> Iterable[tuple[dict[str, object], float]]:
        source_iters = (
            ("cedict", iter_cedict_entries(cedict_path)),
            ("jmdict", iter_jmdict_entries(jmdict_path)),
            ("cmudict", iter_cmudict_entries(cmudict_path)),
        )
        for source_name, entries in source_iters:
            for entry, score in entries:
                lang = str(entry.get("lang", ""))
                if not entry.get("surface"):
                    continue
                counts[f"{source_name}_entries"] += 1
                counts[f"{lang}_entries"] += 1
                yield entry, score

    return wrapped_entries(), counts, meta


def build_artifact(
    output_path: Path = OUTPUT_PATH,
    cedict_path: Path = CEDICT_PATH,
    jmdict_path: Path = JMDICT_PATH,
    cmudict_path: Path = CMUDICT_PATH,
) -> dict[str, object]:
    print(f"[build] output -> {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        print(f"[build] remove existing artifact {output_path}")
        output_path.unlink()

    entries, counts, meta = iter_all_entries(
        cedict_path=cedict_path,
        jmdict_path=jmdict_path,
        cmudict_path=cmudict_path,
    )
    print("[build] compiling compact index")
    compact_meta = build_compact_index_from_entries(entries, output_path, meta_extra={"builder": meta})
    print(f"[build] ok {output_path}")
    return {"counts": dict(counts), "meta": compact_meta}


def main() -> None:
    ensure_required_sources()
    result = build_artifact()
    print(json.dumps({"output": str(OUTPUT_PATH), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
