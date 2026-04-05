from __future__ import annotations

import gzip
import json
import lzma
import pickle
import re
import shutil
import sys
import tarfile
import tempfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
API_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


CEDICT_RE = re.compile(r"^(?P<trad>\S+)\s+(?P<simp>\S+)\s+\[(?P<pinyin>.+?)\]\s+/(?P<defs>.+)/$")
SCOWL_FILES = (
    "scowl-2020.12.07/final/english-words.95",
    "scowl-2020.12.07/final/american-words.95",
)
DATA_DIR = API_DIR / "data"
CEDICT_PATH = DATA_DIR / "cc-cedict.txt.gz"
JMDICT_PATH = DATA_DIR / "JMdict_e.gz"
SCOWL_PATH = DATA_DIR / "scowl-2020.12.07.tar.gz"
OUTPUT_PATH = DATA_DIR / "autocomplete.compact.xz"
WORDFREQ_TOP_N = 200000

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
    "scowl": {
        "path": SCOWL_PATH,
        "url": "https://downloads.sourceforge.net/wordlist/scowl-2020.12.07.tar.gz",
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


def build_compact_index_from_rows(
    rows: Iterable[tuple[str, str, str, str, float]],
    output_path: Path,
    *,
    meta_extra: dict[str, object] | None = None,
) -> dict[str, int]:
    surface_ids: dict[tuple[str, str], int] = {}
    source_ids: dict[str, int] = {}
    surfaces: list[tuple[str, str]] = []
    sources: list[str] = []
    alias_buckets: dict[str, dict[tuple[int, int], int]] = {}
    row_count = 0
    kept_rows = 0

    for alias_norm, surface, lang, source, score in rows:
        if not alias_norm or not surface:
            continue
        row_count += 1

        surface_key = (surface, lang)
        surface_id = surface_ids.get(surface_key)
        if surface_id is None:
            surface_id = len(surfaces)
            surface_ids[surface_key] = surface_id
            surfaces.append(surface_key)

        source_id = source_ids.get(source)
        if source_id is None:
            source_id = len(sources)
            source_ids[source] = source_id
            sources.append(source)

        bucket = alias_buckets.setdefault(alias_norm, {})
        score100 = int(round(float(score) * 100))
        key = (surface_id, source_id)
        prev = bucket.get(key)
        if prev is None or score100 > prev:
            bucket[key] = score100
            if prev is None:
                kept_rows += 1

    meta = {
        "version": 2,
        "source": "direct_rows",
        "row_count": row_count,
        "deduped_row_count": kept_rows,
        "alias_count": len(alias_buckets),
        "surface_count": len(surfaces),
        "source_count": len(sources),
    }
    if meta_extra:
        meta.update(meta_extra)

    aliases = sorted(alias_buckets)
    postings = [
        [(sid, srcid, score100) for (sid, srcid), score100 in sorted(alias_buckets[alias].items())]
        for alias in aliases
    ]
    payload = {
        "meta": meta,
        "aliases": aliases,
        "postings": postings,
        "surfaces": surfaces,
        "sources": sources,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(output_path, "wb", preset=9) as handle:
        pickle.dump(payload, handle, protocol=5)
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


def verify_scowl(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        try:
            archive.getmember("scowl-2020.12.07/final/english-words.95")
            archive.getmember("scowl-2020.12.07/final/american-words.95")
        except KeyError as exc:
            raise RuntimeError(f"{path.name} is missing expected SCOWL members") from exc


def verify_dataset(kind: str, path: Path) -> None:
    if kind == "cedict":
        verify_cedict(path)
    elif kind == "jmdict":
        verify_jmdict(path)
    elif kind == "scowl":
        verify_scowl(path)
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
    from wordfreq import top_n_list, zipf_frequency  # type: ignore
    return top_n_list, zipf_frequency


@lru_cache(maxsize=1_000_000)
def wordfreq_score(word: str, lang: str) -> float:
    _, zipf_frequency = try_import_wordfreq()
    try:
        score = float(zipf_frequency(word, lang))
    except Exception:
        return 0.0
    return max(score, 0.0)


def normalize_pinyin(raw: str) -> tuple[str, str]:
    text = unicodedata.normalize("NFKC", raw).lower()
    text = text.replace("u:", "ü").replace("v", "ü")
    text = ascii_fold(text)
    text = re.sub(r"\d", "", text)
    text = re.sub(r"[^a-zü\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    u_form = text.replace("ü", "u")
    v_form = text.replace("ü", "v")
    return u_form, v_form


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


def iter_cedict_rows(path: Path) -> Iterable[tuple[str, str, str, str, float]]:
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
            pinyin_u, pinyin_v = normalize_pinyin(match.group("pinyin"))
            entry_score = max(wordfreq_score(simp, "zh"), wordfreq_score(trad, "zh"))

            for surface in {simp, trad}:
                yield (
                    normalize_query(surface),
                    surface,
                    "zh",
                    "cc-cedict:surface",
                    entry_score,
                )

            display = simp
            if pinyin_u:
                normalized = normalize_query(pinyin_u)
                yield (normalized, display, "zh", "cc-cedict:pinyin", entry_score)
                for variant in pinyin_variants(pinyin_u):
                    if variant != normalized:
                        yield (variant, display, "zh", "cc-cedict:pinyin-fuzzy", entry_score)
                for alias in chinese_mixed_aliases(display, pinyin_u):
                    yield (alias, display, "zh", "cc-cedict:mixed", entry_score)
            if pinyin_v and pinyin_v != pinyin_u:
                normalized = normalize_query(pinyin_v)
                yield (normalized, display, "zh", "cc-cedict:pinyin-v", entry_score)
                for variant in pinyin_variants(pinyin_v):
                    if variant != normalized:
                        yield (variant, display, "zh", "cc-cedict:pinyin-v-fuzzy", entry_score)


def iter_jmdict_rows(path: Path) -> Iterable[tuple[str, str, str, str, float]]:
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",))
        for _, elem in context:
            if elem.tag != "entry":
                continue
            kebs = [node.text.strip() for node in elem.findall("./k_ele/keb") if node.text]
            rebs = [node.text.strip() for node in elem.findall("./r_ele/reb") if node.text]
            entry_score = 0.0
            for keb in kebs:
                entry_score = max(entry_score, wordfreq_score(keb, "ja"))
            for reb in rebs:
                entry_score = max(entry_score, wordfreq_score(reb, "ja"))

            for keb in kebs:
                yield (
                    normalize_query(keb),
                    keb,
                    "ja",
                    "jmdict:surface",
                    entry_score,
                )

            for reb in rebs:
                yield (
                    normalize_query(reb),
                    reb,
                    "ja",
                    "jmdict:reading",
                    entry_score,
                )
                base_romaji = kana_to_romaji(reb)
                for romaji in romaji_variants(reb):
                    yield (
                        normalize_query(romaji),
                        reb,
                        "ja",
                        "jmdict:romaji" if romaji == base_romaji else "jmdict:romaji-fuzzy",
                        entry_score,
                    )
            elem.clear()


def extract_scowl_file(tar_path: Path, member_name: str) -> list[str]:
    with tarfile.open(tar_path, "r:gz") as archive:
        member = archive.getmember(member_name)
        extracted = archive.extractfile(member)
        if extracted is None:
            return []
        payload = extracted.read()
        try:
            return payload.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return payload.decode("latin-1").splitlines()


def iter_scowl_rows(path: Path) -> Iterable[tuple[str, str, str, str, float]]:
    seen: set[str] = set()
    for member_name in SCOWL_FILES:
        for word in extract_scowl_file(path, member_name):
            item = word.strip()
            if not item:
                continue
            lowered = item.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            yield (normalize_query(lowered), item, "en", "scowl:word", 3.0)


def iter_wordfreq_rows(top_n: int) -> Iterable[tuple[str, str, str, str, float]]:
    top_n_list, zipf_frequency = try_import_wordfreq()
    allowed = re.compile(r"^[A-Za-z][A-Za-z' -]*[A-Za-z]$|^[A-Za-z]$")
    seen: set[str] = set()
    for item in top_n_list("en", top_n):
        word = item.strip()
        if not word:
            continue
        lowered = word.lower()
        if lowered in seen or not allowed.match(word):
            continue
        seen.add(lowered)
        yield (
            normalize_query(lowered),
            word,
            "en",
            "wordfreq:word",
            2.0 + float(zipf_frequency(word, "en")),
        )


def iter_all_rows(
    cedict_path: Path,
    jmdict_path: Path,
    scowl_path: Path,
) -> tuple[Iterable[tuple[str, str, str, str, float]], Counter[str], dict[str, object]]:
    counts = Counter()
    meta = {
        "cedict_path": str(cedict_path),
        "jmdict_path": str(jmdict_path),
        "scowl_path": str(scowl_path),
        "wordfreq_top_n": WORDFREQ_TOP_N,
    }

    def wrapped_rows() -> Iterable[tuple[str, str, str, str, float]]:
        source_iters = (
            ("cedict", iter_cedict_rows(cedict_path)),
            ("jmdict", iter_jmdict_rows(jmdict_path)),
            ("scowl", iter_scowl_rows(scowl_path)),
            ("wordfreq", iter_wordfreq_rows(WORDFREQ_TOP_N)),
        )
        for source_name, rows in source_iters:
            for alias_norm, surface, lang, source, score in rows:
                if not alias_norm or not surface:
                    continue
                counts[f"{source_name}_rows"] += 1
                counts[f"{lang}_rows"] += 1
                yield alias_norm, surface, lang, source, score

    return wrapped_rows(), counts, meta


def build_artifact(
    output_path: Path = OUTPUT_PATH,
    cedict_path: Path = CEDICT_PATH,
    jmdict_path: Path = JMDICT_PATH,
    scowl_path: Path = SCOWL_PATH,
) -> dict[str, object]:
    print(f"[build] output -> {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        print(f"[build] remove existing artifact {output_path}")
        output_path.unlink()

    rows, counts, meta = iter_all_rows(
        cedict_path=cedict_path,
        jmdict_path=jmdict_path,
        scowl_path=scowl_path,
    )
    print("[build] compiling compact index")
    compact_meta = build_compact_index_from_rows(rows, output_path, meta_extra={"builder": meta})
    print(f"[build] ok {output_path}")
    return {"counts": dict(counts), "meta": compact_meta}


def main() -> None:
    ensure_required_sources()
    result = build_artifact()
    print(json.dumps({"output": str(OUTPUT_PATH), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
