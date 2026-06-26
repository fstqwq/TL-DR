import json


DICTIONARY_SCHEMA = {
    "type": "object",
    "properties": {
        "targetWord": {
            "type": "string",
            "description": "The word being queried. This must be the corrected/standardized version of the user input (e.g., if input is '预约する', this should be '予約する').",
        },
        "detectedLanguage": {
            "type": "string",
            "enum": ["zh", "en", "ja", "unknown"],
            "description": "The detected source language of the query.",
        },
        "partsOfSpeech": {"type": "array", "description": "Part(s) of speech of targetWord in detectedLanguage. Use only lowercase English labels from the enum. Order by common dictionary usage. Return [] if unknown.", "items": {"type": "string", "enum": ["noun", "proper noun", "verb", "adjective", "adverb", "pronoun", "preposition", "conjunction", "interjection", "particle", "determiner", "numeral", "counter", "prefix", "suffix", "phrase", "proverb", "expression"]}},
        "origin": {
            "type": ["string", "null"],
            "description": "If the target word is a Japanese Katakana loanword (Gairaigo), provide the original Western word (e.g. '(English) Television' for 'テレビ'). Otherwise return null.",
        },
        "definitions": {
            "type": "object",
            "properties": {
                "zh": {"type": "string", "description": "Definition/Translation in Chinese (Simplified)."},
                "en": {"type": "string", "description": "Definition/Translation in English."},
                "ja": {"type": "string", "description": "Definition/Translation in Japanese. If the word has Kanji form, include it."},
            },
            "required": ["zh", "en", "ja"],
        },
        "translations": {
            "type": "object",
            "description": "Direct translation of the target word into each language, with its specific pronunciation.",
            "properties": {
                "zh": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string", "description": "The word in Simplified Chinese (e.g. '苹果')."},
                        "pronunciation": {"type": "string", "description": "Pinyin with tones (e.g., 'píng guǒ')."},
                    },
                    "required": ["word", "pronunciation"],
                },
                "en": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string", "description": "The word in English (e.g. 'Apple')."},
                        "pronunciation": {"type": "string", "description": "IPA notation (e.g., '/ˈæp.əl/')."},
                    },
                    "required": ["word", "pronunciation"],
                },
                "ja": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string", "description": "The word in Japanese (e.g. 'リンゴ' or '林檎')."},
                        "pronunciation": {"type": "string", "description": "Hiragana reading (e.g., 'りんご')."},
                    },
                    "required": ["word", "pronunciation"],
                },
            },
            "required": ["zh", "en", "ja"],
        },
        "synonyms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of 1-3 synonyms for the target word in its detected language.",
        },
        "antonyms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of 0-3 antonyms for the target word in its detected language (if applicable).",
        },
        "exampleSentence": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "A short, natural example sentence containing the word in its source language."},
                "translation": {"type": "string", "description": "Translation of the sentence into English (if source is not EN) or Chinese (if source is EN)."},
            },
        },
    },
    "required": ["targetWord", "detectedLanguage", "partsOfSpeech", "definitions", "translations", "synonyms", "antonyms"],
}

LOOKUP_SYSTEM_PROMPT = """You are a smart trilingual dictionary assistant.
Step 1: Auto-Correction & Fuzzy Matching
- Detect if the input contains typos, mixed scripts, or is close to a known word.
- Example: "预约する" (mixed Chinese/Japanese) -> "予約する" (Japanese Standard).
- Example: "aple" (typo) -> "apple".
- Use the corrected/standardized word as the "targetWord" in the JSON output.

Step 2: Analysis
- Identify the language (Chinese, English, or Japanese). If the preferred language is specified (not 'auto'), try to interpret the query in that context. Only if it is clearly from another language, mark it as such.
- Return "partsOfSpeech" for the "targetWord" in the detected source language, not for its translations.
- Use concise lowercase English labels from the schema enum.
- If multiple labels apply, order by common dictionary usage and remove duplicates. If unknown, return [].
- If the word is a Japanese Katakana loanword (Gairaigo), identify the original Western word and put it in the 'origin' field.
- Provide the definition/translation for ALL THREE languages. Be as accurate as dictinary entries, and as concise as possible.
- Provide the EQUIVALENT WORD and PRONUNCIATION for ALL THREE languages in the 'translations' object.
- For Chinese: 'word' is Hanzi, 'pronunciation' is Pinyin.
- For English: 'word' is the English term, 'pronunciation' is IPA.
- For Japanese: 'word' is the most common written form (Kanji/Kana), 'pronunciation' is Hiragana.
Please note the difference between Hanzi and Kanji: the same literals may have different meanings in Chinese and Japanese, so you must provide distinct translations for each language, in this case, translate based on meaning rather than literal wording. For example, "直前" means "immediately before" in Japanese but not a valid term in Chinese - provide appropriate Chinese equivalent like "即将发生之前" instead.
- Provide a list of synonyms and antonyms IN THE DETECTED LANGUAGE of the target word.
- Provide one short example sentence.
- Output MUST STRICTLY follow the provided JSON SCHEMA without any deviations. Start your response directly with the {
"""

