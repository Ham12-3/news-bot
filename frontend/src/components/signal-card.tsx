'use client';

import Link from 'next/link';
import type { Signal } from '@/types';
import { formatRelativeTime, formatScore, getScoreColor, truncate } from '@/lib/utils';
import { cn } from '@/lib/utils';

interface SignalCardProps {
  signal: Signal;
  showActions?: boolean;
}

export function SignalCard({ signal, showActions = false }: SignalCardProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition">
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center space-x-2 text-sm text-gray-500">
          <span className="font-medium text-gray-700">{signal.source_name}</span>
          <span>·</span>
          {signal.published_at && (
            <span>{formatRelativeTime(signal.published_at)}</span>
          )}
        </div>
        <div
          className={cn(
            'px-2 py-1 rounded text-sm font-medium',
            getScoreColor(signal.signal_score)
          )}
        >
          {formatScore(signal.signal_score)}
        </div>
      </div>

      {/* Title */}
      <Link href={`/signals/${signal.id}`}>
        <h3 className="text-lg font-semibold text-gray-900 hover:text-primary-600 transition mb-2">
          {signal.title}
        </h3>
      </Link>

      {/* Preview */}
      {signal.content_preview && (
        <p className="text-gray-600 text-sm mb-3">
          {truncate(signal.content_preview, 150)}
        </p>
      )}

      {/* Score Breakdown */}
      <div className="flex items-center space-x-4 text-xs text-gray-500">
        <span title="Relevance">R: {formatScore(signal.relevance)}</span>
        <span title="Velocity">V: {formatScore(signal.velocity)}</span>
        <span title="Cross-source">X: {formatScore(signal.cross_source)}</span>
        <span title="Novelty">N: {formatScore(signal.novelty)}</span>
      </div>

      {/* Actions */}
      {showActions && (
        <div className="flex items-center space-x-4 mt-4 pt-4 border-t border-gray-100">
          <a
            href={signal.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-primary-600 hover:text-primary-700"
          >
            Read Original →
          </a>
        </div>
      )}
    </div>
  );
}
