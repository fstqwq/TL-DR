import type { LookupSource } from '../types';

export type FormattedSourceItem = {
  term?: string;
  label?: string;
  text: string;
};

export type FormattedSourcePreview = {
  title?: string;
  reading?: string;
  items: FormattedSourceItem[];
};

const SOURCE_PARSER_ORDER: Record<string, Array<(text: string) => FormattedSourcePreview | null>> = {
  'cc-cedict': [parseHeaderBullets],
  jmdict: [parseHeaderBullets],
  cmudict: [parseHeaderBullets],
  dictionaryapi: [parseDictionaryApi],
  jisho: [parseColonEntries],
  weblio: [parseWeblio],
  wiktionary: [parseWiktionaryPreview, parseWiktionary],
};

const GENERIC_PARSERS = [parseHeaderBullets, parseDictionaryApi, parseColonEntries, parseWiktionary, parseWeblio];

export const formatLookupSourcePreview = (source: LookupSource): FormattedSourcePreview | null => {
  const text = normalizeText(source.preview);
  if (!text) return null;

  const parsers = SOURCE_PARSER_ORDER[source.id] || GENERIC_PARSERS;
  for (const parser of parsers) {
    const parsed = parser(text);
    if (isUsefulPreview(parsed)) return parsed;
  }
  return null;
};

const isUsefulPreview = (preview: FormattedSourcePreview | null): preview is FormattedSourcePreview =>
  !!preview && (!!preview.title || !!preview.reading || preview.items.length > 0);

const normalizeText = (text: string) => text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();

const cleanInline = (text: string) =>
  text
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.;:!?])/g, '$1')
    .trim();

