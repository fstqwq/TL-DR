export const playAudio = (text: string, lang: string) => {
  if (typeof window === 'undefined' || !window.speechSynthesis) return;

  // Cancel any current speaking
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);

  // Map internal codes to BCP 47 language tags
  const langMap: Record<string, string> = {
    zh: 'zh-CN',
    en: 'en-US',
    ja: 'ja-JP',
  };

  utterance.lang = langMap[lang] || 'en-US';
  window.speechSynthesis.speak(utterance);
};
