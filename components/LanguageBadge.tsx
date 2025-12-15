import React from 'react';

interface LanguageBadgeProps {
  lang: 'zh' | 'en' | 'ja'
  label: string;
}

const colors = {
  zh: 'bg-red-100 text-red-800 border-red-200',
  en: 'bg-blue-100 text-blue-800 border-blue-200',
  ja: 'bg-emerald-100 text-emerald-800 border-emerald-200',
};

export const LanguageBadge: React.FC<LanguageBadgeProps> = ({ lang, label }) => {
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${colors[lang]}`}>
      {label}
    </span>
  );
};
