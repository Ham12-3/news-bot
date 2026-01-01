'use client';

import Link from 'next/link';
import { useAuthStore } from '@/lib/auth-store';

export function Navigation() {
  const { user, isAuthenticated, isLoading, logout } = useAuthStore();

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center space-x-2">
            <span className="text-xl font-bold text-primary-600">NIP</span>
            <span className="hidden sm:inline text-gray-600">
              News Intelligence
            </span>
          </Link>

          {/* Navigation Links */}
          <div className="flex items-center space-x-6">
            <Link
              href="/signals"
              className="text-gray-600 hover:text-gray-900 transition"
            >
              Signals
            </Link>

            {isAuthenticated && (
              <Link
                href="/briefings"
                className="text-gray-600 hover:text-gray-900 transition"
              >
                Briefings
              </Link>
            )}

            {/* Auth Section */}
            {isLoading ? (
              <div className="w-20 h-8 bg-gray-200 rounded animate-pulse" />
            ) : isAuthenticated ? (
              <div className="flex items-center space-x-4">
                <span className="text-sm text-gray-600">
                  {user?.display_name || user?.email}
                </span>
                <button
                  onClick={() => logout()}
                  className="text-sm text-gray-600 hover:text-gray-900 transition"
                >
                  Sign Out
                </button>
              </div>
            ) : (
              <div className="flex items-center space-x-4">
                <Link
                  href="/login"
                  className="text-gray-600 hover:text-gray-900 transition"
                >
                  Sign In
                </Link>
                <Link
                  href="/register"
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition"
                >
                  Get Started
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
