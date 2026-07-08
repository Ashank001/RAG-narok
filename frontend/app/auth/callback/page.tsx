"use client";

/**
 * app/auth/callback/page.tsx
 * --------------------------
 * GitHub OAuth callback handler.
 *
 * Flow:
 *  1. GitHub redirects here with ?code=<authorization_code>
 *  2. We POST that code to our FastAPI backend at POST /api/auth/github
 *  3. The backend exchanges it for a GitHub access token, creates a JWT, and
 *     returns { access_token, token_type, username }
 *  4. We store the JWT in localStorage and redirect to the main chat ("/")
 *
 * IMPORTANT (Next.js 16 / React 19):
 *  `useSearchParams` must be inside a <Suspense> boundary when the route
 *  might be statically prerendered. We handle this by splitting into a
 *  server-renderable shell (this file) and a client-only inner component.
 */

import { Suspense } from "react";
import CallbackHandler from "@/app/auth/callback/CallbackHandler";

// ---------------------------------------------------------------------------
// Fallback shown while JS hydrates (and also during prerendering)
// ---------------------------------------------------------------------------
function CallbackFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950">
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="relative flex h-14 w-14 items-center justify-center">
          <div className="absolute inset-0 rounded-full border-2 border-emerald-500/20" />
          <div className="absolute inset-0 animate-spin rounded-full border-t-2 border-emerald-400" />
          <svg
            className="h-6 w-6 text-emerald-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        </div>
        <p className="text-sm font-medium text-zinc-300">
          Connecting to GitHub…
        </p>
        <p className="text-xs text-zinc-600">Please wait a moment</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page shell — wraps the dynamic callback logic in Suspense
// ---------------------------------------------------------------------------
export default function CallbackPage() {
  return (
    <Suspense fallback={<CallbackFallback />}>
      <CallbackHandler />
    </Suspense>
  );
}
