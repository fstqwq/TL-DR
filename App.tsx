import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Search, History, Sparkles, Settings2, Dices, X, HelpCircle, CornerDownLeft, Lightbulb } from 'lucide-react';
import { lookupWord, generateSentence, setRuntimeConfig } from './services/llmService';
import { playAudio } from './services/ttsService';
import { DictionaryEntry, LuckySentenceResult, WordContext, AppConfig } from './types';
import { WordCard } from './components/WordCard';
import { Spinner } from './components/Spinner';
import { LuckyResultCard } from './components/LuckyResultCard';
import { PopQuizCard } from './components/PopQuizCard';

type PreferredLanguage = 'auto' | 'zh' | 'en' | 'ja';
type AppProps = { config: AppConfig };

const MAX_HISTORY = 42;
const DEFAULT_EASE = 2.5;
const MIN_EASE = 1.3;
const AGAIN_INTERVAL = 1000; // 1 second
const HARD_MIN_INTERVAL = 3 * 60 * 1000; // 3 minutes
const GOOD_NEW_INTERVAL = 30 * 60 * 1000; // 30 minutes

// Default fallback models in case config is broken
const DEFAULT_MODELS = [
    { "id": "Qwen/Qwen3-Next-80B-A3B-Instruct", "name": "Qwen3 Next 80BA3B Instruct" },
    { "id": "Qwen/Qwen3-Next-80B-A3B-Thinking", "name": "Qwen3 Next 80BA3B Thinking" },
    { "id": "meta-llama/Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B (FP8)" },
    { "id": "openai/gpt-oss-120b", "name": "GPT OSS 120B" },
    { "id": "openai/gpt-oss-20b", "name": "GPT OSS 20B" },
    { "id": "meta-llama/Meta-Llama-3.1-8B-Instruct", "name": "Llama 3.1 8B (FP8)" },
    { "id": "Qwen/Qwen3-235B-A22B", "name": "Qwen 3 235B A22B (FP8)" },
    { "id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3 (FP8)" }
];

