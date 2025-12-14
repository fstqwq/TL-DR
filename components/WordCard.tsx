import React, { useEffect, useRef, useState } from 'react';
import { DictionaryEntry } from '../types';
import { LanguageBadge } from './LanguageBadge';
import { Volume2, BookOpen, Trash2, ChevronDown, ChevronUp } from 'lucide-react';

interface WordCardProps {
  entry: DictionaryEntry;
  isHistory?: boolean;
  onDelete?: (id: string) => void;
}

export const WordCard: React.FC<WordCardProps> = ({ entry, isHistory = false, onDelete }) => {
  const { data } = entry;
  // If it's a history item, default to collapsed. If it's the main result, always expanded.
  const [isExpanded, setIsExpanded] = useState(!isHistory);

  const playAudio = (e: React.MouseEvent, text: string, lang: string) => {
    e.stopPropagation();
    if (!window.speechSynthesis) return;
    
    // Cancel any current speaking
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    
    // Map internal codes to BCP 47 language tags
    const langMap: Record<string, string> = {
      zh: 'zh-CN',
      en: 'en-US',
      ja: 'ja-JP'
    };
    
    utterance.lang = langMap[lang] || 'en-US';
    window.speechSynthesis.speak(utterance);
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
      {/* Header Section - Always Visible */}
      <div 
        className={`bg-slate-50 p-4 border-b border-slate-100 flex justify-between items-center cursor-pointer ${!isExpanded ? 'hover:bg-slate-100' : ''}`}
        onClick={isHistory ? toggleExpand : undefined}
      >
        <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-3">
              {/* Expand/Collapse Chevron for History items */}
              {isHistory && (
                <div className="text-slate-400">
                  {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                </div>
              )}

              <h2 className={`font-bold text-slate-800 ${isHistory ? 'text-xl' : 'text-3xl'}`}>
                {data.targetWord}
              </h2>
              
              {/* Main Play Button for detected language */}
              {data.detectedLanguage !== 'unknown' && (
                <button 
                  onClick={(e) => playAudio(e, data.targetWord, data.detectedLanguage)}
                  className="p-2 rounded-full hover:bg-slate-200 text-indigo-600 transition-colors"
                  title="Play pronunciation"
                  aria-label="Play pronunciation"
                >
                  <Volume2 size={isHistory ? 18 : 24} />
                </button>
              )}
            </div>
            
            <div className="flex items-center gap-2">
              {data.detectedLanguage === 'zh' && <LanguageBadge lang="zh" label="Chinese" />}
              {data.detectedLanguage === 'en' && <LanguageBadge lang="en" label="English" />}
              {data.detectedLanguage === 'ja' && <LanguageBadge lang="ja" label="Japanese" />}
              
              {/* Delete Button (Only for History) */}
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

      {/* Content Section - Conditionally Visible */}
      {isExpanded && (
        <div className={`p-5 animate-fade-in-up`}>
          
          {/* Translations & Pronunciations Grid */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            {/* Chinese */}
            <div 
              onClick={(e) => playAudio(e, data.translations.zh.word, 'zh')}
              className="text-center bg-red-50/40 rounded-lg border border-red-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-red-50 hover:border-red-200"
            >
              {/* <span className="text-[10px] sm:text-xs text-slate-400 group-hover:text-red-400 uppercase tracking-wider mb-1">Chinese</span> */}
              <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-red-900 leading-tight">{data.translations.zh.word}</span>
              <span className="text-xs sm:text-sm text-slate-500 group-hover:text-red-700 font-medium">{data.translations.zh.pronunciation}</span>
            </div>

            {/* English */}
            <div 
              onClick={(e) => playAudio(e, data.translations.en.word, 'en')}
              className="text-center bg-blue-50/40 rounded-lg border border-blue-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-blue-50 hover:border-blue-200"
            >
              {/* <span className="text-[10px] sm:text-xs text-slate-400 group-hover:text-blue-400 uppercase tracking-wider mb-1">English</span> */}
              <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-blue-900 leading-tight">{data.translations.en.word}</span>
              <span className="text-xs sm:text-sm font-mono text-slate-500 group-hover:text-blue-700">{data.translations.en.pronunciation}</span>
            </div>

            {/* Japanese */}
            <div 
              onClick={(e) => playAudio(e, data.translations.ja.word, 'ja')}
              className="text-center bg-emerald-50/40 rounded-lg border border-emerald-100 transition-colors cursor-pointer group flex flex-col items-center justify-center min-h-[90px] hover:bg-emerald-50 hover:border-emerald-200"
            >
              {/* <span className="text-[10px] sm:text-xs text-slate-400 group-hover:text-emerald-400 uppercase tracking-wider mb-1">Japanese</span> */}
              <span className="text-lg sm:text-xl font-bold text-slate-800 group-hover:text-emerald-900 leading-tight">{data.translations.ja.word}</span>
              <span className="text-xs sm:text-sm text-slate-500 group-hover:text-emerald-700 font-medium">{data.translations.ja.pronunciation}</span>
            </div>
          </div>

          {/* Definitions List */}
          <div className="space-y-3 mb-6">
            {/* Chinese Definition */}
            <div className="flex items-start gap-3 group">
              <button 
                onClick={(e) => playAudio(e, data.definitions.zh, 'zh')}
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
                onClick={(e) => playAudio(e, data.definitions.en, 'en')}
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
                onClick={(e) => playAudio(e, data.definitions.ja, 'ja')}
                className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center shrink-0 text-emerald-600 font-bold text-xs hover:bg-emerald-100 transition-colors cursor-pointer"
                title="Read Japanese definition"
              >
                日
              </button>
              <p className="text-slate-700 mt-1 flex-grow text-sm sm:text-base">
                {/* Show origin word if it exists (e.g. for Loanwords) */}
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
                        onClick={(e) => playAudio(e, word, data.detectedLanguage)}
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
                        onClick={(e) => playAudio(e, word, data.detectedLanguage)}
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
                    onClick={(e) => playAudio(e, data.exampleSentence!.text, data.detectedLanguage as 'zh'|'en'|'ja')}
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
      )}
    </div>
  );
};
