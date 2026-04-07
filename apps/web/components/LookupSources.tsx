import React from 'react';
import { ExternalLink, Globe } from 'lucide-react';
import { LookupSource } from '../types';

type LookupSourcesProps = {
  sources: LookupSource[];
  title?: string;
  className?: string;
};

export const LookupSources: React.FC<LookupSourcesProps> = ({
  sources,
  title = 'Source Text',
  className = '',
}) => {
  if (!sources.length) return null;

  return (
    <div className={className}>
      <div className="mb-3 flex items-center gap-2 text-slate-700">
        <Globe size={16} />
        <h3 className="text-xs font-semibold uppercase tracking-wide">{title}</h3>
      </div>
      <div className="space-y-3">
        {sources.map((source) => (
          <details
            key={source.id}
            className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70"
          >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-800">{source.name}</span>
                </div>
                {source.preview && (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">{source.preview}</p>
                )}
              </div>
              <a
                href={source.pageUrl || source.fetchUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(event) => event.stopPropagation()}
                className="shrink-0 rounded-full bg-white p-2 text-slate-500 transition-colors hover:text-indigo-600"
                title="Open source page"
              >
                <ExternalLink size={16} />
              </a>
            </summary>
            <div className="border-t border-slate-200 bg-white p-4">
              <pre className="whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700 sm:text-xs">
                {source.preview}
              </pre>
            </div>
          </details>
        ))}
      </div>
    </div>
  );
};
