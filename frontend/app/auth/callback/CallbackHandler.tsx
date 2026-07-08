"use client";

/**
 * app/auth/callback/CallbackHandler.tsx
 * --------------------------------------
 * The actual OAuth callback logic component.
 * Separated from page.tsx so it can be safely wrapped in <Suspense> while
 * still calling useSearchParams() (a Client Component hook).
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { saveAuthToken, saveUsername } from "@/lib/auth";

type CallbackStatus =
  | { phase: "exchanging" }
  | { phase: "success"; username: string }
  | { phase: "error"; message: string };



export default function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<CallbackStatus>({ phase: "exchanging" });

  useEffect(() => {
    const code = searchParams.get("code");
    const errorParam = searchParams.get("error");

    // GitHub signals a user-denied authorization via ?error=access_denied
    if (errorParam) {
      setStatus({
        phase: "error",
        message:
          errorParam === "access_denied"
            ? "You cancelled the GitHub authorization. Please try again."
            : `GitHub returned an error: ${errorParam}`,
      });
      return;
    }

    if (!code) {
      setStatus({
        phase: "error",
        message:
          "No authorization code was returned by GitHub. Please try logging in again.",
      });
      return;
    }

    // Exchange the code via the Next.js proxy route (/api/auth/github).
    // The proxy calls FastAPI server-to-server — no CORS, no ERR_EMPTY_RESPONSE.
    const exchangeCode = async () => {
      const endpoint = "/api/auth/github"; // same-origin → zero CORS
      const payload = { code };

      console.info("[Auth] Forwarding code through Next.js proxy:", endpoint);
      console.info("[Auth] Payload:", payload);

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify(payload),
        });

        console.info(
          `[Auth] Proxy responded: ${response.status} ${response.statusText}`
        );

        if (!response.ok) {
          let detail = `Server error ${response.status} ${response.statusText}`;
          try {
            const json = await response.json();
            console.error("[Auth] Error body:", json);
            if (json?.detail) detail = String(json.detail);
          } catch (parseErr) {
            console.error("[Auth] Could not parse error body:", parseErr);
          }
          throw new Error(detail);
        }

        const data: {
          access_token: string;
          token_type: string;
          username: string;
        } = await response.json();

        console.info("[Auth] Token exchange successful for user:", data.username);

        // Persist credentials
        saveAuthToken(data.access_token);
        saveUsername(data.username);

        setStatus({ phase: "success", username: data.username });

        // Brief delay so the user sees the success state before redirect
        setTimeout(() => {
          router.replace("/");
        }, 1200);
      } catch (err) {
        console.error("[Auth] Token exchange failed:", err);
        setStatus({
          phase: "error",
          message:
            err instanceof Error
              ? err.message
              : "An unexpected error occurred during authentication.",
        });
      }
    };

    exchangeCode();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run once on mount — searchParams is stable after initial render

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (status.phase === "exchanging") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <div className="flex flex-col items-center gap-6 text-center px-6 max-w-sm">
          {/* Spinner */}
          <div className="relative flex h-16 w-16 items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-emerald-500/20" />
            <div className="absolute inset-0 animate-spin rounded-full border-t-2 border-emerald-400" />
            <svg
              className="h-7 w-7 text-emerald-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
              />
            </svg>
          </div>

          <div className="space-y-1.5">
            <p className="text-base font-semibold text-white">
              Authenticating…
            </p>
            <p className="text-sm text-zinc-500">
              Exchanging your authorization code with the backend. This only
              takes a second.
            </p>
          </div>

          {/* Progress steps */}
          <div className="flex flex-col gap-2 w-full text-left">
            {[
              { label: "Received GitHub code", done: true },
              { label: "Verifying with FastAPI backend", done: false, active: true },
              { label: "Saving session", done: false },
            ].map(({ label, done, active }) => (
              <div key={label} className="flex items-center gap-2.5">
                <div
                  className={`h-4 w-4 shrink-0 rounded-full flex items-center justify-center ${
                    done
                      ? "bg-emerald-500"
                      : active
                      ? "border-2 border-emerald-400 animate-pulse"
                      : "border border-zinc-700"
                  }`}
                >
                  {done && (
                    <svg
                      className="h-2.5 w-2.5 text-white"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  )}
                </div>
                <span
                  className={`text-xs ${
                    done
                      ? "text-emerald-400"
                      : active
                      ? "text-zinc-200"
                      : "text-zinc-600"
                  }`}
                >
                  {label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (status.phase === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <div className="flex flex-col items-center gap-6 text-center px-6 max-w-sm">
          {/* Success icon */}
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/15 ring-1 ring-emerald-500/30">
            <svg
              className="h-8 w-8 text-emerald-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>

          <div className="space-y-1.5">
            <p className="text-base font-semibold text-white">
              Welcome, {status.username}! 🎉
            </p>
            <p className="text-sm text-zinc-500">
              Authentication successful. Taking you to RAGnarok…
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 px-6">
      <div className="flex flex-col items-center gap-6 text-center max-w-sm w-full">
        {/* Error icon */}
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-500/10 ring-1 ring-red-500/25">
          <svg
            className="h-8 w-8 text-red-400"
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
        </div>

        <div className="space-y-2">
          <p className="text-base font-semibold text-white">
            Authentication failed
          </p>
          <p className="text-sm text-zinc-500 leading-relaxed">
            {status.message}
          </p>
        </div>

        {/* Error detail box */}
        <div className="w-full rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-left">
          <p className="text-xs font-mono text-red-400 break-words">
            {status.message}
          </p>
        </div>

        <button
          id="retry-login-btn"
          onClick={() => router.push("/login")}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-800 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:border-zinc-600 hover:bg-zinc-700 active:scale-[0.98]"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10 19l-7-7m0 0l7-7m-7 7h18"
            />
          </svg>
          Back to Login
        </button>
      </div>
    </div>
  );
}