AUTOCOMPLETE_PROMPT = """Autocomplete for a Chinese, English, Japanese dictionary. Input is a partial string, possibly misspelled or incomplete. Infer likely intended word completions. Output words only. One suggestion per line. At most three lines. Place the most possible answer at first. No numbering, no punctuation, no explanations. Each output must be a single word or fixed dictionary form. If the input clearly suggests a multi-word phrase, output the full phrase and preserve spaces. Example: "for examp" -> "for example". Consider possibility of Kana / Pinyin:
zhonggu
中国
natsuyas
夏休み
Output immediately."""

LUCKY_SCHEMA = {
    "type": "object",
    "properties": {
        "usedWords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of the specific words from the input list that were successfully used.",
        },
        "content": {
            "type": "object",
            "properties": {
                "zh": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "pronunciation": {"type": "string", "description": "Pinyin with tones (e.g., 'píng guǒ')."},
                    },
                    "required": ["text", "pronunciation"],
                },
                "en": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "pronunciation": {"type": "string", "description": "IPA notation (e.g., '/ˈæp.əl/')."},
                    },
                    "required": ["text", "pronunciation"],
                },
                "ja": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "pronunciation": {"type": "string", "description": "Hiragana reading (e.g., 'りんご')."},
                    },
                    "required": ["text", "pronunciation"],
                },
            },
            "required": ["zh", "en", "ja"],
        },
    },
    "required": ["usedWords", "content"],
}

LUCKY_SYSTEM_PROMPT = """You are a creative language tutor.
Task: Create a single coherent, creative, or funny sentence that incorporates as many of the provided words as possible.
The input words can be in any of the three languages: Chinese (Simplified), English, or Japanese. When forming the sentence, you may need to adjust word forms, tenses, or use synonyms to ensure naturalness, and ensure the sentence is fully coherent in the target language.
Please note the difference between Hanzi and Kanji: the same literals may have different meanings in Chinese and Japanese, so you must provide distinct translations for each language, in this case, translate based on meaning rather than direcly using the literal wording. For example, "直前" means "immediately before" in Japanese but not a valid term in Chinese - provide appropriate Chinese equivalent like "即将发生之前" instead when forming the Chinese sentence.

Output:
1. The sentence in English, Chinese (Simplified), and Japanese.
2. Pronunciations for all 3.
3. A list of which input words were successfully used.

Output MUST STRICTLY follow the provided JSON SCHEMA. Start your response directly with the {{.
"""


def lookup_system_content() -> str:
    return LOOKUP_SYSTEM_PROMPT + json.dumps(DICTIONARY_SCHEMA, ensure_ascii=False, indent=None)


def lookup_user_content(query: str, preferred_language: str, augmented_content: str) -> str:
    return (
        f"Analyze the query: \"{query}\". User preferred language context: {preferred_language} "
        "(If 'auto', detect. If specified, bias interpretation towards this language)."
        + (
            f" Additionally, you can use the following content from dictionary about the word: {augmented_content}"
            if augmented_content
            else ""
        )
    )


def lucky_system_content() -> str:
    return LUCKY_SYSTEM_PROMPT + json.dumps(LUCKY_SCHEMA, ensure_ascii=False, indent=None)
