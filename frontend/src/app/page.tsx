'use client';

import { useQuery } from '@tanstack/react-query';
import { signals } from '@/lib/api';
import { SignalCard } from '@/components/signal-card';
import { useAuthStore } from '@/lib/auth-store';
import Link from 'next/link';

export default function HomePage() {
  const { isAuthenticated, isLoading: authLoading } = useAuthStore();

  const { data, isLoading, error } = useQuery({
    queryKey: ['top-signals'],
    queryFn: () => signals.top(10),
  });

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <section className="text-center py-12">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          News Intelligence Platform
        </h1>
        <p className="text-xl text-gray-600 max-w-2xl mx-auto mb-8">
          AI-powered news curation that cuts through the noise.
          Get the signals that matter, delivered daily.
        </p>

        {!authLoading && !isAuthenticated && (
          <div className="flex gap-4 justify-center">
            <Link
              href="/login"
              className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition"
            >
              Sign In
            </Link>
            <Link
              href="/register"
              className="px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition"
            >
              Create Account
            </Link>
          </div>
        )}

        {!authLoading && isAuthenticated && (
          <Link
            href="/briefings"
            className="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition"
          >
            View Your Briefings
          </Link>
        )}
      </section>

      {/* Top Signals */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-semibold text-gray-900">
            Top Signals Today
          </h2>
          <Link
            href="/signals"
            className="text-primary-600 hover:text-primary-700"
          >
            View all →
          </Link>
        </div>

        {isLoading && (
          <div className="grid gap-4 md:grid-cols-2">
            {[...Array(4)].map((_, i) => (
              <div
                key={i}
                className="h-48 bg-gray-200 rounded-lg animate-pulse"
              />
            ))}
          </div>
        )}

        {error && (
          <div className="text-center py-12 text-gray-500">
            Failed to load signals. Please try again later.
          </div>
        )}

        {data && (
          <div className="grid gap-4 md:grid-cols-2">
            {data.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        )}

        {data?.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            No signals available yet. Check back soon!
          </div>
        )}
      </section>
    </div>
  );
}
