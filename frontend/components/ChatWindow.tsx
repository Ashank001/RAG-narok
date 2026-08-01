"use client";

import React, { useRef, useEffect, KeyboardEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import MessageBubble from "./MessageBubble";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
}

// ---------------------------------------------------------------------------
// Ingestion Progress State
// ---------------------------------------------------------------------------

export type IngestStep = "cloning" | "filtering" | "embedding" | "ready";

interface IngestProgressProps {
  currentStep: IngestStep;
  repoUrl: string;
}

const INGEST_STEPS: { key: IngestStep; label: string; icon: React.ReactNode }[] = [
  {
    key: "cloning",
    label: "Cloning repository",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
    ),
  },
  {
    key: "filtering",
    label: "Filtering files",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
      </svg>
    ),
  },
  {
    key: "embedding",
    label: "Generating embeddings",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
  {
    key: "ready",
    label: "Ready to chat",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    ),
  },
];

function IngestProgress({ currentStep, repoUrl }: IngestProgressProps) {
  const stepOrder: IngestStep[] = ["cloning", "filtering", "embedding", "ready"];
  const currentIndex = stepOrder.indexOf(currentStep);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="mx-auto max-w-md flex flex-col items-center pt-20 text-center px-6"
    >
      {/* Spinner */}
      <div className="relative mb-8">
        <div className="h-16 w-16 rounded-full border-2 border-[#1e1e1e]" />
        <div className="absolute inset-0 h-16 w-16 animate-spin-slow rounded-full border-t-2 border-[#00ff88]" />
        <div className="absolute inset-0 flex items-center justify-center">
          <svg className="w-6 h-6 text-[#00ff88]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
      </div>

      <h3 className="text-lg font-semibold text-white mb-1">Ingesting Repository</h3>
      <p className="text-xs text-zinc-500 font-mono mb-8 truncate max-w-full">{repoUrl}</p>

      {/* Steps */}
      <div className="flex flex-col gap-3 w-full text-left">
        {INGEST_STEPS.map((step, i) => {
          const isComplete = i < currentIndex;
          const isActive = i === currentIndex;
          const isPending = i > currentIndex;

          return (
            <motion.div
              key={step.key}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className={`flex items-center gap-3 rounded-lg px-4 py-3 border transition-all ${
                isComplete
                  ? "border-[#00ff88]/20 bg-[#00ff88]/5"
                  : isActive
                  ? "border-[#00ff88]/30 bg-[#00ff88]/10 animate-pulse-glow"
                  : "border-[#1e1e1e] bg-[#111111]"
              }`}
            >
              <span
                className={`${
                  isComplete
                    ? "text-[#00ff88]"
                    : isActive
                    ? "text-[#00ff88]"
                    : "text-zinc-600"
                }`}
              >
                {isComplete ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  step.icon
                )}
              </span>
              <span
                className={`text-sm ${
                  isComplete
                    ? "text-[#00ff88]"
                    : isActive
                    ? "text-white font-medium"
                    : "text-zinc-600"
                }`}
              >
                {step.label}
              </span>
              {isActive && !isComplete && (
                <svg className="w-3.5 h-3.5 animate-spin text-[#00ff88] ml-auto" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
            </motion.div>
          );
        })}
      </div>

      <p className="text-[11px] text-zinc-600 mt-6">
        This may take a few minutes depending on repository size.
      </p>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main ChatWindow Component
// ---------------------------------------------------------------------------

interface ChatWindowProps {
  messages: Message[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: (text?: string) => void;
  onStopGeneration: () => void;
  isStreaming: boolean;
  username: string;
  activeSession: string | null;
  activeRepoUrl: string | null;
  ingestStep: IngestStep | null;
  ingestRepoUrl: string | null;
  onToggleSidebar: () => void;
}

const SUGGESTION_CARDS = [
  {
    title: "Explain the architecture",
    desc: "High-level overview of how this codebase is structured",
    prompt: "Explain the overall architecture of this codebase. What are the main components and how do they interact?",
  },
  {
    title: "Find potential bugs",
    desc: "Look for common issues and anti-patterns",
    prompt: "Analyze this codebase for potential bugs, security issues, or anti-patterns. Suggest fixes.",
  },
  {
    title: "How does X work?",
    desc: "Deep dive into specific functionality",
    prompt: "How does the main request handling pipeline work? Trace a request from entry to response.",
  },
  {
    title: "What does Y function do?",
    desc: "Explain a specific function's purpose",
    prompt: "What are the most important functions in this codebase? Explain what each one does.",
  },
];

export default function ChatWindow({
  messages,
  input,
  onInputChange,
  onSend,
  onStopGeneration,
  isStreaming,
  username,
  activeSession,
  activeRepoUrl,
  ingestStep,
  ingestRepoUrl,
  onToggleSidebar,
}: ChatWindowProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [input]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  // STATE 2: Ingesting
  if (ingestStep && ingestRepoUrl) {
    return (
      <main className="relative flex flex-1 flex-col overflow-hidden h-full">
        <Header
          onToggleSidebar={onToggleSidebar}
          activeSession={activeSession}
          activeRepoUrl={activeRepoUrl}
        />
        <div className="flex-1 overflow-y-auto">
          <IngestProgress currentStep={ingestStep} repoUrl={ingestRepoUrl} />
        </div>
      </main>
    );
  }

  // STATE 1: Empty (no messages)
  if (messages.length === 0) {
    return (
      <main className="relative flex flex-1 flex-col overflow-hidden h-full">
        <Header
          onToggleSidebar={onToggleSidebar}
          activeSession={activeSession}
          activeRepoUrl={activeRepoUrl}
        />

        <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="mx-auto flex max-w-2xl flex-col items-center justify-center pt-16 text-center"
          >
            {/* Logo icon */}
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#00ff88] to-emerald-500 shadow-xl shadow-[#00ff88]/10 mb-6">
              <svg
                className="w-7 h-7 text-black"
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
            <h2 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
              How can I help?
            </h2>
            <p className="mt-2.5 text-sm text-zinc-500 max-w-md">
              Ingest a GitHub repository and ask questions about the codebase.
            </p>

            {/* Suggestion Cards */}
            <div className="mt-8 grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
              {SUGGESTION_CARDS.map((card, idx) => (
                <motion.button
                  key={idx}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15 + idx * 0.07, duration: 0.35 }}
                  onClick={() => onSend(card.prompt)}
                  className="flex flex-col rounded-xl border border-[#1e1e1e] bg-[#111111] hover:bg-[#1a1a1a] hover:border-[#2a2a2a] p-4 text-left transition-all duration-200 group"
                >
                  <span className="font-medium text-xs text-white group-hover:text-[#00ff88] transition-colors">
                    {card.title}
                  </span>
                  <span className="mt-1 text-[11px] text-zinc-500 leading-relaxed">
                    {card.desc}
                  </span>
                </motion.button>
              ))}
            </div>
          </motion.div>
        </div>

        {/* Input Bar */}
        <InputBar
          input={input}
          onInputChange={onInputChange}
          onSend={onSend}
          onStopGeneration={onStopGeneration}
          isStreaming={isStreaming}
          textareaRef={textareaRef}
          handleKeyDown={handleKeyDown}
          activeRepoUrl={activeRepoUrl}
          activeSession={activeSession}
        />
      </main>
    );
  }

  // STATE 3: Chat Active
  return (
    <main className="relative flex flex-1 flex-col overflow-hidden h-full">
      <Header
        onToggleSidebar={onToggleSidebar}
        activeSession={activeSession}
        activeRepoUrl={activeRepoUrl}
      />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
        <div className="mx-auto max-w-3xl space-y-5">
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              id={message.id}
              role={message.role}
              content={message.content}
              isStreaming={message.isStreaming}
              username={username}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Bar */}
      <InputBar
        input={input}
        onInputChange={onInputChange}
        onSend={onSend}
        onStopGeneration={onStopGeneration}
        isStreaming={isStreaming}
        textareaRef={textareaRef}
        handleKeyDown={handleKeyDown}
        activeRepoUrl={activeRepoUrl}
        activeSession={activeSession}
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// Header sub-component
// ---------------------------------------------------------------------------

function Header({
  onToggleSidebar,
  activeSession,
  activeRepoUrl,
}: {
  onToggleSidebar: () => void;
  activeSession: string | null;
  activeRepoUrl: string | null;
}) {
  return (
    <header className="flex h-14 items-center justify-between border-b border-[#1e1e1e] px-4 bg-[#0a0a0a]/80 backdrop-blur-md shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="rounded-lg p-2 text-zinc-500 hover:bg-[#1a1a1a] hover:text-white transition-colors lg:hidden"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>

        {activeRepoUrl && (
          <div className="flex items-center gap-2 rounded-lg bg-[#111111] px-3 py-1.5 border border-[#1e1e1e]">
            <svg className="w-3.5 h-3.5 text-[#00ff88]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <span className="text-xs text-zinc-300 font-mono truncate max-w-[200px]">
              {activeRepoUrl.replace("https://github.com/", "")}
            </span>
          </div>
        )}
      </div>

      {activeSession && (
        <div className="text-[11px] text-zinc-600 select-none hidden sm:block font-mono">
          Session: <span className="text-zinc-400">{activeSession.slice(0, 12)}</span>
        </div>
      )}
    </header>
  );
}

// ---------------------------------------------------------------------------
// Input Bar sub-component
// ---------------------------------------------------------------------------

function InputBar({
  input,
  onInputChange,
  onSend,
  onStopGeneration,
  isStreaming,
  textareaRef,
  handleKeyDown,
  activeRepoUrl,
  activeSession,
}: {
  input: string;
  onInputChange: (value: string) => void;
  onSend: (text?: string) => void;
  onStopGeneration: () => void;
  isStreaming: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  handleKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  activeRepoUrl: string | null;
  activeSession: string | null;
}) {
  return (
    <div className="border-t border-[#1e1e1e] p-4 bg-[#0a0a0a]/80 backdrop-blur-md shrink-0">
      <div className="mx-auto max-w-3xl">
        {/* Active repo indicator */}
        {activeRepoUrl && activeSession && (
          <div className="flex items-center gap-2 mb-2 px-1">
            <span className="h-1.5 w-1.5 rounded-full bg-[#00ff88]" />
            <span className="text-[10px] text-zinc-500 font-mono truncate">
              {activeRepoUrl.replace("https://github.com/", "")} • {activeSession.slice(0, 8)}
            </span>
          </div>
        )}

        <div className="relative flex items-end rounded-2xl border border-[#1e1e1e] bg-[#111111] shadow-xl shadow-black/20 focus-within:border-[#2a2a2a] focus-within:ring-1 focus-within:ring-[#00ff88]/15 transition-all">
          {/* Text Input */}
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about the codebase…"
            className="flex-1 resize-none overflow-y-auto bg-transparent px-4 py-3.5 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 max-h-[200px]"
          />

          <div className="flex items-center gap-2 pr-3 pb-2.5">
            {/* Char count */}
            {input.length > 0 && (
              <span className="text-[10px] text-zinc-600 tabular-nums">
                {input.length}
              </span>
            )}

            {/* Send / Stop */}
            {isStreaming ? (
              <button
                onClick={onStopGeneration}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-400 transition-all active:scale-95"
                title="Stop generating"
              >
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="1.5" />
                </svg>
              </button>
            ) : (
              <button
                onClick={() => onSend()}
                disabled={!input.trim()}
                className={`flex h-8 w-8 items-center justify-center rounded-lg transition-all active:scale-95 ${
                  input.trim()
                    ? "bg-[#00ff88]/20 hover:bg-[#00ff88]/30 text-[#00ff88] cursor-pointer"
                    : "bg-[#1a1a1a] text-zinc-600 cursor-not-allowed"
                }`}
                title="Send message"
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M5 10l7-7m0 0l7 7m-7-7v18"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>

        <p className="mt-2 text-center text-[10px] text-zinc-700">
          RAGnarok can make mistakes. Always verify important information.
        </p>
      </div>
    </div>
  );
}
