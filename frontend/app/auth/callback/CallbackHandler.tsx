"use client";

/**
 * app/auth/callback/CallbackHandler.tsx
 * --------------------------------------
 * OAuth callback logic — exchanges the GitHub code for a JWT token,
 * stores it, and redirects to /dashboard.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { saveAuthToken, saveUsername, saveAvatar } from "@/lib/auth";
import { motion } from "framer-motion";

type CallbackStatus =
  | { phase: "exchanging" }
  | { phase: "success"; username: string }
  | { phase: "error"; message: string };

export default function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<CallbackStatus>({ phase: "exchanging" });

  // Guard against React 18 Strict Mode double-firing this effect.
  // GitHub OAuth codes are single-use — a second exchange attempt would fail.
  const exchangedRef = useRef(false);

  useEffect(() => {
    if (exchangedRef.current) return;   // already fired once
    exchangedRef.current = true;

    const code = searchParams.get("code");
    const errorParam = searchParams.get("error");

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

    const exchangeCode = async () => {
      const endpoint = "/api/auth/github";
      const payload = { code };

      console.info("[Auth] Forwarding code through Next.js proxy:", endpoint);

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
          avatar_url?: string;
        } = await response.json();

        console.info("[Auth] Token exchange successful for user:", data.username);

        // Persist credentials
        saveAuthToken(data.access_token);
        saveUsername(data.username);
        if (data.avatar_url) {
          saveAvatar(data.avatar_url);
        }

        setStatus({ phase: "success", username: data.username });

        // Redirect to dashboard
        setTimeout(() => {
          router.replace("/dashboard");
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
  }, []);

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (status.phase === "exchanging") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col items-center gap-6 text-center px-6 max-w-sm"
        >
          {/* Spinner */}
          <div className="relative flex h-16 w-16 items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-[#1e1e1e]" />
            <div className="absolute inset-0 animate-spin rounded-full border-t-2 border-[#00ff88]" />
            <svg
              className="h-7 w-7 text-[#00ff88]"
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
              Exchanging your authorization code. This only takes a second.
            </p>
          </div>

          {/* Progress steps */}
          <div className="flex flex-col gap-2 w-full text-left">
            {[
              { label: "Received GitHub code", done: true },
              { label: "Verifying with backend", done: false, active: true },
              { label: "Saving session", done: false },
            ].map(({ label, done, active }) => (
              <div key={label} className="flex items-center gap-2.5">
                <div
                  className={`h-4 w-4 shrink-0 rounded-full flex items-center justify-center ${
                    done
                      ? "bg-[#00ff88]"
                      : active
                      ? "border-2 border-[#00ff88] animate-pulse"
                      : "border border-[#2a2a2a]"
                  }`}
                >
                  {done && (
                    <svg
                      className="h-2.5 w-2.5 text-black"
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
                      ? "text-[#00ff88]"
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
        </motion.div>
      </div>
    );
  }

  if (status.phase === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center gap-6 text-center px-6 max-w-sm"
        >
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#00ff88]/10 ring-1 ring-[#00ff88]/30">
            <svg
              className="h-8 w-8 text-[#00ff88]"
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
        </motion.div>
      </div>
    );
  }

  // Error state
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] px-6">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col items-center gap-6 text-center max-w-sm w-full"
      >
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

        <div className="w-full rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-left">
          <p className="text-xs font-mono text-red-400 break-words">
            {status.message}
          </p>
        </div>

        <button
          id="retry-login-btn"
          onClick={() => router.push("/login")}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#2a2a2a] bg-[#1a1a1a] px-5 py-3 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:border-[#3a3a3a] hover:bg-[#222222] active:scale-[0.98]"
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
      </motion.div>
    </div>
  );
}
