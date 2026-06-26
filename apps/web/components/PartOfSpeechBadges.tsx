import React from 'react';

type PartOfSpeechBadgesProps = {
  partsOfSpeech?: string[];
  className?: string;
};

const ALLOWED_PARTS_OF_SPEECH = new Set([
  'noun',
  'proper noun',
  'verb',
  'adjective',
  'adverb',
  'pronoun',
  'preposition',
  'conjunction',
  'interjection',
  'particle',
  'determiner',
  'numeral',
  'counter',
  'prefix',
  'suffix',
  'phrase',
  'proverb',
  'expression',
]);

export const PartOfSpeechBadges: React.FC<PartOfSpeechBadgesProps> = ({
  partsOfSpeech,
  className = '',
}) => {
  const seen = new Set<string>();
  const labels = Array.isArray(partsOfSpeech)
    ? partsOfSpeech.flatMap((label) => {
        if (typeof label !== 'string') return [];
        const normalized = label.trim().toLowerCase().replace(/\s+/g, ' ');
        if (!ALLOWED_PARTS_OF_SPEECH.has(normalized) || seen.has(normalized)) return [];
        seen.add(normalized);
        return [normalized];
      })
    : [];

  if (!labels.length) return null;

  return (
    <div className={['flex flex-wrap items-center gap-1.5', className].filter(Boolean).join(' ')}>
      {labels.map((label) => (
        <span
          key={label}
          className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs font-semibold lowercase tracking-wide text-slate-500"
        >
          {label}
        </span>
      ))}
    </div>
  );
};
