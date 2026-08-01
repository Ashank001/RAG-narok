"use client";

/**
 * app/auth/callback/page.tsx
 * --------------------------
 * GitHub OAuth callback page shell.
 * Wraps the dynamic callback logic in Suspense for Next.js compatibility.
 */

import { Suspense } from "react";
import CallbackHandler from "@/app/auth/callback/CallbackHandler";

function CallbackFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="relative flex h-14 w-14 items-center justify-center">
          <div className="absolute inset-0 rounded-full border-2 border-[#1e1e1e]" />
          <div className="absolute inset-0 animate-spin rounded-full border-t-2 border-[#00ff88]" />
          <svg
            className="h-6 w-6 text-[#00ff88]"
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

export default function CallbackPage() {
  return (
    <Suspense fallback={<CallbackFallback />}>
      <CallbackHandler />
    </Suspense>
  );
}
