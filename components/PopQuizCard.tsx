import React from 'react';
import { HelpCircle, Check, Eye, Lightbulb, RefreshCw, Trash2, X, Volume2, Undo2, Dot } from 'lucide-react';
import { DictionaryEntry } from '../types';
import { playAudio } from '../services/ttsService';
import { LanguageBadge } from './LanguageBadge';
import { WordContent } from './WordContent';

type PopQuizCardProps = {
  quizCard: DictionaryEntry | null;
  quizMessage: string | null;
  quizRevealed: boolean;
  feedbackEffect: 'again' | 'hard' | 'good' | null;
  undoAvailable: boolean;
  onClose: () => void;
  onReveal: () => void;
  onRepeat: () => void;
  onHard: () => void;
  onGood: () => void;
  onRemove: () => void;
  onUndoRemove: () => void;
};

export const PopQuizCard: React.FC<PopQuizCardProps> = ({
  quizCard,
  quizMessage,
  quizRevealed,
  feedbackEffect,
  undoAvailable,
  onClose,
  onReveal,
  onRepeat,
  onHard,
  onGood,
  onRemove,
  onUndoRemove,
  dueCount,
}) => {
  if (!quizCard && !quizMessage) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center px-4 py-6">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-2xl">
        <div className="bg-white rounded-xl border border-amber-200 shadow-lg p-5 animate-fade-in-up h-[80vh] flex flex-col">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-amber-600 font-semibold">
              <Lightbulb size={18} />
              <span className="sm:block hidden">Pop Quiz</span>
            {undoAvailable && (
              <button
                onClick={onUndoRemove}
                className="flex items-center gap-2 text-slate-400 hover:text-slate-600 mr-4"
                title="Undo last action"
              >
                <Undo2 size={16} />
                <span>Undo</span>
              </button>
            )}
                {feedbackEffect === 'again' && (
                <div className="flex gap-0 items-center text-red-600 font-semibold bg-slate-100 rounded-full">
                  <Dot size={18} />
                </div>
              )}
              {feedbackEffect === 'hard' && (
                <div className="flex gap-0 items-center text-slate-700 font-semibold bg-slate-100 rounded-full">
                  <Dot size={18} />
                  <Dot size={18} />
                </div>
              )}
              {feedbackEffect === 'good' && (
                <div className="flex gap-0 items-center text-emerald-600 font-semibold bg-slate-100 rounded-full">
                  <Dot size={18} />
                  <Dot size={18} />
                  <Dot size={18} />
                </div>
              )}
            </div>
            <div className="flex items-center gap-4">
              <div className="px-2 py-0.5 inline-flex items-center justify-center text-xs font-semibold bg-slate-100 rounded-full">
              {dueCount}
              </div>
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600" title="Close quiz">
              <X size={16} />
            </button>
            </div>
          </div>

          <div className="flex-1 overflow-auto mt-3 space-y-4">
            {!quizCard && quizMessage && (
                <div className="flex h-full flex-col items-center justify-center text-center space-y-1">
                  <div className="flex items-center justify-center gap-2">
                    <Check size={32} className="text-emerald-500" />
                    <div className="text-xl font-bold text-slate-900">{quizMessage}</div>
                  </div>
                </div>
            )}

            {quizCard && (
              <>
                <div className="text-center space-y-1">
                  <div className="flex items-center justify-center gap-3 text-2xl font-bold text-slate-900">
                    <span>{quizCard.data.targetWord}</span>
                    {quizCard.data.detectedLanguage !== 'unknown' && (
                      <div className="flex items-center gap-2 text-base font-normal">
                        <button
                          onClick={() => playAudio(quizCard.data.targetWord, quizCard.data.detectedLanguage)}
                          className="p-2 rounded-full hover:bg-slate-200 text-indigo-600 transition-colors"
                          title="Play pronunciation"
                          aria-label="Play pronunciation"
                        >
                          <Volume2 size={18} />
                        </button>
                        <LanguageBadge
                          lang={quizCard.data.detectedLanguage}
                          label={quizCard.data.detectedLanguage.toUpperCase()}
                        />
                      </div>
                    )}
                  </div>
                </div>

                {quizRevealed && <WordContent entry={quizCard} withPadding={false} className="mt-4" />}
              </>
            )}
          </div>

          <div className="mt-4">
            {!quizCard ? null : !quizRevealed ? (
              <div className="grid grid-cols-8 gap-3 justify-center items-stretch">
                <button
                  onClick={onReveal}
                  className="col-span-6 px-4 py-4 rounded-md bg-amber-100 text-amber-700 text-sm font-semibold border border-amber-200 hover:bg-amber-200 transition-colors flex items-center justify-center gap-2 w-full"
                >
                  <Eye size={14} />
                </button>
                <button
                  onClick={onRemove}
                  className="col-span-2 px-4 py-4 rounded-md bg-blue-50 text-blue-600 border border-blue-100 hover:bg-blue-100 transition-colors flex items-center justify-center gap-2 min-w-[64px]"
                  title="Remove"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-8 gap-3 justify-center items-stretch">
                <button
                  onClick={onRepeat}
                  className="col-span-2 px-4 py-4 rounded-md bg-red-50 text-red-600 border border-red-100 hover:bg-red-100 transition-colors flex items-center justify-center gap-2"
                  title="Again"
                >
                  <RefreshCw size={14} />
                </button>
                <button
                  onClick={onHard}
                  className="col-span-2 px-4 py-4 rounded-md bg-slate-100 text-slate-700 border border-slate-200 hover:bg-slate-200 transition-colors flex items-center justify-center gap-2"
                  title="Hard"
                >
                  <HelpCircle size={14} />
                </button>
                <button
                  onClick={onGood}
                  className="col-span-2 px-4 py-4 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-100 hover:bg-emerald-100 transition-colors flex items-center justify-center gap-2"
                  title="Good"
                >
                  <Check size={14} />
                </button>
                <button
                  onClick={onRemove}
                  className="col-span-2 px-4 py-4 rounded-md bg-blue-50 text-blue-600 border border-blue-100 hover:bg-blue-100 transition-colors flex items-center justify-center gap-2 min-w-[64px]"
                  title="Remove"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
