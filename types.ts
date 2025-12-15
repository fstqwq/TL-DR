export interface DictionaryEntry {
  id: string; // Unique ID for React keys
  timestamp: number;
  query: string;
  data: DictionaryData;
  nextReview?: number; // for spaced repetition scheduling (ms epoch)
  interval?: number;   // last interval in ms
  ease?: number;       // ease factor (e.g., 2.5)
  reps?: number;       // successful reps count
}

export interface DictionaryData {
  targetWord: string;
  detectedLanguage: 'zh' | 'en' | 'ja' | 'unknown';
  origin?: string; // Origin word for loanwords (e.g. "Television" for "テレビ")
  definitions: {
    zh: string;
    en: string;
    ja: string;
  };
  // Refactored to include the word and the pronunciation
  translations: {
    zh: { word: string; pronunciation: string }; // word: Hanzi, pronunciation: Pinyin
    en: { word: string; pronunciation: string }; // word: English, pronunciation: IPA
    ja: { word: string; pronunciation: string }; // word: Kanji/Kana, pronunciation: Hiragana
  };
  synonyms?: string[]; // Synonyms in the detected language
  antonyms?: string[]; // Antonyms in the detected language
  exampleSentence?: {
    text: string;
    translation: string;
  };
}

export interface WordContext {
  word: string;
  lang: string;
}

export interface LuckySentenceResult {
  usedWords: string[]; // The words from history that were actually used
  content: {
    zh: { text: string; pronunciation: string };
    en: { text: string; pronunciation: string };
    ja: { text: string; pronunciation: string };
  };
}

export interface AppConfig {
  BACKEND_URL?: string;
  MODELS?: Array<{ id: string; name: string }>;
}
