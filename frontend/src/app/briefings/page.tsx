'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { briefings } from '@/lib/api';
import { useAuthStore } from '@/lib/auth-store';
import { formatDate } from '@/lib/utils';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function BriefingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isAuthenticated, isLoading: authLoading } = useAuthStore();

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [authLoading, isAuthenticated, router]);

  const { data: latest, isLoading: latestLoading } = useQuery({
    queryKey: ['latest-briefing'],
    queryFn: () => briefings.latest(),
    enabled: isAuthenticated,
  });

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['briefing-history'],
    queryFn: () => briefings.list(10),
    enabled: isAuthenticated,
  });

  const generateMutation = useMutation({
    mutationFn: () => briefings.generate(false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['latest-briefing'] });
      queryClient.invalidateQueries({ queryKey: ['briefing-history'] });
    },
  });

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Your Briefings</h1>

        <button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition disabled:opacity-50"
        >
          {generateMutation.isPending ? 'Generating...' : 'Generate New'}
        </button>
      </div>

      {generateMutation.isError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          Failed to generate briefing. Please try again.
        </div>
      )}

      {generateMutation.isSuccess && !generateMutation.data.generated && (
        <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-yellow-700 text-sm">
          {generateMutation.data.message || "A briefing already exists for today."}
        </div>
      )}

      {/* Latest Briefing */}
      <section>
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          Latest Briefing
        </h2>

        {latestLoading && (
          <div className="h-64 bg-gray-200 rounded-lg animate-pulse" />
        )}

        {!latestLoading && !latest && (
          <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
            No briefings yet. Click "Generate New" to create your first briefing.
          </div>
        )}

        {latest && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm text-gray-500">
                {formatDate(latest.generated_at)}
              </span>
              {latest.sent_at && (
                <span className="text-xs text-green-600">
                  Sent via email
                </span>
              )}
            </div>

            <div className="prose prose-sm max-w-none">
              <ReactMarkdown>{latest.content}</ReactMarkdown>
            </div>

            {latest.items && latest.items.length > 0 && (
              <div className="mt-6 pt-6 border-t border-gray-200">
                <h3 className="text-sm font-medium text-gray-700 mb-3">
                  Sources ({latest.items.length})
                </h3>
                <ul className="space-y-2">
                  {latest.items.map((item) => (
                    <li key={item.id} className="text-sm">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary-600 hover:text-primary-700"
                      >
                        {item.title}
                      </a>
                      <span className="text-gray-400"> - {item.source}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Briefing History */}
      {history && history.briefings.length > 1 && (
        <section>
          <h2 className="text-xl font-semibold text-gray-900 mb-4">
            Previous Briefings
          </h2>

          <div className="space-y-3">
            {history.briefings.slice(1).map((briefing) => (
              <Link
                key={briefing.id}
                href={`/briefings/${briefing.id}`}
                className="block bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">
                    {formatDate(briefing.generated_at)}
                  </span>
                  {briefing.sent_at && (
                    <span className="text-xs text-green-600">Sent</span>
                  )}
                </div>
                <p className="text-sm text-gray-500 mt-1 line-clamp-2">
                  {briefing.content.slice(0, 150)}...
                </p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
