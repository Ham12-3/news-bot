'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { signals } from '@/lib/api';
import { SignalCard } from '@/components/signal-card';

export default function SignalsPage() {
  const [minScore, setMinScore] = useState(0.5);
  const [hours, setHours] = useState(24);

  const { data, isLoading, error } = useQuery({
    queryKey: ['signals', minScore, hours],
    queryFn: () => signals.list({ min_score: minScore, hours, limit: 50 }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">All Signals</h1>

        {/* Filters */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <label className="text-sm text-gray-600">Min Score:</label>
            <select
              value={minScore}
              onChange={(e) => setMinScore(parseFloat(e.target.value))}
              className="px-3 py-1 border border-gray-300 rounded text-sm"
            >
              <option value={0.3}>30%</option>
              <option value={0.5}>50%</option>
              <option value={0.6}>60%</option>
              <option value={0.7}>70%</option>
              <option value={0.8}>80%</option>
            </select>
          </div>

          <div className="flex items-center space-x-2">
            <label className="text-sm text-gray-600">Time:</label>
            <select
              value={hours}
              onChange={(e) => setHours(parseInt(e.target.value))}
              className="px-3 py-1 border border-gray-300 rounded text-sm"
            >
              <option value={6}>6 hours</option>
              <option value={12}>12 hours</option>
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={168}>7 days</option>
            </select>
          </div>
        </div>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-48 bg-gray-200 rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <div className="text-center py-12 text-gray-500">
          Failed to load signals. Please try again later.
        </div>
      )}

      {data && (
        <>
          <p className="text-sm text-gray-500">
            Showing {data.signals.length} signals
            {data.has_more && ' (more available)'}
          </p>

          <div className="grid gap-4 md:grid-cols-2">
            {data.signals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} showActions />
            ))}
          </div>

          {data.signals.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              No signals found matching your filters.
            </div>
          )}
        </>
      )}
    </div>
  );
}
