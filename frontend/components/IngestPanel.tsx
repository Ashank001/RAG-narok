"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { postIngestRepository, getIngestStatus } from "@/lib/api";

type IngestStatus = "idle" | "queued" | "processing" | "completed" | "failed";

interface IngestSession {
  sessionId: string;
  repoUrl: string;
  status: IngestStatus;
  error?: string;
}

interface IngestPanelProps {
  onSessionReady: (sessionId: string, repoUrl: string) => void;
  onError: (message: string) => void;
}

export default function IngestPanel({ onSessionReady, onError }: IngestPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeIngest, setActiveIngest] = useState<IngestSession | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Validate GitHub URL
  const isValidUrl = (url: string) =>
    /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(url.trim());

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const startPolling = useCallback(
    (sessionId: string, repoUrl: string) => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }

      pollIntervalRef.current = setInterval(async () => {
        try {
          const data = await getIngestStatus(sessionId);
          setActiveIngest((prev) =>
            prev ? { ...prev, status: data.status, error: data.error } : prev
          );

          if (data.status === "completed") {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            onSessionReady(sessionId, repoUrl);
          } else if (data.status === "failed") {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          }
        } catch {
          // Silent fail — keep polling
        }
      }, 2000);
    },
    [onSessionReady]
  );

  const handleSubmit = async () => {
    const url = repoUrl.trim();
    if (!url || !isValidUrl(url) || isSubmitting) return;

    setIsSubmitting(true);
    setActiveIngest(null);

    try {
      const data = await postIngestRepository(url);
      const session: IngestSession = {
        sessionId: data.sessionId,
        repoUrl: url,
        status: "queued",
      };
      setActiveIngest(session);
      setRepoUrl("");
      startPolling(data.sessionId, url);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to connect to ingestion service.";
      onError(message);
      setActiveIngest({
        sessionId: "",
        repoUrl: url,
        status: "failed",
        error: message,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetry = () => {
    if (activeIngest) {
      setRepoUrl(activeIngest.repoUrl);
      setActiveIngest(null);
    }
  };

  const statusConfig: Record<
    IngestStatus,
    { label: string; color: string; dotClass: string }
  > = {
    idle: { label: "", color: "", dotClass: "" },
    queued: {
      label: "Queued",
      color: "text-amber-400",
      dotClass: "bg-amber-400",
    },
    processing: {
      label: "Processing",
      color: "text-blue-400",
      dotClass: "bg-blue-400 animate-pulse",
    },
    completed: {
      label: "Ready",
      color: "text-[#00ff88]",
      dotClass: "bg-[#00ff88]",
    },
    failed: {
      label: "Failed",
      color: "text-red-400",
      dotClass: "bg-red-400",
    },
  };

  return (
    <div className="px-3">
      {/* Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between rounded-xl border border-[#1e1e1e] bg-[#111111]/60 hover:bg-[#1a1a1a] px-3 py-2.5 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-all duration-200"
      >
        <div className="flex items-center gap-2">
          <svg
            className="w-3.5 h-3.5 text-[#00ff88]"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
            />
          </svg>
          <span>Ingest Repository</span>
        </div>
        <motion.svg
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19 9l-7 7-7-7"
          />
        </motion.svg>
      </button>

      {/* Expandable Panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-xl border border-[#1e1e1e] bg-[#0d0d0d] p-3 space-y-3">
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                GitHub Repository URL
              </label>
              <input
                type="url"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSubmit();
                }}
                placeholder="https://github.com/owner/repo"
                disabled={isSubmitting}
                className="w-full rounded-lg border border-[#2a2a2a] bg-[#0a0a0a] px-3 py-2.5 text-xs text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-[#00ff88]/40 focus:ring-1 focus:ring-[#00ff88]/20 transition-all disabled:opacity-50 font-mono"
              />

              {/* URL validation hint */}
              {repoUrl.trim() && !isValidUrl(repoUrl) && (
                <p className="text-[10px] text-red-400/80">
                  Must be a valid GitHub repo URL (https://github.com/owner/repo)
                </p>
              )}

              <button
                onClick={handleSubmit}
                disabled={!repoUrl.trim() || !isValidUrl(repoUrl) || isSubmitting}
                className={`flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-semibold transition-all duration-200 ${
                  isSubmitting
                    ? "bg-[#00ff88]/10 text-[#00ff88] border border-[#00ff88]/20 cursor-wait"
                    : repoUrl.trim() && isValidUrl(repoUrl)
                    ? "bg-[#00ff88]/15 hover:bg-[#00ff88]/25 text-[#00ff88] border border-[#00ff88]/30 hover:border-[#00ff88]/50 active:scale-[0.98]"
                    : "bg-[#1a1a1a] text-zinc-600 border border-[#1e1e1e] cursor-not-allowed"
                }`}
              >
                {isSubmitting ? (
                  <>
                    <svg
                      className="w-3.5 h-3.5 animate-spin"
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
                    Submitting…
                  </>
                ) : (
                  <>
                    <svg
                      className="w-3.5 h-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M13 10V3L4 14h7v7l9-11h-7z"
                      />
                    </svg>
                    Ingest Repository
                  </>
                )}
              </button>

              {/* Active Ingestion Status */}
              <AnimatePresence>
                {activeIngest && activeIngest.status !== "idle" && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    className={`flex items-center justify-between rounded-lg border px-3 py-2.5 text-[11px] ${
                      activeIngest.status === "failed"
                        ? "bg-red-500/5 border-red-500/15"
                        : activeIngest.status === "completed"
                        ? "bg-[#00ff88]/5 border-[#00ff88]/15"
                        : "bg-zinc-900/50 border-[#1e1e1e]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-2 w-2 rounded-full ${
                          statusConfig[activeIngest.status].dotClass
                        }`}
                      />
                      <span
                        className={
                          statusConfig[activeIngest.status].color
                        }
                      >
                        {statusConfig[activeIngest.status].label}
                      </span>
                    </div>

                    {activeIngest.status === "failed" && (
                      <button
                        onClick={handleRetry}
                        className="text-red-400 hover:text-red-300 font-medium transition-colors"
                      >
                        Retry
                      </button>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
