import { DictionaryData, LuckySentenceResult, WordContext } from "../types";

// --- CONFIGURATION ---

const getApiBaseUrl = () => {
  const RUNTIME_CONFIG = window.APP_CONFIG || {};
  const RAW_BASE_URL = RUNTIME_CONFIG.BACKEND_URL || 'http://localhost:5000';
  return RAW_BASE_URL.replace(/\/$/, "");
};

export const lookupWord = async (query: string, preferredLanguage: string = 'auto', model: string = 'gemini-2.0-flash'): Promise<DictionaryData> => {
  const timestamp = Date.now();
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, preferredLanguage, model, timestamp }),
    });

    if (!response.ok) throw new Error(`Backend Error: ${response.statusText}`);
    return await response.json() as DictionaryData;
  } catch (error) {
    console.error("Backend API Error:", error);
    throw error;
  }
};

export const generateSentence = async (words: WordContext[], model: string = 'gemini-2.0-flash'): Promise<LuckySentenceResult> => {
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