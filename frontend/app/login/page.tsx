"use client";

/**
 * app/login/page.tsx
 * ------------------
 * The RAGnarok login page.
 * Renders a single "Login with GitHub" button that redirects the user to the
 * GitHub OAuth authorization URL.  If the user is already authenticated (i.e.
 * a token is present in localStorage) they are silently forwarded to the chat.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { buildGitHubOAuthUrl, isAuthenticated } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If already authenticated, send the user straight to the app
  useEffect(() => {
    if (isAuthenticated()) {
      router.replace("/");
    }
  }, [router]);

  const handleLogin = () => {
    try {
      setIsLoading(true);
      setError(null);
      const url = buildGitHubOAuthUrl();
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build GitHub OAuth URL.");
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 relative overflow-hidden">
      {/* Background gradient blobs */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -left-40 h-[600px] w-[600px] rounded-full bg-emerald-500/10 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -right-40 h-[600px] w-[600px] rounded-full bg-teal-500/10 blur-[120px]"
      />

      <div className="relative z-10 flex flex-col items-center gap-8 px-6 text-center">
        {/* Logo mark */}
        <div className="flex flex-col items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-2xl shadow-emerald-500/30 ring-1 ring-white/10">
            <svg
              className="h-9 w-9 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>

          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight text-white">
              RAGnarok
            </h1>
            <p className="text-sm text-zinc-400">
              Retrieval-Augmented Generation · Chat with your codebase
            </p>
          </div>
        </div>

        {/* Login card */}
        <div className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-900/70 p-8 shadow-2xl backdrop-blur-xl ring-1 ring-white/5">
          <div className="space-y-2 mb-8">
            <h2 className="text-lg font-semibold text-white">
              Welcome back
            </h2>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Connect your GitHub account to start querying your repositories with AI.
            </p>
          </div>

          {/* Error message */}
          {error && (
            <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                />
              </svg>
              <span>{error}</span>
            </div>
          )}

          {/* GitHub OAuth Button */}
          <button
            id="github-login-btn"
            onClick={handleLogin}
            disabled={isLoading}
            className="group relative flex w-full items-center justify-center gap-3 rounded-xl border border-zinc-700 bg-zinc-800 px-5 py-3.5 text-sm font-semibold text-white shadow-md transition-all duration-200 hover:border-zinc-600 hover:bg-zinc-700 hover:shadow-lg hover:shadow-black/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? (
              <>
                <svg
                  className="h-4 w-4 animate-spin text-zinc-400"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Redirecting to GitHub…
              </>
            ) : (
              <>
                {/* GitHub mark */}
                <svg
                  className="h-5 w-5 transition-transform duration-200 group-hover:scale-105"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden
                >
                  <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
                </svg>
                Continue with GitHub
              </>
            )}
          </button>

          <p className="mt-5 text-center text-xs text-zinc-600 leading-relaxed">
            By continuing, you agree to our{" "}
            <span className="text-zinc-500 underline-offset-2 hover:underline cursor-pointer">
              Terms of Service
            </span>{" "}
            and{" "}
            <span className="text-zinc-500 underline-offset-2 hover:underline cursor-pointer">
              Privacy Policy
            </span>
            .
          </p>
        </div>

        {/* Feature pills */}
        <div className="flex flex-wrap justify-center gap-2 max-w-sm">
          {[
            "🔍 Semantic code search",
            "⚡ Streaming responses",
            "🔒 Secure OAuth",
          ].map((feat) => (
            <span
              key={feat}
              className="rounded-full border border-zinc-800 bg-zinc-900/60 px-3 py-1 text-xs text-zinc-500"
            >
              {feat}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
