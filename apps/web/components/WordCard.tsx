import React, { useState } from 'react';
import { DictionaryEntry } from '../types';
import { LanguageBadge } from './LanguageBadge';
import { Volume2, Trash2, ChevronDown, ChevronUp } from 'lucide-react';
import { playAudio } from '../services/ttsService';
import { WordContent } from './WordContent';

interface WordCardProps {
  entry: DictionaryEntry;
  isHistory?: boolean;
  onDelete?: (id: string) => void;
}

export const WordCard: React.FC<WordCardProps> = ({ entry, isHistory = false, onDelete }) => {
  const { data } = entry;
  const [isExpanded, setIsExpanded] = useState(!isHistory);

  const handlePlay = (e: React.MouseEvent, text: string, lang: string) => {
    e.stopPropagation(); // prevent card toggle
    playAudio(text, lang);
  };

  const toggleExpand = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsExpanded(!isExpanded);
  };

  return (
    <div
      className={`
        bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden 
        transition-all duration-300 hover:shadow-md
        ${isHistory ? 'w-full' : 'w-full max-w-2xl mx-auto'}
      `}
    >
      <div
        className={`bg-slate-50 p-4 border-b border-slate-100 flex justify-between items-center cursor-pointer ${!isExpanded ? 'hover:bg-slate-100' : ''}`}
        onClick={isHistory ? toggleExpand : undefined}
      >
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-3">
            {isHistory && (
              <div className="text-slate-400">
                {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
              </div>
            )}

            <h2 className={`font-bold text-slate-800 ${isHistory ? 'text-xl' : 'text-3xl'}`}>
              {data.targetWord}
            </h2>

            {data.detectedLanguage !== 'unknown' && (
              <button
                onClick={(e) => handlePlay(e, data.targetWord, data.detectedLanguage)}
                className="p-2 rounded-full hover:bg-slate-200 text-indigo-600 transition-colors"
                title="Play pronunciation"
                aria-label="Play pronunciation"
              >
                <Volume2 size={isHistory ? 18 : 24} />
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {data.detectedLanguage === 'zh' && <LanguageBadge lang="zh" label="ZH" />}
            {data.detectedLanguage === 'en' && <LanguageBadge lang="en" label="EN" />}
            {data.detectedLanguage === 'ja' && <LanguageBadge lang="ja" label="JA" />}

            {isHistory && onDelete && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(entry.id);
                }}
                className="ml-2 p-1.5 rounded-full text-slate-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                title="Remove from history"
              >
                <Trash2 size={18} />
              </button>
            )}
          </div>
        </div>
      </div>

      {isExpanded && <WordContent entry={entry} className={'animate-fade-in-up'} />}
    </div>
  );
};