// Load models from Runtime Config
function App({ config }: AppProps) {
  const models = useMemo(
    () => (config.MODELS && config.MODELS.length > 0 ? config.MODELS : DEFAULT_MODELS),
    [config]
  );
  const [query, setQuery] = useState('');
  const [preferredLang, setPreferredLang] = useState<PreferredLanguage>('auto');
  
  // Initialize models from local storage, but validate against the current CONFIG
  // If the stored model ID no longer exists in config, fall back to the first available model.
  const [searchModel, setSearchModel] = useState<string>(() => {
    const stored = localStorage.getItem('search_model');
    const exists = models.find(m => m.id === stored);
    return exists ? stored! : models[0].id;
  });

  const [luckyModel, setLuckyModel] = useState<string>(() => {
    const stored = localStorage.getItem('lucky_model');
    const exists = models.find(m => m.id === stored);
    return exists ? stored! : models[0].id;
  });
  
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isLuckyLoading, setIsLuckyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // App state
  const [currentResult, setCurrentResult] = useState<DictionaryEntry | null>(null);
  const [luckyResult, setLuckyResult] = useState<LuckySentenceResult | null>(null);
  const [quizCard, setQuizCard] = useState<DictionaryEntry | null>(null);
  const [quizRevealed, setQuizRevealed] = useState(false);
  const [quizMessage, setQuizMessage] = useState<string | null>(null);
  const [dueCount, setDueCount] = useState(0);
  const [quizFeedback, setQuizFeedback] = useState<'again' | 'hard' | 'good' | null>(null);
  const feedbackTimerRef = useRef<number | null>(null);
  const [undoHistory, setUndoHistory] = useState<DictionaryEntry[] | null>(null);

  const ensureScheduling = (entry: DictionaryEntry): DictionaryEntry => ({
    ...entry,
    nextReview: entry.nextReview ?? 0,
    interval: entry.interval ?? 0,
    ease: entry.ease ?? DEFAULT_EASE,
    reps: entry.reps ?? 0,
  });

  const calculateDueCount = (list: DictionaryEntry[]) => {
    const now = Date.now();
    return list
      .map(ensureScheduling)
      .filter(item => (item.nextReview ?? 0) <= now).length;
  };

  const refreshDueCount = (list: DictionaryEntry[]) => {
    setDueCount(calculateDueCount(list));
  };

  const updateHistoryWithUndo = useCallback((updater: (prev: DictionaryEntry[]) => DictionaryEntry[]) => {
    setHistory(prev => {
      setUndoHistory(prev);
      return updater(prev);
    });
  }, []);

  const setFeedback = (type: 'again' | 'hard' | 'good' | null) => {
    if (feedbackTimerRef.current) {
      window.clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = null;
    }
    setQuizFeedback(type);
    if (type) {
      feedbackTimerRef.current = window.setTimeout(() => {
        setQuizFeedback(null);
        feedbackTimerRef.current = null;
      }, 3000);
    }
  };

  // Load history from local storage using Lazy Initialization
  const [history, setHistory] = useState<DictionaryEntry[]>(() => {
    if (typeof window === 'undefined') return [];
    
    const savedHistory = localStorage.getItem('dictionary_history');
    if (savedHistory) {
      try {
        const parsed = JSON.parse(savedHistory);
        
        // Validate new data structure
        if (Array.isArray(parsed) && parsed.length > 0) {
            for (const item of parsed) {
              if (
                !item.data || 
                !item.data.translations || 
                !item.data.translations.en || 
                !item.data.translations.zh || 
                !item.data.translations.ja
              ) {
                console.log("Old or invalid history format detected. Filtering it out.");
                // Instead of returning [], we can filter the array to remove invalid items.
                // Let's restructure this to use filter.
                return parsed.filter((item: any) => 
                  item.data && 
                  item.data.translations && 
                  item.data.translations.en && 
                  item.data.translations.zh && 
                  item.data.translations.ja
                );
              }
            }
          return parsed as DictionaryEntry[];
        }
      } catch (e) {
        console.error("Failed to parse history", e);
        return [];
      }
    }
    return [];
  });

  // Save history whenever it changes
  useEffect(() => {
    localStorage.setItem('dictionary_history', JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    refreshDueCount(history);
  }, [history]);

  // Save model preferences
  useEffect(() => {
    localStorage.setItem('search_model', searchModel);
    localStorage.setItem('lucky_model', luckyModel);
  }, [searchModel, luckyModel]);

  // Provide runtime config to llmService (backend URL, etc.)
  useEffect(() => {
    setRuntimeConfig(config);
  }, [config]);

  useEffect(() => {
    return () => {
      if (feedbackTimerRef.current) {
        window.clearTimeout(feedbackTimerRef.current);
      }
    };
  }, []);

  // Click outside to close settings
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (settingsRef.current && !settingsRef.current.contains(event.target as Node)) {
        setIsSettingsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const handleSearch = useCallback(async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    setError(null);
    setCurrentResult(null);

    try {
      // Use searchModel here
      const data = await lookupWord(query, preferredLang, searchModel);
      
      const newEntry: DictionaryEntry = {
        id: query.trim().toLowerCase() + '_' + Date.now(), // for http deployment
        timestamp: Date.now(),
        query: query.trim(),
        data: data,
        nextReview: Date.now(),
        interval: 0,
        ease: DEFAULT_EASE,
        reps: 0
      };

      setCurrentResult(newEntry);
      
      // Add to history (prevent duplicates based on the targetWord)
      setHistory(prev => {
        const filtered = prev.filter(item => item.data.targetWord.toLowerCase() !== data.targetWord.toLowerCase());
        return [newEntry, ...filtered].slice(0, MAX_HISTORY); // Keep max items defined by MAX_HISTORY
      });

    } catch (err: any) {
      setError(err.message || "Failed to look up the word. Please check your connection or API key.");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, [query, preferredLang, searchModel]);

  const handleLucky = async () => {
    if (history.length < 2) {
      setError("Search for at least 2 words to use 'I'm Feeling Lucky'!");
      setTimeout(() => setError(null), 3000);
      return;
    }

    setIsLuckyLoading(true);
    setError(null);
    setLuckyResult(null);
    // REMOVED: setCurrentResult(null); We now keep the current result visible.

    try {
      // Shuffle history and pick 2-4 random words
      const shuffled = [...history].sort(() => 0.5 - Math.random());
      const selectedEntries = shuffled.slice(0, Math.min(4, Math.max(2, history.length)));
      
      // Map to structured WordContext objects
      const words: WordContext[] = selectedEntries.map(e => ({
        word: e.data.targetWord,
        lang: e.data.detectedLanguage
      }));

      // Use luckyModel here
      const result = await generateSentence(words, luckyModel);
      setLuckyResult(result);
    } catch (err: any) {
      setError(err.message || "Failed to generate sentence.");
    } finally {
      setIsLuckyLoading(false);
    }
  };

  const startQuiz = () => {
    if (history.length === 0) {
      setError("Add some history first, then try pop quiz!");
      setTimeout(() => setError(null), 2000);
      return;
    }
    setFeedback(null);
    setUndoHistory(null);
    setQuizRevealed(false);
    setQuizMessage(null);
    refreshDueCount(history);
    selectNextQuizCard(history);
  };

  const selectNextQuizCard = (list: DictionaryEntry[]) => {
    refreshDueCount(list);
    if (list.length === 0) {
      setQuizCard(null);
      setQuizMessage("Pop quiz complete for now.");
      return;
    }
    const now = Date.now();
    const normalized = list.map(ensureScheduling);
    const sorted = [...normalized].sort(
      (a, b) => (a.nextReview ?? 0) - (b.nextReview ?? 0)
    );
    const due = sorted.find(entry => (entry.nextReview ?? 0) <= now);
    if (due) {
      setQuizCard(due);
      setQuizRevealed(false);
      setQuizMessage(null);
    } else {
      setQuizCard(null);
      setQuizMessage("Pop quiz complete for now.");
    }
  };

  const handleQuizRepeat = () => {
    if (!quizCard) return;
    const now = Date.now();
    setFeedback('again');
    updateHistoryWithUndo(prev => {
      const updated = prev.map(item => {
        if (item.id !== quizCard.id) return item;
        const ensured = ensureScheduling(item);
        const newEase = Math.max(MIN_EASE, (ensured.ease ?? DEFAULT_EASE) - 0.2);
        return {
          ...ensured,
          ease: newEase,
          interval: AGAIN_INTERVAL,
          nextReview: now + AGAIN_INTERVAL,
          reps: 0,
        };
      });
      selectNextQuizCard(updated);
      return updated;
    });
  };

  const handleQuizHard = () => {
    if (!quizCard) return;
    const now = Date.now();
    setFeedback('hard');
    updateHistoryWithUndo(prev => {
      const updated = prev.map(item => {
        if (item.id !== quizCard.id) return item;
        const ensured = ensureScheduling(item);
        const baseInterval = ensured.interval ?? 0;
        const nextInterval = Math.max(HARD_MIN_INTERVAL, Math.round(baseInterval * 1.2));
        const newEase = Math.max(MIN_EASE, (ensured.ease ?? DEFAULT_EASE) - 0.15);
        return {
          ...ensured,
          ease: newEase,
          interval: nextInterval,
          nextReview: now + nextInterval,
        };
      });
      selectNextQuizCard(updated);
      return updated;
    });
  };

  const handleQuizGood = () => {
    if (!quizCard) return;
    const now = Date.now();
    setFeedback('good');
    updateHistoryWithUndo(prev => {
      const updated = prev.map(item => {
        if (item.id !== quizCard.id) return item;
        const ensured = ensureScheduling(item);
        const ease = ensured.ease ?? DEFAULT_EASE;
        const baseInterval = ensured.interval ?? 0;
        const nextInterval = baseInterval === 0
          ? GOOD_NEW_INTERVAL
          : Math.max(HARD_MIN_INTERVAL, Math.round(baseInterval * ease));
        return {
          ...ensured,
          interval: nextInterval,
          nextReview: now + nextInterval,
          reps: (ensured.reps ?? 0) + 1,
        };
      });
      selectNextQuizCard(updated);
      return updated;
    });
  };

  const handleQuizRemove = () => {
    if (!quizCard) return;
    setFeedback(null);
    setQuizRevealed(false);
    updateHistoryWithUndo(prev => {
      const updated = prev.filter(item => item.id !== quizCard.id);
      selectNextQuizCard(updated);
      return updated;
    });
  };

  const handleUndoRemove = () => {
    if (!undoHistory) return;
    setFeedback(null);
    setQuizRevealed(false);
    setQuizMessage(null);
    setHistory(undoHistory);
    selectNextQuizCard(undoHistory);
    setUndoHistory(null);
  };

  const handleQuizReveal = () => {
    if (!quizCard) return;
    if (!quizRevealed) {
      const lang = quizCard.data.detectedLanguage !== 'unknown' ? quizCard.data.detectedLanguage : 'en';
      playAudio(quizCard.data.targetWord, lang);
    }
    setQuizRevealed(true);
  };

  const handleDeleteHistory = (id: string) => {
    setHistory(prev => prev.filter(item => item.id !== id));
  };

  // Determine styles for the history counter
  const getCounterStyles = () => {
    const count = history.length;
    if (count >= MAX_HISTORY) {
      return {
        container: "bg-red-50 text-red-600 border-red-200",
        icon: "text-red-400 hover:text-red-600"
      };
    }
    if (count >= MAX_HISTORY - 5) {
      return {
        container: "bg-yellow-50 text-yellow-700 border-yellow-200",
        icon: "text-yellow-500 hover:text-yellow-700"
      };
    }
    return {
      container: "bg-slate-100 text-slate-500 border-slate-200",
      icon: "text-slate-400 hover:text-slate-600"
    };
  };

  const counterStyles = getCounterStyles();

  const langOptions: { id: PreferredLanguage; label: React.ReactNode; title: string; baseClass: string; activeClass: string }[] = [
    { 
      id: 'auto', 
      label: <Sparkles size={18} />, 
      title: 'Auto Detect',
      baseClass: 'bg-slate-100 text-slate-500 hover:bg-slate-200',
      activeClass: 'bg-slate-800 text-white shadow-lg scale-110'
    },
    { 
      id: 'zh', 
      label: '中', 
      title: 'Chinese',
      baseClass: 'bg-red-50 text-red-600 hover:bg-red-100',
      activeClass: 'bg-red-600 text-white shadow-lg scale-110'
    },
    { 
      id: 'en', 
      label: 'EN', 
      title: 'English',
      baseClass: 'bg-blue-50 text-blue-600 hover:bg-blue-100',
      activeClass: 'bg-blue-600 text-white shadow-lg scale-110'
    },
    { 
      id: 'ja', 
      label: '日', 
      title: 'Japanese',
      baseClass: 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100',
      activeClass: 'bg-emerald-600 text-white shadow-lg scale-110'
    },
  ];

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 pb-20">
      
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="Logo" className="w-8 h-8 hover:rotate-6 transition-transform cursor-pointer" />
            <h1 className="text-xl font-bold tracking-tight text-indigo-600 hidden sm:block">Tri-Lingual Dictionary Remastered</h1>
            <h1 className="text-xl font-bold tracking-tight text-indigo-600 sm:hidden">TL;DR</h1>
          </div>
          
          <div className="flex items-center gap-3 relative" ref={settingsRef}>
             {/* Settings Menu Toggle */}
             <button 
                onClick={() => setIsSettingsOpen(!isSettingsOpen)}
                className={`
                  flex items-center gap-2 px-3 py-2 rounded-lg transition-all
                  ${isSettingsOpen ? 'bg-indigo-50 text-indigo-700 ring-2 ring-indigo-200' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}
                `}
                title="Model Settings"
             >
                <Settings2 size={18} />
                <span className="text-sm font-medium hidden sm:inline">Settings</span>
             </button>

             {/* Settings Dropdown Panel */}
             {isSettingsOpen && (
               <div className="absolute right-0 top-full mt-3 w-72 bg-white rounded-xl shadow-xl border border-slate-200 p-5 z-50 animate-fade-in-up">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="font-bold text-slate-800">Model Configuration</h3>
                    <button onClick={() => setIsSettingsOpen(false)} className="text-slate-400 hover:text-slate-600">
                      <X size={16} />
                    </button>
                  </div>

                  {/* Search Model Setting */}
                  <div className="mb-5">
                    <div className="flex items-center gap-2 mb-2 text-slate-700">
                      <Search size={16} />
                      <label className="text-sm font-semibold">Dictionary Search</label>
                    </div>
                    <div className="relative">
                      <select 
                        value={searchModel}
                        onChange={(e) => setSearchModel(e.target.value)}
                        className="w-full appearance-none bg-slate-50 border border-slate-200 text-slate-700 text-sm rounded-lg p-2.5 focus:ring-indigo-500 focus:border-indigo-500 block"
                      >
                        {models.map(model => (
                          <option key={model.id} value={model.id}>{model.name}</option>
                        ))}
                      </select>
                      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                      </div>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">Faster models recommended.</p>
                  </div>

                  {/* Lucky Model Setting */}
                  <div>
                    <div className="flex items-center gap-2 mb-2 text-violet-700">
                      <Dices size={16} />
                      <label className="text-sm font-semibold">I'm Feeling Lucky</label>
                    </div>
                    <div className="relative">
                      <select 
                        value={luckyModel}
                        onChange={(e) => setLuckyModel(e.target.value)}
                        className="w-full appearance-none bg-violet-50 border border-violet-100 text-violet-900 text-sm rounded-lg p-2.5 focus:ring-violet-500 focus:border-violet-500 block"
                      >
                         {models.map(model => (
                          <option key={model.id} value={model.id}>{model.name}</option>
                        ))}
                      </select>
                      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-violet-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                      </div>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">Thinking models recommended for creativity - at the cost of speed.</p>
                  </div>
               </div>
             )}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-10">
        
        {/* Search Section */}
        <section className="flex flex-col items-center justify-center space-y-6">
          <div className="w-full max-w-xl">
            {/* Language Selectors */}
            <div className="flex justify-center gap-4 mb-6">
              {langOptions.map((lang) => (
                <button
                  key={lang.id}
                  onClick={() => setPreferredLang(lang.id)}
                  type="button"
                  title={lang.title}
                  className={`
                    w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300
                    ${preferredLang === lang.id ? lang.activeClass : lang.baseClass}
                  `}
                >
                  {lang.label}
                </button>
              ))}
            </div>

            <form onSubmit={handleSearch} className="relative group">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Apple/苹果/林檎/リンゴ..."
                className="w-full pl-12 pr-4 py-4 rounded-full bg-white border-2 border-slate-300 text-gray-900 placeholder:text-slate-500 shadow-sm focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 focus:scale-[1.02] focus:shadow-md outline-none text-lg transition-all duration-300 ease-out"
              />
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-indigo-500 transition-colors" size={24} />
              <button 
                type="submit"
                disabled={isLoading || !query.trim()}
                className="absolute right-2 top-2 bottom-2 bg-indigo-600 text-white px-6 rounded-full font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {isLoading ? '...' : <CornerDownLeft size={18} />}
              </button>
            </form>
          </div>

          {error && (
             <div className="p-4 bg-red-50 text-red-700 rounded-lg border border-red-200">
               {error}
             </div>
          )}
        </section>

        {/* Current Result (Always Visible) */}
        <section>
          {isLoading && <Spinner />}
          {!isLoading && currentResult && (
            <div className="animate-fade-in-up">
              <WordCard entry={currentResult} />
            </div>
          )}
        </section>

        {/* History Section */}
        {history.length > 0 && (
          <section className="pt-8 border-t border-slate-200">
            <div className="flex flex-row items-center justify-between gap-4 mb-6">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <History className="text-slate-400" />
                  <h3 className="text-xl font-bold text-slate-800 hidden sm:block">History</h3>
                </div>
                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${counterStyles.container}`}>
                  <span>{history.length} / {MAX_HISTORY}</span>
                  <div className="group relative flex items-center">
                    <HelpCircle size={14} className={`cursor-help transition-colors ${counterStyles.icon}`} />
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-slate-800 text-white text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none text-center z-10">
                      The earliest words will be removed when the limit is reached.
                      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800"></div>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex items-center gap-2">
                <div className="relative">
                  <button
                    onClick={startQuiz}
                    disabled={history.length === 0}
                    className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-full text-sm font-bold shadow-sm hover:shadow-md hover:scale-105 transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    <Lightbulb size={24} />
                    <span className="sm:block hidden">Pop Quiz</span>
                  </button>
                </div>

                {/* Lucky Button */}
                {history.length >= 2 && (
                  <button
                    onClick={handleLucky}
                    disabled={isLuckyLoading}
                    className="group flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-full text-sm font-bold shadow-sm hover:shadow-md hover:scale-105 transition-all active:scale-95 disabled:opacity-70 disabled:cursor-wait"
                  >
                    <Dices size={24} className="transition-transform duration-500 group-hover:rotate-180" />
                    <span className="sm:block hidden">I'm Feeling Lucky</span>
                  </button>
                )}
              </div>
            </div>
            
            <div className="space-y-3 max-w-3xl mx-auto">
              <LuckyResultCard
                isLoading={isLuckyLoading}
                result={luckyResult}
                onDismiss={() => setLuckyResult(null)}
              />

              <PopQuizCard
                quizCard={quizCard}
                quizMessage={quizMessage}
                quizRevealed={quizRevealed}
                feedbackEffect={quizFeedback}
                undoAvailable={!!undoHistory}
                onClose={() => {
                  setQuizCard(null);
                  setQuizMessage(null);
                }}
                onReveal={handleQuizReveal}
                onRepeat={handleQuizRepeat}
                onHard={handleQuizHard}
                onGood={handleQuizGood}
                onRemove={handleQuizRemove}
                onUndoRemove={handleUndoRemove}
                dueCount={dueCount}
              />

              {/* Standard History Items */}
              {history.map((entry) => (
                <div key={entry.id}>
                  <WordCard 
                    entry={entry} 
                    isHistory={true} 
                    onDelete={handleDeleteHistory}
                  />
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
      <footer className="py-8 text-center text-slate-400 text-sm">
        <div>
          Built by fstqwq and, mostly, Gemini 3 Pro.
        </div>
        <div className="mt-2">
          <a 
            href="https://github.com/fstqwq/TL-DR" 
            target="_blank" 
            rel="noopener noreferrer"
            className="text-indigo-500 font-medium inline-flex items-center gap-1.5 group relative"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-github"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></svg>
            Star me on GitHub
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 w-56 p-2 bg-slate-800 text-white text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none text-center z-10 font-normal no-underline">
              いいねくれぇ！！
              いいねくれぇ！！
              <img src="/bocchi.png" alt="Bocchi" className="mx-auto" />
              <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800"></div>
            </div>
          </a>
        </div>
      </footer>
    </div>
  );
}

export default App;
