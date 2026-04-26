import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const formatterPath = new URL('../components/sourcePreviewFormatters.ts', import.meta.url);
const formatterSource = await readFile(formatterPath, 'utf8');
const compiled = await transform(formatterSource, {
  loader: 'ts',
  format: 'esm',
  target: 'es2022',
});

const tempDir = await mkdtemp(path.join(tmpdir(), 'tldr-source-preview-'));
const compiledPath = path.join(tempDir, 'sourcePreviewFormatters.mjs');
await writeFile(compiledPath, compiled.code, 'utf8');

const { formatLookupSourcePreview } = await import(pathToFileURL(compiledPath).href);

const source = (id, name, preview, raw = '') => ({
  id,
  name,
  pageUrl: `https://example.test/${id}`,
  fetchUrl: `https://example.test/${id}.raw`,
  preview,
  raw,
});

const cases = [
  {
    lang: 'en',
    category: 'common',
    word: 'make',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: make',
      'phonetic: /meik/',
      'meanings: verb: form by combining parts; cause to exist | noun: brand or type',
    ].join('\n')),
    expectTitle: 'make',
    expectIncludes: ['form by combining parts'],
  },
  {
    lang: 'en',
    category: 'common',
    word: 'take',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: take',
      'phonetic: /teik/',
      'meanings: verb: lay hold of; carry or bring with oneself | noun: a scene filmed at one time',
    ].join('\n')),
    expectTitle: 'take',
    expectIncludes: ['lay hold of'],
  },
  {
    lang: 'en',
    category: 'common',
    word: 'time',
    source: source(
      'wiktionary',
      'Wiktionary',
      'English · Noun\n- The inevitable progression into the future.\n- A duration of time.',
      '==English==\n===Noun===\n# The inevitable progression into the future.\n# A duration of time.\n==Scots==\n===Noun===\n# A tame animal.'
    ),
    expectTitle: 'English · Noun',
    expectIncludes: ['progression into the future'],
    rejectIncludes: ['tame animal'],
  },
  {
    lang: 'en',
    category: 'common',
    word: 'work',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: work',
      'phonetic: /werk/',
      'meanings: noun: activity involving effort | verb: be engaged in physical or mental activity',
    ].join('\n')),
    expectTitle: 'work',
    expectIncludes: ['activity involving effort'],
  },
  {
    lang: 'en',
    category: 'common',
    word: 'home',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: home',
      'phonetic: /hohm/',
      'meanings: noun: a place where one lives | adverb: to or at the place where one lives',
    ].join('\n')),
    expectTitle: 'home',
    expectIncludes: ['place where one lives'],
  },
  {
    lang: 'en',
    category: 'variant',
    word: 'running',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: running',
      'phonetic: /ruhn-ing/',
      'meanings: noun: the action of running | adjective: moving continuously',
    ].join('\n')),
    expectTitle: 'running',
    expectIncludes: ['action of running'],
  },
  {
    lang: 'en',
    category: 'variant',
    word: 'better',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: better',
      'phonetic: /bet-er/',
      'meanings: adjective: more desirable or satisfactory | verb: improve on or surpass',
    ].join('\n')),
    expectTitle: 'better',
    expectIncludes: ['more desirable'],
  },
  {
    lang: 'en',
    category: 'variant',
    word: 'children',
    source: source('wiktionary', 'Wiktionary', 'English · Noun\n- plural of child'),
    expectTitle: 'English · Noun',
    expectIncludes: ['plural of child'],
  },
  {
    lang: 'en',
    category: 'wiktionary template regression',
    word: 'tldr',
    source: source(
      'wiktionary',
      'Wiktionary',
      'English · Phrase\n- (chiefly; Internet slang) Alternative form of tl;dr.',
      '==English==\n===Phrase===\n{{head|en|phrase}}\n# {{lb|en|chiefly|Internet slang}} {{alt form|en|tl;dr}}.'
    ),
    expectTitle: 'English · Phrase',
    expectIncludes: ['(chiefly; Internet slang) Alternative form of tl;dr.'],
    rejectIncludes: ['# .'],
  },
  {
    lang: 'en',
    category: 'rare noun',
    word: 'zephyr',
    source: source('wiktionary', 'Wiktionary', 'English · Noun\n- A light wind from the west.\n- A gentle breeze.'),
    expectTitle: 'English · Noun',
    expectIncludes: ['gentle breeze'],
  },
  {
    lang: 'en',
    category: 'rare noun',
    word: 'palimpsest',
    source: source('dictionaryapi', 'dictionaryapi.dev', [
      'word: palimpsest',
      'phonetic: /pal-imp-sest/',
      'meanings: noun: a manuscript page reused after earlier writing has been erased',
    ].join('\n')),
    expectTitle: 'palimpsest',
    expectIncludes: ['manuscript page'],
  },
  {
    lang: 'zh',
    category: 'common',
    word: '我',
    source: source('cc-cedict', 'CC-CEDICT', '我 [wǒ]\n- I\n- me'),
    expectTitle: '我',
    expectReading: 'wǒ',
    expectIncludes: ['I'],
  },
  {
    lang: 'zh',
    category: 'common',
    word: '是',
    source: source('cc-cedict', 'CC-CEDICT', '是 [shì]\n- is\n- are\n- am'),
    expectTitle: '是',
    expectReading: 'shì',
    expectIncludes: ['is'],
  },
  {
    lang: 'zh',
    category: 'common',
    word: '有',
    source: source('cc-cedict', 'CC-CEDICT', '有 [yǒu]\n- to have\n- there is'),
    expectTitle: '有',
    expectReading: 'yǒu',
    expectIncludes: ['to have'],
  },
  {
    lang: 'zh',
    category: 'common',
    word: '人',
    source: source('cc-cedict', 'CC-CEDICT', '人 [rén]\n- person\n- people'),
    expectTitle: '人',
    expectReading: 'rén',
    expectIncludes: ['person'],
  },
  {
    lang: 'zh',
    category: 'common',
    word: '好',
    source: source('cc-cedict', 'CC-CEDICT', '好 [hǎo]\n- good\n- well'),
    expectTitle: '好',
    expectReading: 'hǎo',
    expectIncludes: ['good'],
  },
  {
    lang: 'zh',
    category: 'variant',
    word: '不是',
    source: source('cc-cedict', 'CC-CEDICT', '不是 [bù shì]\n- no\n- is not\n- not'),
    expectTitle: '不是',
    expectReading: 'bù shì',
    expectIncludes: ['is not'],
  },
  {
    lang: 'zh',
    category: 'variant',
    word: '他们',
    source: source('cc-cedict', 'CC-CEDICT', '他们 [tā men]\n- they\n- them'),
    expectTitle: '他们',
    expectReading: 'tā men',
    expectIncludes: ['they'],
  },
  {
    lang: 'zh',
    category: 'variant',
    word: '这里',
    source: source('cc-cedict', 'CC-CEDICT', '这里 [zhè lǐ]\n- here\n- this place'),
    expectTitle: '这里',
    expectReading: 'zhè lǐ',
    expectIncludes: ['this place'],
  },
  {
    lang: 'zh',
    category: 'rare noun',
    word: '饕餮',
    source: source('cc-cedict', 'CC-CEDICT', '饕餮 [tāo tiè]\n- Taotie\n- legendary voracious beast\n- glutton'),
    expectTitle: '饕餮',
    expectReading: 'tāo tiè',
    expectIncludes: ['legendary voracious beast'],
  },
  {
    lang: 'zh',
    category: 'rare noun',
    word: '檐铃',
    source: source('cc-cedict', 'CC-CEDICT', '檐铃 [yán líng]\n- wind bell hung from eaves\n- eaves bell'),
    expectTitle: '檐铃',
    expectReading: 'yán líng',
    expectIncludes: ['wind bell'],
  },
  {
    lang: 'ja',
    category: 'common',
    word: 'する',
    source: source('jmdict', 'JMdict', 'する [する]\n- (suru verb - irregular) to do\n- (suru verb - irregular) to make'),
    expectTitle: 'する',
    expectReading: 'する',
    expectIncludes: ['to do'],
  },
  {
    lang: 'ja',
    category: 'common',
    word: 'ある',
    source: source('jmdict', 'JMdict', 'ある [ある]\n- (Godan verb with ru ending) to be; to exist\n- (Godan verb with ru ending) to have'),
    expectTitle: 'ある',
    expectReading: 'ある',
    expectIncludes: ['to exist'],
  },
  {
    lang: 'ja',
    category: 'common',
    word: '人',
    source: source('jmdict', 'JMdict', '人 [ひと]\n- (noun (common) (futsuumeishi)) person\n- (noun (common) (futsuumeishi)) human being'),
    expectTitle: '人',
    expectReading: 'ひと',
    expectIncludes: ['person'],
  },
  {
    lang: 'ja',
    category: 'common',
    word: '出す',
    source: source('jmdict', 'JMdict', '出す [いず]\n- (verb) to leave; to exit; to go out; to come out; to get out\n- (verb) to leave (on a journey); to depart; to start out; to set out'),
    expectTitle: '出す',
    expectReading: 'いず',
    expectIncludes: ['to leave'],
  },
  {
    lang: 'ja',
    category: 'common',
    word: '椅子',
    source: source('jisho', 'Jisho', '椅子: chair, seat, stool\nイス: swords (suit)\n以色列: Israel'),
    expectIncludes: ['chair, seat, stool'],
    expectTerms: ['椅子', 'イス', '以色列'],
  },
  {
    lang: 'ja',
    category: 'variant',
    word: '出した',
    source: source('jmdict', 'JMdict', '出した [だした]\n- (verb) put out; sent out\n- (verb) produced; submitted'),
    expectTitle: '出した',
    expectReading: 'だした',
    expectIncludes: ['put out'],
  },
  {
    lang: 'ja',
    category: 'variant',
    word: '食べた',
    source: source('jmdict', 'JMdict', '食べた [たべた]\n- (verb) ate\n- (verb) has eaten'),
    expectTitle: '食べた',
    expectReading: 'たべた',
    expectIncludes: ['ate'],
  },
  {
    lang: 'ja',
    category: 'variant',
    word: '大きな',
    source: source('jmdict', 'JMdict', '大きな [おおきな]\n- (pre-noun adjectival) big\n- (pre-noun adjectival) large'),
    expectTitle: '大きな',
    expectReading: 'おおきな',
    expectIncludes: ['large'],
  },
  {
    lang: 'ja',
    category: 'rare noun',
    word: '袈裟',
    source: source('jmdict', 'JMdict', '袈裟 [けさ]\n- (noun (common) (futsuumeishi)) kasaya\n- (noun (common) (futsuumeishi)) Buddhist monk robe'),
    expectTitle: '袈裟',
    expectReading: 'けさ',
    expectIncludes: ['Buddhist monk robe'],
  },
  {
    lang: 'ja',
    category: 'rare noun',
    word: '勾玉',
    source: source('jmdict', 'JMdict', '勾玉 [まがたま]\n- (noun (common) (futsuumeishi)) comma-shaped jewel\n- (noun (common) (futsuumeishi)) curved magatama bead'),
    expectTitle: '勾玉',
    expectReading: 'まがたま',
    expectIncludes: ['comma-shaped jewel'],
  },
  {
    lang: 'ja',
    category: 'wiktionary regression',
    word: 'いす',
    source: source('wiktionary', 'Wiktionary', [
      '==Japanese==',
      '===Pronunciation===',
      '===Noun===',
      '==Miyako==',
      '===Pronunciation===',
      '* IPA(key): /iss/',
      '===Noun===',
      '# stone',
    ].join('\n')),
    expectFallback: true,
    rejectIncludes: ['stone'],
  },
  {
    lang: 'ja',
    category: 'weblio encyclopedia regression',
    word: 'Vite',
    source: source('weblio', 'Weblio', [
      'Vite\u51FA\u5178: \u30D5\u30EA\u30FC\u767E\u79D1\u4E8B\u5178\u300E\u30A6\u30A3\u30AD\u30DA\u30C7\u30A3\u30A2\uFF08Wikipedia\uFF09\u300F\uFF082026/03/16 14:15 UTC \u7248\uFF09',
      'Vite\u4F5C\u8005\u5C24\u96E8\u6E13\u521D\u72482020\u5E744\u670820\u65E5',
      'Vite\uFF08\u30F4\u30A3\u30FC\u30C8\u3001\u30D5\u30E9\u30F3\u30B9\u8A9E: [vit]\uFF09\u306F\u3001\u5C24\u96E8\u6E13\uFF08Vue.js\u306E\u4F5C\u8005\uFF09\u306B\u3088\u3063\u3066\u4F5C\u3089\u308C\u305F\u30ED\u30FC\u30AB\u30EB\u306E\u958B\u767A\u7528\u30B5\u30FC\u30D0\u30FC\u3067\u3042\u308B\u3002',
      'github.com/vitejs/vite TypeScript Node.js ES Module',
    ].join('')),
    expectTitle: 'Vite',
    expectIncludes: ['\u30ED\u30FC\u30AB\u30EB\u306E\u958B\u767A\u7528\u30B5\u30FC\u30D0\u30FC'],
    rejectIncludes: ['2026/03/16', 'github.com'],
  },
];

