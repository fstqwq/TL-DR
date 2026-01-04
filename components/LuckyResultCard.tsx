import React from 'react';
import { Dices, X } from 'lucide-react';
import { LuckySentenceResult } from '../types';
import { playAudio } from '../services/ttsService';

type LuckyResultCardProps = {
  isLoading: boolean;
  result: LuckySentenceResult | null;
  selectedWords: string[];
  onDismiss: () => void;
};

export const LuckyResultCard: React.FC<LuckyResultCardProps> = ({
  isLoading,
  result,
  selectedWords = [],
  onDismiss,
}) => {
  if (isLoading) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-violet-100 p-6 flex flex-col items-center justify-center animate-pulse w-full">
        <Dices size={32} className="text-violet-600 animate-spin mb-2" />
        <p className="text-violet-600 font-medium text-sm">Mixing words...</p>
        {selectedWords.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
            {selectedWords.map((word, i) => (
              <span
                key={`${word}-${i}`}
                className="px-2 py-0.5 bg-violet-50 border border-violet-100 text-violet-700 rounded-md text-xs font-medium"
              >
                {word}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (!result) return null;

  return (
    <div className="animate-fade-in-up w-full">
      <div className="bg-gradient-to-br from-indigo-50 to-violet-50 rounded-xl border border-indigo-100 p-5 shadow-sm relative overflow-hidden group hover:shadow-md transition-shadow">
        <button
          onClick={onDismiss}
          className="absolute top-3 right-3 text-slate-400 hover:text-slate-600 p-1 rounded-full hover:bg-white/50 transition-colors"
          title="Dismiss"
        >
          <X size={18} />
        </button>

        <div className="mb-4 flex flex-wrap items-center gap-2 pr-8">
          <span className="text-indigo-600 mr-1">
            <Dices size={20} />
          </span>
          {result.usedWords.map((word, i) => (
            <span
              key={i}
              className="px-2 py-0.5 bg-white/60 border border-indigo-100 text-indigo-700 rounded-md text-xs font-medium"
            >
              {word}
            </span>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div
            onClick={() => playAudio(result.content.en.text, 'en')}
            className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-blue-200 transition-all cursor-pointer"
          >
            <p className="text-slate-800 font-medium mb-1 leading-snug">
              {result.content.en.text}
            </p>
            <p className="text-slate-400 text-xs">{result.content.en.pronunciation}</p>
          </div>
          <div
            onClick={() => playAudio(result.content.zh.text, 'zh')}
            className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-red-200 transition-all cursor-pointer"
          >
            <p className="text-slate-800 font-medium mb-1 leading-snug">
              {result.content.zh.text}
            </p>
            <p className="text-slate-400 text-xs">{result.content.zh.pronunciation}</p>
          </div>
          <div
            onClick={() => playAudio(result.content.ja.text, 'ja')}
            className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-emerald-200 transition-all cursor-pointer"
          >
            <p className="text-slate-800 font-medium mb-1 leading-snug">
              {result.content.ja.text}
            </p>
            <p className="text-slate-400 text-xs">{result.content.ja.pronunciation}</p>
          </div>
        </div>
      </div>
    </div>
  );
};
