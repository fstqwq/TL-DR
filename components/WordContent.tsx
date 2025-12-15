import React from 'react';
import { Volume2, BookOpen } from 'lucide-react';
import { DictionaryEntry } from '../types';
import { playAudio } from '../services/ttsService';

type WordContentProps = {
  entry: DictionaryEntry;
  withPadding?: boolean;
  className?: string;
};

export const WordContent: React.FC<WordContentProps> = ({
  entry,
  withPadding = true,
  className = '',
}) => {
  const { data } = entry;

  const handlePlay = (e: React.MouseEvent, text: string, lang: string) => {
    e.stopPropagation();
    playAudio(text, lang);
  };

  const containerClasses = [withPadding ? 'p-5' : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={containerClasses}>
      {/* Translations & Pronunciations Grid */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {/* Chinese */}
        <div
          onClick={(e) => handlePlay(e, data.translations.zh.word, 'zh')}
          className="text-center bg-red-50/40 rounded-lg border border-red-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-red-50 hover:border-red-200"
        >
          <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-red-900 leading-tight">
            {data.translations.zh.word}
          </span>
          <span className="text-xs sm:text-sm text-slate-500 group-hover:text-red-700 font-medium">
            {data.translations.zh.pronunciation}
          </span>
        </div>

        {/* English */}
        <div
          onClick={(e) => handlePlay(e, data.translations.en.word, 'en')}
          className="text-center bg-blue-50/40 rounded-lg border border-blue-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-blue-50 hover:border-blue-200"
        >
          <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-blue-900 leading-tight">
            {data.translations.en.word}
          </span>
          <span className="text-xs sm:text-sm font-mono text-slate-500 group-hover:text-blue-700">
            {data.translations.en.pronunciation}
          </span>
        </div>

        {/* Japanese */}
        <div
          onClick={(e) => handlePlay(e, data.translations.ja.word, 'ja')}
          className="text-center bg-emerald-50/40 rounded-lg border border-emerald-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-emerald-50 hover:border-emerald-200"
        >
          <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-emerald-900 leading-tight">
            {data.translations.ja.word}
          </span>
          <span className="text-xs sm:text-sm text-slate-500 group-hover:text-emerald-700 font-medium">
            {data.translations.ja.pronunciation}
          </span>
        </div>
      </div>

      {/* Definitions List */}
      <div className="space-y-3 mb-6">
        {/* Chinese Definition */}
        <div className="flex items-start gap-3 group">
          <button
            onClick={(e) => handlePlay(e, data.definitions.zh, 'zh')}
            className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center shrink-0 text-red-600 font-bold text-xs hover:bg-red-100 transition-colors cursor-pointer"
            title="Read Chinese definition"
          >
            中
          </button>
          <p className="text-slate-700 mt-1 flex-grow text-sm sm:text-base">{data.definitions.zh}</p>
        </div>

        {/* English Definition */}
        <div className="flex items-start gap-3 group">
          <button
            onClick={(e) => handlePlay(e, data.definitions.en, 'en')}
            className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center shrink-0 text-blue-600 font-bold text-xs hover:bg-blue-100 transition-colors cursor-pointer"
            title="Read English definition"
          >
            EN
          </button>
          <p className="text-slate-700 mt-1 flex-grow text-sm sm:text-base">{data.definitions.en}</p>
        </div>

        {/* Japanese Definition */}
        <div className="flex items-start gap-3 group">
          <button
            onClick={(e) => handlePlay(e, data.definitions.ja, 'ja')}
            className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center shrink-0 text-emerald-600 font-bold text-xs hover:bg-emerald-100 transition-colors cursor-pointer"
            title="Read Japanese definition"
          >
            日
          </button>
          <p className="text-slate-700 mt-1 flex-grow text-sm sm:text-base">
            {data.origin && <span className="font-bold mr-2">{data.origin}</span>}
            {data.definitions.ja}
          </p>
        </div>
      </div>

      {((data.synonyms && data.synonyms.length > 0) || (data.antonyms && data.antonyms.length > 0)) && (
        <div className="flex flex-col sm:flex-row gap-6 px-1 pb-4">
          {/* Synonyms */}
          {data.synonyms && data.synonyms.length > 0 && (
            <div className="flex-1">
              <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider block mb-2">Synonyms</span>
              <div className="flex flex-wrap gap-2">
                {data.synonyms.map((word, idx) => (
                  <span
                    key={idx}
                    onClick={(e) => handlePlay(e, word, data.detectedLanguage)}
                    className="px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-full text-sm hover:bg-indigo-100 transition-colors cursor-pointer border border-indigo-100"
                  >
                    {word}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Antonyms */}
          {data.antonyms && data.antonyms.length > 0 && (
            <div className="flex-1">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block mb-2">Antonyms</span>
              <div className="flex flex-wrap gap-2">
                {data.antonyms.map((word, idx) => (
                  <span
                    key={idx}
                    onClick={(e) => handlePlay(e, word, data.detectedLanguage)}
                    className="px-2.5 py-1 bg-slate-100 text-slate-600 rounded-full text-sm hover:bg-slate-200 transition-colors cursor-pointer border border-slate-200"
                  >
                    {word}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Example Sentence */}
      {data.exampleSentence && (
        <div className="mt-4 pt-4 border-t border-slate-100">
          <div className="flex items-center gap-2 mb-2 text-indigo-600">
            <BookOpen size={16} />
            <span className="text-xs font-semibold uppercase tracking-wide">Example</span>
            <button
              onClick={(e) =>
                handlePlay(e, data.exampleSentence!.text, data.detectedLanguage as 'zh' | 'en' | 'ja')
              }
              className="ml-auto p-1 text-indigo-400 hover:text-indigo-600 transition-colors"
            >
              <Volume2 size={16} />
            </button>
          </div>
          <p className="text-slate-800 italic">"{data.exampleSentence.text}"</p>
          <p className="text-slate-500 text-sm mt-1">{data.exampleSentence.translation}</p>
        </div>
      )}
    </div>
  );
};