const failures = [];

for (const testCase of cases) {
  try {
    verifyCase(testCase);
  } catch (error) {
    failures.push(`${testCase.lang}/${testCase.category}/${testCase.word}: ${error.message}`);
  }
}

await rm(tempDir, { recursive: true, force: true });

if (failures.length) {
  console.error(`source preview formatter tests failed: ${failures.length}/${cases.length}`);
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(`source preview formatter tests passed: ${cases.length}/${cases.length}`);
  console.log('fixtures: en 10, zh 10, ja 10 + Wiktionary/Weblio regressions');
}

function verifyCase(testCase) {
  const formatted = formatLookupSourcePreview(testCase.source);
  const rows = summaryRows(formatted, testCase.source.preview);
  assert(rows.length <= 3, `folded preview should be at most 3 rows, got ${rows.length}`);

  if (testCase.expectFallback) {
    assert(formatted === null, 'expected parser failure so UI can fallback to raw preview');
    assertMissing(rows.join('\n'), testCase.rejectIncludes || []);
    return;
  }

  assert(formatted, 'expected formatted preview');
  assertEqual(formatted.title || '', testCase.expectTitle || formatted.title || '', 'title');
  assertEqual(formatted.reading || '', testCase.expectReading || formatted.reading || '', 'reading');

  if (testCase.expectTerms) {
    const terms = formatted.items.map((item) => item.term).filter(Boolean);
    for (const term of testCase.expectTerms) assert(terms.includes(term), `missing term: ${term}`);
  }

  if (testCase.source.id === 'jisho') {
    assert(formatted.items.length > 0, 'Jisho should render colon entries as structured rows');
    assert(formatted.items.every((item) => item.term), 'each Jisho row should keep its term for bold rendering');
  }

  const blob = [
    formatted.title,
    formatted.reading,
    ...formatted.items.flatMap((item) => [item.term, item.label, item.text]),
    ...rows,
  ]
    .filter(Boolean)
    .join('\n');

  assertIncludes(blob, testCase.expectIncludes || []);
  assertMissing(blob, testCase.rejectIncludes || []);
  assert(!/^=+=/m.test(rows.join('\n')), 'folded preview should not expose wiki section markup');
}

function summaryRows(formatted, fallbackText) {
  if (!formatted) {
    return fallbackText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).slice(0, 3);
  }

  const rows = [];
  if (formatted.title || formatted.reading) {
    rows.push([formatted.title, formatted.reading ? `[${formatted.reading}]` : ''].filter(Boolean).join(' '));
  }

  const itemLimit = rows.length ? 2 : 3;
  for (const item of formatted.items.slice(0, itemLimit)) {
    rows.push([
      item.term ? `${item.term}:` : '',
      item.label ? `${item.label}` : '',
      item.text,
    ].filter(Boolean).join(' '));
  }
  return rows;
}

function assertIncludes(blob, expectedValues) {
  for (const expected of expectedValues) {
    assert(blob.includes(expected), `missing expected text: ${expected}`);
  }
}

function assertMissing(blob, rejectedValues) {
  for (const rejected of rejectedValues) {
    assert(!blob.includes(rejected), `unexpected text: ${rejected}`);
  }
}

function assertEqual(actual, expected, label) {
  assert(actual === expected, `${label} expected "${expected}", got "${actual}"`);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}
