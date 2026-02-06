import { DictionaryData, LuckySentenceResult, WordContext, AppConfig, AutocompleteResult } from "../types";

// --- CONFIGURATION ---

let runtimeConfig: AppConfig = {};

export const setRuntimeConfig = (config: AppConfig) => {
  runtimeConfig = config || {};
};

const getApiBaseUrl = () => {
  const RAW_BASE_URL = runtimeConfig.BACKEND_URL || 'http://localhost:5000';
  return RAW_BASE_URL.replace(/\/$/, "");
};

const getFastModel = () => {
  const fastModel = runtimeConfig.FAST_MODEL;
  if (!fastModel || typeof fastModel !== 'string') {
    throw new Error("FAST_MODEL is not configured in /config.json");
  }
  return fastModel;
};

const toStringValue = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const toLanguage = (value: unknown): DictionaryData["detectedLanguage"] => {
  if (value === "zh" || value === "en" || value === "ja" || value === "unknown") return value;
  return "unknown";
};

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

const normalizeDictionaryData = (raw: unknown, query: string): DictionaryData => {
  const data = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const translations = (data.translations && typeof data.translations === "object"
    ? data.translations
    : {}) as Record<string, unknown>;
  const definitions = (data.definitions && typeof data.definitions === "object"
    ? data.definitions
    : {}) as Record<string, unknown>;

  const targetWord = toStringValue(data.targetWord, query).trim() || query;
  const originRaw = toStringValue(data.origin).trim();
  const exampleRaw = (data.exampleSentence && typeof data.exampleSentence === "object"
    ? data.exampleSentence
    : null) as Record<string, unknown> | null;

  return {
    targetWord,
    detectedLanguage: toLanguage(data.detectedLanguage),
    ...(originRaw ? { origin: originRaw } : {}),
    definitions: {
      zh: toStringValue(definitions.zh),
      en: toStringValue(definitions.en),
      ja: toStringValue(definitions.ja),
    },
    translations: {
      zh: {
        word: toStringValue((translations.zh as Record<string, unknown> | undefined)?.word),
        pronunciation: toStringValue((translations.zh as Record<string, unknown> | undefined)?.pronunciation),
      },
      en: {
        word: toStringValue((translations.en as Record<string, unknown> | undefined)?.word),
        pronunciation: toStringValue((translations.en as Record<string, unknown> | undefined)?.pronunciation),
      },
      ja: {
        word: toStringValue((translations.ja as Record<string, unknown> | undefined)?.word),
        pronunciation: toStringValue((translations.ja as Record<string, unknown> | undefined)?.pronunciation),
      },
    },
    synonyms: toStringArray(data.synonyms),
    antonyms: toStringArray(data.antonyms),
    ...(exampleRaw
      ? {
          exampleSentence: {
            text: toStringValue(exampleRaw.text),
            translation: toStringValue(exampleRaw.translation),
          },
        }
      : {}),
  };
};

export const lookupWord = async (query: string, preferredLanguage: string = 'auto', model: string): Promise<DictionaryData> => {
  const timestamp = Date.now();
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, preferredLanguage, model, timestamp }),
    });

    if (!response.ok) throw new Error(`Backend Error: ${response.statusText}`);
    const raw = await response.json();
    return normalizeDictionaryData(raw, query);
  } catch (error: any) {
    if (error?.name !== 'AbortError') {
      console.error("Backend API Error:", error);
    }
    throw error;
  }
};

export const generateSentence = async (words: WordContext[], model: string): Promise<LuckySentenceResult> => {
  const timestamp = Date.now();
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/generate-sentence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ words, model, timestamp }),
    });

    if (!response.ok) throw new Error(`Backend Error: ${response.statusText}`);
    return await response.json() as LuckySentenceResult;
  } catch (error) {
    console.error("Backend API Error:", error);
    throw error;
  }
};

export const autocompleteWords = async (
  partialInput: string,
  _model: string,
  preferredLanguage: string = 'auto',
  signal?: AbortSignal
): Promise<string[]> => {
  const timestamp = Date.now();
  const model = getFastModel();
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/autocomplete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ partialInput, preferredLanguage, model, timestamp }),
      signal,
    });

    if (!response.ok) throw new Error(`Backend Error: ${response.statusText}`);
    const data = await response.json() as AutocompleteResult;
    return Array.isArray(data.suggestions) ? data.suggestions : [];
  } catch (error) {
    console.error("Backend API Error:", error);
    throw error;
  }
};
