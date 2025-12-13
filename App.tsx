import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, History, Sparkles, Settings2, Dices, X, Check, HelpCircle } from 'lucide-react';
import { lookupWord, generateSentence } from './services/llmService';
import { DictionaryEntry, LuckySentenceResult, WordContext } from './types';
import { WordCard } from './components/WordCard';
import { Spinner } from './components/Spinner';

type PreferredLanguage = 'auto' | 'zh' | 'en' | 'ja';

const MAX_HISTORY = 42;

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
const MODELS = (window.APP_CONFIG?.MODELS && window.APP_CONFIG.MODELS.length > 0)
  ? window.APP_CONFIG.MODELS
  : DEFAULT_MODELS;

function App() {
  const [query, setQuery] = useState('');
  const [preferredLang, setPreferredLang] = useState<PreferredLanguage>('auto');
  
  // Initialize models from local storage, but validate against the current CONFIG
  // If the stored model ID no longer exists in config, fall back to the first available model.
  const [searchModel, setSearchModel] = useState<string>(() => {
    const stored = localStorage.getItem('search_model');
    const exists = MODELS.find(m => m.id === stored);
    return exists ? stored! : MODELS[0].id;
  });

  const [luckyModel, setLuckyModel] = useState<string>(() => {
    const stored = localStorage.getItem('lucky_model');
    const exists = MODELS.find(m => m.id === stored);
    return exists ? stored! : MODELS[0].id;
  });
  
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isLuckyLoading, setIsLuckyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // App state
  const [currentResult, setCurrentResult] = useState<DictionaryEntry | null>(null);
  const [luckyResult, setLuckyResult] = useState<LuckySentenceResult | null>(null);

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

  // Save model preferences
  useEffect(() => {
    localStorage.setItem('search_model', searchModel);
    localStorage.setItem('lucky_model', luckyModel);
  }, [searchModel, luckyModel]);

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
    setLuckyResult(null); // Clear lucky result when searching

    try {
      // Use searchModel here
      const data = await lookupWord(query, preferredLang, searchModel);
      
      const newEntry: DictionaryEntry = {
        id: query.trim().toLowerCase() + '_' + Date.now(), // for http deployment
        timestamp: Date.now(),
        query: query.trim(),
        data: data
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
      setError("Search for at least 2 words to use 'I'm feeling lucky'!");
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

  const handleDeleteHistory = (id: string) => {
    setHistory(prev => prev.filter(item => item.id !== id));
  };

  const playAudio = (text: string, lang: string) => {
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
                        {MODELS.map(model => (
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
                         {MODELS.map(model => (
                          <option key={model.id} value={model.id}>{model.name}</option>
                        ))}
                      </select>
                      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-violet-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                      </div>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">Thinking models recommended for creativity -- at the cost of speed.</p>
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
                {isLoading ? '...' : 'Go'}
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
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-6">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <History className="text-slate-400" />
                  <h3 className="text-xl font-bold text-slate-800">History</h3>
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
              
              {/* Lucky Button */}
              {history.length >= 2 && (
                <button
                  onClick={handleLucky}
                  disabled={isLuckyLoading}
                  className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-full text-sm font-bold shadow-sm hover:shadow-md hover:scale-105 transition-all active:scale-95 disabled:opacity-70 disabled:cursor-wait"
                >
                  <Dices size={18} />
                  <span>I'm feeling lucky</span>
                </button>
              )}
            </div>
            
            <div className="space-y-3 max-w-3xl mx-auto">
              
              {/* Sticky Loading State for Lucky Mode */}
              {isLuckyLoading && (
                 <div className="bg-white rounded-xl shadow-sm border border-violet-100 p-6 flex flex-col items-center justify-center animate-pulse w-full">
                    <Dices size={32} className="text-violet-600 animate-spin mb-2" />
                    <p className="text-violet-600 font-medium text-sm">Mixing words...</p>
                 </div>
              )}

              {/* Lucky Result - Displayed as top item in history stream */}
              {!isLuckyLoading && luckyResult && (
                <div className="animate-fade-in-up w-full">
                  <div className="bg-gradient-to-br from-indigo-50 to-violet-50 rounded-xl border border-indigo-100 p-5 shadow-sm relative overflow-hidden group hover:shadow-md transition-shadow">
                    <button 
                      onClick={() => setLuckyResult(null)} 
                      className="absolute top-3 right-3 text-slate-400 hover:text-slate-600 p-1 rounded-full hover:bg-white/50 transition-colors"
                      title="Dismiss"
                    >
                      <X size={18} />
                    </button>

                    <div className="mb-4 flex flex-wrap items-center gap-2 pr-8">
                        <span className="text-indigo-600 mr-1">
                           <Dices size={20} />
                        </span>
                        {luckyResult.usedWords.map((word, i) => (
                          <span key={i} className="px-2 py-0.5 bg-white/60 border border-indigo-100 text-indigo-700 rounded-md text-xs font-medium">
                            {word}
                          </span>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div 
                          onClick={() => playAudio(luckyResult.content.en.text, 'en')}
                          className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-blue-200 transition-all cursor-pointer"
                        >
                          <p className="text-slate-800 font-medium mb-1 leading-snug">{luckyResult.content.en.text}</p>
                          <p className="text-slate-400 text-xs">{luckyResult.content.en.pronunciation}</p>
                        </div>
                        <div 
                          onClick={() => playAudio(luckyResult.content.zh.text, 'zh')}
                          className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-red-200 transition-all cursor-pointer"
                        >
                          <p className="text-slate-800 font-medium mb-1 leading-snug">{luckyResult.content.zh.text}</p>
                          <p className="text-slate-400 text-xs">{luckyResult.content.zh.pronunciation}</p>
                        </div>
                        <div 
                          onClick={() => playAudio(luckyResult.content.ja.text, 'ja')}
                          className="bg-white/80 p-3 rounded-lg border border-indigo-50 hover:bg-white hover:border-emerald-200 transition-all cursor-pointer"
                        >
                          <p className="text-slate-800 font-medium mb-1 leading-snug">{luckyResult.content.ja.text}</p>
                          <p className="text-slate-400 text-xs">{luckyResult.content.ja.pronunciation}</p>
                        </div>
                    </div>
                  </div>
                </div>
              )}

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
        Built by fstqwq and, mostly, Gemini 3 Pro.
      </footer>
    </div>
  );
}

export default App;