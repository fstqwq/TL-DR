import { DictionaryData, LuckySentenceResult, WordContext, AppConfig, LookupSource, LocalAutocompleteSuggestion } from "../types";

// --- CONFIGURATION ---

let runtimeConfig: AppConfig = {};

export const setRuntimeConfig = (config: AppConfig) => {
  runtimeConfig = config || {};
};

const getApiBaseUrl = () => {
  const RAW_BASE_URL = runtimeConfig.BACKEND_URL || 'http://localhost:5000';
  return RAW_BASE_URL.replace(/\/$/, "");
};

const toStringValue = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const normalizeOptionalOrigin = (value: unknown): string => {
  const normalized = toStringValue(value).trim();
  if (!normalized) return "";
  const lowered = normalized.toLowerCase();
  return lowered === "null" || lowered === "none" || lowered === "nil" ? "" : normalized;
};

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
  const originRaw = normalizeOptionalOrigin(data.origin);
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

type LookupStreamHandlers = {
  onProgress?: (stage: string, message: string) => void;
  onSources?: (sources: LookupSource[]) => void;
  onError?: (stage: string, message: string) => void;
};

const normalizeLookupSources = (value: unknown): LookupSource[] =>
  Array.isArray(value)
    ? value.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const source = item as Record<string, unknown>;
        return [{
          id: toStringValue(source.id),
          name: toStringValue(source.name),
          pageUrl: toStringValue(source.pageUrl),
          fetchUrl: toStringValue(source.fetchUrl),
          preview: toStringValue(source.preview),
          raw: toStringValue(source.raw),
        }];
      })
    : [];

export const lookupWord = async (
  query: string,
  preferredLanguage: string = 'auto',
  model: string,
  signal?: AbortSignal,
  handlers: LookupStreamHandlers = {}
): Promise<DictionaryData> => {
  const timestamp = Date.now();
  const response = await fetch(`${getApiBaseUrl()}/api/lookup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, preferredLanguage, model, timestamp }),
    signal,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Backend Error: ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error("Lookup stream did not return a body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lookupResult: DictionaryData | null = null;
  let streamError: Error | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const rawBlock = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseEventBlock(rawBlock);
      if (parsed) {
        try {
          const payload = JSON.parse(parsed.data || "{}") as Record<string, unknown>;
          if (parsed.event === "progress") {
            const stage = typeof payload.stage === "string" ? payload.stage : "unknown";
            const message = typeof payload.message === "string" ? payload.message : "";
            handlers.onProgress?.(stage, message);
          } else if (parsed.event === "sources") {
            handlers.onSources?.(normalizeLookupSources(payload.sources));
          } else if (parsed.event === "result") {
            lookupResult = normalizeDictionaryData(payload, query);
          } else if (parsed.event === "error") {
            const stage = typeof payload.stage === "string" ? payload.stage : "unknown";
            const message = typeof payload.message === "string" ? payload.message : "Unknown lookup error";
            handlers.onError?.(stage, message);
            streamError = new Error(message);
          }
        } catch (error) {
          console.error("Lookup stream parse error:", error);
        }
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (done) break;
  }

  if (lookupResult) return lookupResult;
  if (streamError) throw streamError;
  throw new Error("Lookup stream ended without a result.");
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

const parseSseEventBlock = (block: string): { event: string; data: string } | null => {
  const trimmed = block.trim();
  if (!trimmed) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of trimmed.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  return { event, data: dataLines.join("\n") };
};

const normalizeSuggestions = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

const normalizeLocalSuggestions = (value: unknown): LocalAutocompleteSuggestion[] =>
  Array.isArray(value)
    ? value.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const suggestion = item as Record<string, unknown>;
        const surface = toStringValue(suggestion.surface).trim();
        const reading = toStringValue(suggestion.reading).trim();
        const meaning = toStringValue(suggestion.meaning).trim();
        const lang = suggestion.lang;
        if (!surface || (lang !== "zh" && lang !== "en" && lang !== "ja")) return [];
        return [{ surface, reading, meaning, lang }];
      })
    : [];

const autocompleteRequest = async (
  path: string,
  partialInput: string,
  preferredLanguage: string = 'auto',
  signal?: AbortSignal
): Promise<{ suggestions?: unknown; error?: unknown }> => {
  const timestamp = Date.now();
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ partialInput, preferredLanguage, timestamp }),
    signal,
  });

  if (!response.ok) {
    let message = `Backend Error: ${response.statusText}`;
    try {
      const payload = await response.json() as { error?: unknown };
      if (typeof payload.error === "string" && payload.error.trim()) {
        message = payload.error;
      }
    } catch {
      const text = await response.text();
      if (text) message = text;
    }
    throw new Error(message);
  }

  return await response.json() as { suggestions?: unknown; error?: unknown };
};

export const autocompleteLocalWords = async (
  partialInput: string,
  preferredLanguage: string = 'auto',
  signal?: AbortSignal
): Promise<LocalAutocompleteSuggestion[]> => {
  const payload = await autocompleteRequest('/api/autocomplete/local', partialInput, preferredLanguage, signal);
  return normalizeLocalSuggestions(payload.suggestions);
};

export const autocompleteLlmWords = async (
  partialInput: string,
  preferredLanguage: string = 'auto',
  signal?: AbortSignal
): Promise<string[]> => {
  const payload = await autocompleteRequest('/api/autocomplete/llm', partialInput, preferredLanguage, signal);
  return normalizeSuggestions(payload.suggestions);
};
