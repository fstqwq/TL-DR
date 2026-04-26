import React from 'react';
import { ExternalLink, Globe } from 'lucide-react';
import { LookupSource } from '../types';
import { FormattedSourcePreview, formatLookupSourcePreview } from './sourcePreviewFormatters';

type LookupSourcesProps = {
  sources: LookupSource[];
  title?: string;
  className?: string;
};

type SourceSummaryPreviewProps = {
  formatted: FormattedSourcePreview | null;
  fallbackText: string;
};

const SourceSummaryPreview: React.FC<SourceSummaryPreviewProps> = ({ formatted, fallbackText }) => {
  if (!formatted) {
    return (
      <p className="line-clamp-3 whitespace-pre-line text-xs leading-5 text-slate-600">
        {fallbackText}
      </p>
    );
  }

  const hasHeader = Boolean(formatted.title || formatted.reading);
  const visibleItems = formatted.items.slice(0, hasHeader ? 2 : 3);

  return (
    <div className="min-w-0 text-xs leading-5 text-slate-700">
      {hasHeader && (
        <div className="line-clamp-1">
          {formatted.title && (
            <span className="font-semibold text-slate-800">{formatted.title}</span>
          )}
          {formatted.reading && (
            <span className="ml-1 font-mono text-[11px] text-slate-500">
              [{formatted.reading}]
            </span>
          )}
        </div>
      )}
      {visibleItems.length > 0 && (
        <ul className="mt-0.5 space-y-0.5">
          {visibleItems.map((item, index) => (
            <li key={`${item.term || item.label || 'item'}-${index}`} className="line-clamp-1">
              <span className="mr-1 text-slate-400">-</span>
              {item.term && (
                <span className="mr-1 font-semibold text-slate-900">{item.term}:</span>
              )}
              {item.label && (
                <span className="mr-1 rounded bg-white/80 px-1 font-medium text-slate-500">
                  {item.label}
                </span>
              )}
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
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
        {sources.map((source) => {
          const formatted = formatLookupSourcePreview(source);
          const expandedText = source.raw || source.preview;

          return (
            <details
              key={source.id}
              className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70"
            >
              <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  {source.preview && (
                    <SourceSummaryPreview formatted={formatted} fallbackText={source.preview} />
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="max-w-24 truncate text-xs font-medium text-slate-500">
                    {source.name}
                  </span>
                  <a
                    href={source.pageUrl || source.fetchUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(event) => event.stopPropagation()}
                    className="rounded-full bg-white p-2 text-slate-500 transition-colors hover:text-indigo-600"
                    title="Open source page"
                  >
                    <ExternalLink size={16} />
                  </a>
                </div>
              </summary>
              <div className="border-t border-slate-200 bg-white p-4">
                <pre className="whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700 sm:text-xs">
                  {expandedText}
                </pre>
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
};