const stripWikiMarkup = (text: string) =>
  cleanInline(
    text
      .replace(/\[\[(?:[^\]|]+\|)?([^\]]+)\]\]/g, '$1')
      .replace(/\{\{[^{}]{1,120}\}\}/g, '')
      .replace(/'''?/g, '')
  );

const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const normalizePartOfSpeech = (raw: string) => {
  const lowered = raw.toLowerCase();
  if (lowered.includes('proper noun')) return 'proper noun';
  if (lowered.includes('noun')) return 'noun';
  if (lowered.includes('verb')) return 'verb';
  if (lowered.includes('adjective')) return 'adjective';
  if (lowered.includes('adverb')) return 'adverb';
  if (lowered.includes('expression')) return 'expression';

  return cleanInline(raw.replace(/[()]/g, ' '))
    .replace(/\b(common|futsuumeishi|ichidan|godan|transitive|intransitive)\b/gi, '')
    .trim();
};

function parseHeaderBullets(text: string): FormattedSourcePreview | null {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2) return null;

  const header = lines[0].match(/^(.+?)(?:\s+\[([^\]]+)\])?$/);
  if (!header) return null;
  if (/^=+.+?=+$/.test(lines[0])) return null;

  const items = lines.slice(1).flatMap((line) => {
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (!bullet) return [];
    const body = cleanInline(bullet[1]);
    if (!body) return [];

    const tagMatch = body.match(/^\((.*)\)\s+(.+)$/);
    if (!tagMatch) return [{ text: body }];

    const label = normalizePartOfSpeech(tagMatch[1]);
    const itemText = cleanInline(tagMatch[2]);
    return itemText ? [{ label, text: itemText }] : [];
  });

  if (!items.length) return null;
  return {
    title: cleanInline(header[1]),
    reading: header[2] ? cleanInline(header[2]) : undefined,
    items,
  };
}

function parseWiktionaryPreview(text: string): FormattedSourcePreview | null {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2 || !lines[0].includes(' · ')) return null;

  const items = lines.slice(1).flatMap((line) => {
    const bullet = line.match(/^-\s+(.+)$/);
    if (!bullet) return [];
    const itemText = cleanInline(bullet[1]);
    return itemText ? [{ text: itemText }] : [];
  });

  return items.length ? { title: cleanInline(lines[0]), items } : null;
}

function parseColonEntries(text: string): FormattedSourcePreview | null {
  const items = text.split('\n').flatMap((line) => {
    const match = line.trim().match(/^(.+?)\s*(?::|\uFF1A)\s*(.+)$/);
    if (!match) return [];
    const term = cleanInline(match[1]);
    const itemText = cleanInline(match[2]);
    return term && itemText ? [{ term, text: itemText }] : [];
  });
  return items.length ? { items } : null;
}

function parseDictionaryApi(text: string): FormattedSourcePreview | null {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  let title = '';
  let reading = '';
  const items: FormattedSourceItem[] = [];

  for (const line of lines) {
    const match = line.match(/^([^:]+):\s*(.+)$/);
    if (!match) continue;
    const key = match[1].toLowerCase();
    const value = cleanInline(match[2]);
    if (!value) continue;

    if (key === 'word') {
      title = value;
      continue;
    }
    if (key === 'phonetic') {
      reading = value;
      continue;
    }
    if (key === 'meanings') {
      for (const part of value.split(/\s+\|\s+/)) {
        const meaningMatch = part.match(/^([^:]+):\s*(.+)$/);
        if (meaningMatch) {
          items.push({ label: cleanInline(meaningMatch[1]), text: cleanInline(meaningMatch[2]) });
        } else {
          items.push({ text: cleanInline(part) });
        }
      }
    }
  }

  return title || reading || items.length ? { title, reading, items } : null;
}

function parseWiktionary(text: string): FormattedSourcePreview | null {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  let language = '';
  let currentSection = '';
  const items: FormattedSourceItem[] = [];

  for (const line of lines) {
    const heading = line.match(/^(=+)\s*([^=]+?)\s*\1$/);
    if (heading) {
      const level = heading[1].length;
      const value = cleanInline(heading[2]);
      if (level === 2) {
        if (language) break;
        language = value;
        currentSection = '';
      } else if (level === 3) {
        currentSection = value;
      }
      continue;
    }

    const definition = line.match(/^#+\s*(.+)$/);
    if (!definition) continue;
    const textValue = stripWikiMarkup(definition[1]);
    if (!textValue || textValue === '*') continue;
    const label = currentSection && !/pronunciation|synonyms|antonyms/i.test(currentSection)
      ? currentSection.toLowerCase()
      : undefined;
    items.push({ label, text: textValue });
  }

  return items.length ? { title: language, items } : null;
}

function parseWeblio(text: string): FormattedSourcePreview | null {
  const compact = cleanInline(text);
  if (!compact) return null;

  const encyclopediaPreview = parseWeblioEncyclopedia(compact);
  if (encyclopediaPreview) return encyclopediaPreview;

  const readingMatch = compact.match(/^(.*?)\u8AAD\u307F\u65B9\s*(?::|\uFF1A)\s*([^0-9\uFF10-\uFF19]+)([\s\S]*)$/);
  const title = readingMatch ? cleanInline(readingMatch[1]) : '';
  const reading = readingMatch ? cleanInline(readingMatch[2]) : '';
  const body = readingMatch ? readingMatch[3] : compact;
  if (!readingMatch && !/[0-9\uFF10-\uFF19]/.test(body)) return null;

  const items = body
    .split(/(?=[0-9\uFF10-\uFF19])/)
    .flatMap((part) => {
      const match = part.match(/^[0-9\uFF10-\uFF19]\s*(.+)$/);
      const itemText = cleanInline(match ? match[1] : part);
      return itemText ? [{ text: itemText }] : [];
    });

  return title || reading || items.length ? { title, reading, items } : null;
}

function parseWeblioEncyclopedia(text: string): FormattedSourcePreview | null {
  if (!/(?:Wikipedia|\u30A6\u30A3\u30AD\u30DA\u30C7\u30A3\u30A2|\u30D5\u30EA\u30FC\u767E\u79D1\u4E8B\u5178)/.test(text)) {
    return null;
  }

  const titleMatch = text.match(/^(.+?)\u51FA\u5178(?::|\uFF1A)?/);
  if (!titleMatch) return null;

  const title = cleanInline(titleMatch[1]);
  if (!title) return null;

  let body = text.slice(titleMatch[0].length).trim();
  const versionEnd = body.search(/\u7248[\)\uFF09]/);
  if (versionEnd >= 0) {
    body = body.slice(versionEnd + 2).trim();
  }

  const escapedTitle = escapeRegExp(title);
  const sentenceStarts = [
    new RegExp(`${escapedTitle}\\uFF08[^\\uFF09]+\\uFF09\\u306F`),
    new RegExp(`${escapedTitle}\\u3068\\u306F`),
    new RegExp(`${escapedTitle}\\u306F`),
  ];
  const sentenceStart = sentenceStarts
    .map((pattern) => body.search(pattern))
    .filter((index) => index >= 0)
    .sort((a, b) => a - b)[0];
  if (sentenceStart !== undefined) {
    body = body.slice(sentenceStart).trim();
  }

  const sentence = body.match(/^(.+?\u3002)/)?.[1] || body.slice(0, 180);
  const summary = cleanInline(sentence);
  if (!summary) return null;

  return {
    title,
    items: [{ text: summary }],
  };
}
