"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface MessageBubbleProps {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  username?: string;
}

export default function MessageBubble({
  role,
  content,
  isStreaming,
  username = "You",
}: MessageBubbleProps) {
  const isUser = role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={`flex w-full flex-col ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={`flex max-w-[85%] gap-3 ${
          isUser ? "flex-row-reverse" : "flex-row"
        }`}
      >
        {/* Avatar */}
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg shadow-sm">
          {isUser ? (
            <div className="flex h-full w-full items-center justify-center rounded-lg bg-gradient-to-tr from-accent-indigo to-purple-600 text-[11px] font-bold text-white">
              {username.slice(0, 2).toUpperCase()}
            </div>
          ) : (
            <div className="flex h-full w-full items-center justify-center rounded-lg bg-gradient-to-br from-[#00ff88] to-emerald-500 text-black">
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
                  d="M9.663 17h4.673M12 3v1m6.364.364l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
            </div>
          )}
        </div>

        {/* Bubble */}
        <div className="flex flex-col">
          <span className="text-[10px] text-zinc-500 font-medium mb-1 px-1.5">
            {isUser ? username : "RAGnarok AI"}
          </span>
          <div
            className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              isUser
                ? "bg-accent-indigo/15 text-zinc-100 rounded-tr-sm border border-accent-indigo/20"
                : "bg-[#111111] text-zinc-200 border border-[#1e1e1e] rounded-tl-sm"
            }`}
          >
            <div className="space-y-2">
              {renderMessageContent(content)}
              {isStreaming && content === "" && (
                <div className="flex space-x-1.5 py-1 items-center">
                  <div
                    className="h-2 w-2 bg-[#00ff88] rounded-full animate-bounce"
                    style={{ animationDelay: "0ms" }}
                  />
                  <div
                    className="h-2 w-2 bg-[#00ff88] rounded-full animate-bounce"
                    style={{ animationDelay: "150ms" }}
                  />
                  <div
                    className="h-2 w-2 bg-[#00ff88] rounded-full animate-bounce"
                    style={{ animationDelay: "300ms" }}
                  />
                </div>
              )}
              {isStreaming && content !== "" && (
                <span className="cursor-blink" />
              )}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Markdown-ish content renderer with syntax-highlighted code blocks
// ---------------------------------------------------------------------------

function renderMessageContent(content: string) {
  if (!content) return null;

  const parts = content.split(/(```[\s\S]*?```)/g);

  return parts.map((part, index) => {
    // Code block
    if (part.startsWith("```") && part.endsWith("```")) {
      const match = part.match(/```(\w*)\n([\s\S]*?)```/);
      const language = match ? match[1] : "";
      const code = match ? match[2] : part.slice(3, -3);
      return <CodeBlock key={index} language={language} code={code} />;
    }

    // Inline styling: Bold (**text**) and Inline Code (`code`)
    const inlineParts = part.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return (
      <span key={index} className="whitespace-pre-wrap leading-7">
        {inlineParts.map((subpart, subIdx) => {
          if (subpart.startsWith("`") && subpart.endsWith("`")) {
            return (
              <code
                key={subIdx}
                className="px-1.5 py-0.5 mx-0.5 rounded font-mono text-xs bg-[#1a1a2e] text-[#00ff88] border border-[#1e1e1e]"
              >
                {subpart.slice(1, -1)}
              </code>
            );
          }
          if (subpart.startsWith("**") && subpart.endsWith("**")) {
            return (
              <strong key={subIdx} className="font-semibold text-white">
                {subpart.slice(2, -2)}
              </strong>
            );
          }
          return subpart;
        })}
      </span>
    );
  });
}

// ---------------------------------------------------------------------------
// Syntax-highlighted code block with copy button
// ---------------------------------------------------------------------------

interface CodeBlockProps {
  language: string;
  code: string;
}

function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code.trim());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error("Failed to copy", e);
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-[#1e1e1e] bg-[#0d0d0d] font-mono text-sm shadow-lg code-block-wrapper">
      <div className="flex items-center justify-between bg-[#141414] px-4 py-2 text-xs text-zinc-500 select-none border-b border-[#1e1e1e]">
        <span className="font-semibold uppercase tracking-wider text-[10px]">
          {language || "code"}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-white transition-colors"
        >
          {copied ? (
            <>
              <svg
                className="w-3.5 h-3.5 text-[#00ff88]"
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
              <span className="text-[10px] text-[#00ff88] font-medium">
                Copied!
              </span>
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
                  d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"
                />
              </svg>
              <span className="text-[10px] font-medium">Copy</span>
            </>
          )}
        </button>
      </div>
      <SyntaxHighlighter
        language={language || "text"}
        style={oneDark}
        customStyle={{
          margin: 0,
          padding: "1rem",
          background: "transparent",
          fontSize: "0.8125rem",
          lineHeight: 1.6,
        }}
        codeTagProps={{
          style: {
            fontFamily: "var(--font-mono)",
          },
        }}
      >
        {code.trim()}
      </SyntaxHighlighter>
    </div>
  );
}
