"use client";

import React, { useState, useEffect, useRef, FormEvent, KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { getAuthToken, getUsername, clearAuthToken, isAuthenticated } from "@/lib/auth";
import { apiFetch } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
}

interface ChatSession {
  id: string;
  title: string;
  timestamp: string;
}

export default function Home() {
  const router = useRouter();
  const [authUsername, setAuthUsername] = useState<string>("You");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [apiConnected, setApiConnected] = useState<"checking" | "connected" | "disconnected" | "demo">("checking");
  const [activeSession, setActiveSession] = useState("session_123");
  const [sessions, setSessions] = useState<ChatSession[]>([
    { id: "session_123", title: "FastAPI SSE Integration", timestamp: "Just now" },
    { id: "session_2", title: "Next.js Tailwind v4 Layout", timestamp: "2 hours ago" },
    { id: "session_3", title: "RAG Pipeline Query Debugging", timestamp: "Yesterday" },
    { id: "session_4", title: "Database Vector Indexing", timestamp: "3 days ago" },
  ]);

  // --- Ingestion State ---
  const [repoUrl, setRepoUrl] = useState("");
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [isIngestPanelOpen, setIsIngestPanelOpen] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auth guard: redirect to /login if no token is present
  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      const stored = getUsername();
      if (stored) setAuthUsername(stored);
    }
  }, [router]);

  // Check API connectivity initially
  useEffect(() => {
    const checkAPI = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);
        // Use apiFetch so the request goes to localhost:8000 (matching CORS allowed origins)
        // Hit /health — a lightweight unauthenticated endpoint
        const response = await apiFetch("/health", {
          method: "GET",
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        setApiConnected("connected");
      } catch (err) {
        console.warn("FastAPI server not reachable, falling back to Demo Mode.", err);
        setApiConnected("demo");
      }
    };
    checkAPI();
  }, []);

  // Handle textarea auto-resizing
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSendMessage = async (textToSend?: string) => {
    const queryText = (textToSend || input).trim();
    if (!queryText || isStreaming) return;

    if (!textToSend) {
      setInput("");
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: queryText,
    };

    const assistantPlaceholder: Message = {
      id: (Date.now() + 1).toString(),
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
    setIsStreaming(true);

    // Setup Abort Controller
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    if (apiConnected === "demo") {
      // Simulate SSE stream in demo mode
      simulateStreamingResponse(queryText, assistantPlaceholder.id);
      return;
    }

    try {
      const response = await apiFetch(`/chat/${activeSession}`, {
        method: "POST",
        body: JSON.stringify({ query: queryText }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }

      if (!response.body) {
        throw new Error("No response body available for streaming.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;

      while (!finished) {
        const { value, done } = await reader.read();
        if (done) {
          finished = true;
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        // Keep the last chunk in the buffer if it is incomplete
        buffer = parts.pop() || "";

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed) continue;

          // SSE format: data: {"text": "hello"} or data: {"done": true}
          let jsonStr = trimmed;
          if (trimmed.startsWith("data:")) {
            jsonStr = trimmed.substring(5).trim();
          }

          try {
            const parsed = JSON.parse(jsonStr);
            if (parsed.text) {
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantPlaceholder.id
                    ? { ...msg, content: msg.content + parsed.text }
                    : msg
                )
              );
            }
            if (parsed.done === true) {
              finished = true;
            }
          } catch (e) {
            console.warn("Could not parse JSON chunk:", jsonStr, e);
          }
        }
      }

      // Flush remaining buffer
      if (buffer.trim()) {
        const trimmed = buffer.trim();
        let jsonStr = trimmed;
        if (trimmed.startsWith("data:")) {
          jsonStr = trimmed.substring(5).trim();
        }
        try {
          const parsed = JSON.parse(jsonStr);
          if (parsed.text) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantPlaceholder.id
                  ? { ...msg, content: msg.content + parsed.text }
                  : msg
              )
            );
          }
        } catch (e) {
          console.warn("Error parsing final chunk:", e);
        }
      }
    } catch (error: any) {
      if (error.name === "AbortError") {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantPlaceholder.id
              ? { ...msg, content: msg.content + "\n\n*[Response generation cancelled by user]*" }
              : msg
          )
        );
      } else {
        console.error("Fetch error:", error);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantPlaceholder.id
              ? {
                ...msg,
                content: `⚠️ Connection Failed.\n\nCould not stream response from FastAPI server. Please check if the backend is running at http://127.0.0.1:8000/chat/session_123 or switch to Demo Mode.`,
              }
              : msg
          )
        );
      }
    } finally {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantPlaceholder.id ? { ...msg, isStreaming: false } : msg
        )
      );
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  };

  // Helper to simulate SSE streaming chunks for Demo Mode
  const simulateStreamingResponse = (query: string, placeholderId: string) => {
    let mockResponse = "";
    const lowerQuery = query.toLowerCase();

    if (lowerQuery.includes("sse") || lowerQuery.includes("stream")) {
      mockResponse = `Server-Sent Events (SSE) is an HTTP standard that allows a web server to push real-time updates to a client over a single long-lived connection.\n\nHere is how you parse the stream in React:\n\n\`\`\`typescript\nconst response = await fetch("http://127.0.0.1:8000/chat/session_123", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify({ query: "${query}" })\n});\n\nconst reader = response.body.getReader();\nconst decoder = new TextDecoder();\nlet buffer = "";\n\nwhile (true) {\n  const { value, done } = await reader.read();\n  if (done) break;\n  buffer += decoder.decode(value, { stream: true });\n  // Split by double newline\n  const events = buffer.split("\\n\\n");\n  ...\n}\n\`\`\`\n\nThis creates a highly efficient streaming link without full WebSockets overhead!`;
    } else if (lowerQuery.includes("fastapi")) {
      mockResponse = `To set up a FastAPI server that returns this SSE stream, install \`sse-starlette\` and run a route like this:\n\n\`\`\`python\nfrom fastapi import FastAPI\nfrom fastapi.responses import StreamingResponse\nfrom fastapi.middleware.cors import CORSMiddleware\nimport json, asyncio\n\napp = FastAPI()\napp.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])\n\n@app.post("/chat/session_123")\nasync def chat_session():\n    async def event_generator():\n        chunks = ["Hello", "!", " This", " is", " streaming", " from", " FastAPI", "."]\n        for chunk in chunks:\n            yield f"data: {json.dumps({'text': chunk})}\\n\\n"\n            await asyncio.sleep(0.15)\n        yield "data: {\\"done\\": true}\\n\\n"\n    return StreamingResponse(event_generator(), media_type="text/event-stream")\n\`\`\`\n\nThis response was simulated dynamically using **Demo Mode**.`;
    } else {
      mockResponse = `Hello! I received your query: **"${query}"**.\n\nSince the FastAPI backend at \`http://127.0.0.1:8000/chat/session_123\` is offline, I've loaded in **Demo Mode**.\n\nHere are some cool design elements of this Chat UI:\n- **Clean layout** inspired by modern ChatGPT interfaces.\n- **SSE-compatible parsing** for real-time text chunk rendering.\n- **Syntax highlighting renderer** with a copy-to-clipboard button.\n- **Abort stream support** - you can cancel generations on the fly!\n- **Fully responsive sidebar** and support for dark/light modes.\n\nHow else can I help you today?`;
    }

    const words = mockResponse.split(/( )/);
    let index = 0;

    const interval = setInterval(() => {
      // Check if user cancelled the stream
      if (abortControllerRef.current?.signal.aborted) {
        clearInterval(interval);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === placeholderId
              ? {
                ...msg,
                content: msg.content + "\n\n*[Response generation cancelled by user]*",
                isStreaming: false,
              }
              : msg
          )
        );
        setIsStreaming(false);
        abortControllerRef.current = null;
        return;
      }

      if (index >= words.length) {
        clearInterval(interval);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === placeholderId ? { ...msg, isStreaming: false } : msg
          )
        );
        setIsStreaming(false);
        abortControllerRef.current = null;
      } else {
        const nextWord = words[index];
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === placeholderId ? { ...msg, content: msg.content + nextWord } : msg
          )
        );
        index++;
      }
    }, 20); // typing speed
  };

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Helper to parse content and render markdown bold, inline code, and block code
  const renderMessageContent = (content: string) => {
    if (!content) return null;

    const parts = content.split(/(```[\s\S]*?```)/g);

    return parts.map((part, index) => {
      // Match Code Block
      if (part.startsWith("```") && part.endsWith("```")) {
        const match = part.match(/```(\w*)\n([\s\S]*?)```/);
        const language = match ? match[1] : "";
        const code = match ? match[2] : part.slice(3, -3);

        return (
          <CodeBlock key={index} language={language} code={code} />
        );
      }

      // Parse inline styling: Bold (**text**) and Inline Code (`code`)
      const inlineParts = part.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
      return (
        <span key={index} className="whitespace-pre-wrap leading-7">
          {inlineParts.map((subpart, subIdx) => {
            if (subpart.startsWith("`") && subpart.endsWith("`")) {
              return (
                <code
                  key={subIdx}
                  className="px-1.5 py-0.5 mx-0.5 rounded font-mono text-sm bg-zinc-100 dark:bg-zinc-800 text-emerald-600 dark:text-emerald-400 border border-zinc-200 dark:border-zinc-700/50"
                >
                  {subpart.slice(1, -1)}
                </code>
              );
            }
            if (subpart.startsWith("**") && subpart.endsWith("**")) {
              return (
                <strong key={subIdx} className="font-semibold text-zinc-900 dark:text-white">
                  {subpart.slice(2, -2)}
                </strong>
              );
            }
            return subpart;
          })}
        </span>
      );
    });
  };

  const startNewChat = () => {
    handleStopGeneration();
    setMessages([]);
    setInput("");
  };

  // --- Ingestion Handler ---
  const handleIngestRepository = async () => {
    const trimmedUrl = repoUrl.trim();
    if (!trimmedUrl || isIngesting) return;

    // Basic URL validation
    if (!trimmedUrl.startsWith("https://github.com/")) {
      setIngestResult({ type: "error", message: "Please enter a valid GitHub repository URL (https://github.com/...)" });
      return;
    }

    setIsIngesting(true);
    setIngestResult(null);

    const sessionId = `ingest_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;

    try {
      const response = await apiFetch("/api/ingest", {
        method: "POST",
        body: JSON.stringify({ sessionId, repositoryUrl: trimmedUrl }),
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      setIngestResult({
        type: "success",
        message: `Ingestion queued! Session: ${data.sessionId || sessionId}`,
      });
      setRepoUrl("");
    } catch (error: any) {
      setIngestResult({
        type: "error",
        message: error.message || "Failed to connect to ingestion API.",
      });
    } finally {
      setIsIngesting(false);
      // Auto-clear success messages after 6 seconds
      setTimeout(() => setIngestResult(null), 6000);
    }
  };

  return (
    <div className={`flex h-screen w-full overflow-hidden font-sans transition-colors duration-300 ${isDarkMode ? "bg-zinc-900 text-zinc-100" : "bg-zinc-50 text-zinc-800"}`}>
      {/* Dynamic Cursor Blinking style */}
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .cursor-blink {
          display: inline-block;
          width: 5px;
          height: 15px;
          background-color: ${isDarkMode ? "#34d399" : "#10b981"};
          margin-left: 2px;
          vertical-align: middle;
          animation: blink 1s step-end infinite;
        }
      `}</style>

      {/* LEFT SIDEBAR */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-zinc-200 bg-zinc-950 text-zinc-300 transition-transform duration-300 ease-in-out md:static md:translate-x-0 ${isSidebarOpen ? "translate-x-0" : "-translate-x-full"
          } border-zinc-805 ${isDarkMode ? "border-zinc-800" : "border-zinc-200"}`}
      >
        {/* Sidebar Header */}
        <div className="flex h-14 items-center justify-between px-4 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-emerald-500 to-teal-600 shadow-md">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <span className="font-semibold text-white tracking-wide text-sm">RAGnarok</span>
          </div>

          <button
            onClick={() => setIsSidebarOpen(false)}
            className="rounded-md p-1.5 hover:bg-zinc-800 hover:text-white md:hidden transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Sidebar New Chat Button */}
        <div className="p-3.5">
          <button
            onClick={startNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-850 hover:border-zinc-700 px-4 py-2.5 text-sm font-medium text-white transition-all duration-200 shadow-inner group"
          >
            <svg className="w-4 h-4 text-emerald-400 group-hover:rotate-90 transition-transform duration-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
            </svg>
            New chat
          </button>
        </div>

        {/* Repository Ingestion Panel */}
        <div className="px-3.5">
          <button
            onClick={() => setIsIngestPanelOpen(!isIngestPanelOpen)}
            className="flex w-full items-center justify-between rounded-xl border border-zinc-800/60 bg-zinc-900/40 hover:bg-zinc-800/40 px-3 py-2 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-all duration-200"
          >
            <div className="flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-teal-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <span>Ingest Repository</span>
            </div>
            <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${isIngestPanelOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {isIngestPanelOpen && (
            <div className="mt-2 rounded-xl border border-zinc-800/60 bg-zinc-900/50 p-3 space-y-2.5 animate-in slide-in-from-top-1 duration-200">
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                GitHub Repository URL
              </label>
              <input
                type="url"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleIngestRepository(); }}
                placeholder="https://github.com/owner/repo"
                disabled={isIngesting}
                className="w-full rounded-lg border border-zinc-700/60 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-teal-500/60 focus:ring-1 focus:ring-teal-500/30 transition-all disabled:opacity-50"
              />
              <button
                onClick={handleIngestRepository}
                disabled={!repoUrl.trim() || isIngesting}
                className={`flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all duration-200 ${isIngesting
                    ? "bg-teal-600/20 text-teal-400 border border-teal-500/30 cursor-wait"
                    : repoUrl.trim()
                      ? "bg-gradient-to-r from-teal-600 to-emerald-600 hover:from-teal-500 hover:to-emerald-500 text-white shadow-md shadow-teal-900/30 active:scale-[0.98]"
                      : "bg-zinc-800/60 text-zinc-600 border border-zinc-800 cursor-not-allowed"
                  }`}
              >
                {isIngesting ? (
                  <>
                    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Ingesting...
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Ingest Repository
                  </>
                )}
              </button>

              {/* Result Feedback */}
              {ingestResult && (
                <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-[11px] leading-relaxed border ${ingestResult.type === "success"
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                    : "bg-red-500/10 text-red-400 border-red-500/20"
                  }`}>
                  {ingestResult.type === "success" ? (
                    <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  )}
                  <span>{ingestResult.message}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sidebar Navigation / Chat History */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
          <div>
            <span className="px-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Recent Chats</span>
            <div className="mt-2 space-y-1">
              {sessions.map((session) => (
                <button
                  key={session.id}
                  onClick={() => setActiveSession(session.id)}
                  className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-all group ${activeSession === session.id
                      ? "bg-zinc-850 text-white font-medium shadow-sm border-l-2 border-emerald-500 pl-2.5"
                      : "hover:bg-zinc-900/60 text-zinc-400 hover:text-zinc-200"
                    }`}
                >
                  <span className="truncate max-w-[180px]">{session.title}</span>
                  <span className="text-[10px] text-zinc-600 group-hover:text-zinc-400 transition-colors">
                    {session.timestamp}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar Footer Controls */}
        <div className="border-t border-zinc-805 border-zinc-800 p-4 bg-zinc-950/80 backdrop-blur-md space-y-3.5">
          {/* API Status Indicator */}
          <div className="flex items-center justify-between rounded-lg bg-zinc-900/80 px-3 py-2 border border-zinc-800/60">
            <span className="text-xs text-zinc-400">FastAPI Backend</span>
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${apiConnected === "connected"
                    ? "bg-emerald-500 animate-pulse"
                    : apiConnected === "demo"
                      ? "bg-amber-500"
                      : "bg-red-500 animate-pulse"
                  }`}
              />
              <span className="text-[11px] font-medium capitalize text-zinc-300">
                {apiConnected === "connected" ? "Online" : apiConnected === "demo" ? "Demo Mode" : "Offline"}
              </span>
            </div>
          </div>

          {/* User Settings & Theme Controls */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-white font-semibold text-xs shadow-md">
                {authUsername.slice(0, 2).toUpperCase()}
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-medium text-white leading-none">{authUsername}</span>
                <span className="text-[10px] text-zinc-500">GitHub · Developer</span>
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setIsDarkMode(!isDarkMode)}
                className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-800 hover:text-white transition-colors"
                title="Toggle Theme"
              >
                {isDarkMode ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m0-12.728l.707.707m12.728 12.728l.707-.707M12 8a4 4 0 100 8 4 4 0 000-8z" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
                )}
              </button>
              {/* Logout button */}
              <button
                id="logout-btn"
                onClick={() => { clearAuthToken(); router.replace("/login"); }}
                className="rounded-lg p-2 text-zinc-400 hover:bg-red-900/40 hover:text-red-400 transition-colors"
                title="Sign out"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* Mobile Sidebar Overlay Backdrop */}
      {isSidebarOpen && (
        <div
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 z-20 bg-zinc-950/60 backdrop-blur-sm md:hidden"
        />
      )}

      {/* MAIN CHAT CONTENT AREA */}
      <main className="relative flex flex-1 flex-col overflow-hidden h-full">
        {/* Navigation Top Header */}
        <header className={`flex h-14 items-center justify-between border-b px-4 ${isDarkMode ? "border-zinc-800/80 bg-zinc-900/60" : "border-zinc-200 bg-white"
          } backdrop-blur-md`}>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className={`rounded-lg p-2 transition-colors ${isDarkMode ? "hover:bg-zinc-800 text-zinc-400 hover:text-white" : "hover:bg-zinc-150 text-zinc-500 hover:text-zinc-900"
                }`}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>

            {/* Model Name Select (ChatGPT styling) */}
            <div className={`flex items-center gap-1.5 rounded-xl px-3 py-1 text-sm font-medium ${isDarkMode ? "hover:bg-zinc-800/60 text-zinc-300" : "hover:bg-zinc-100 text-zinc-700"
              } cursor-pointer transition-colors`}>
              <span>Gemini 3.5 Flash</span>
              <svg className="w-4 h-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Quick action buttons on Header */}
            {apiConnected === "demo" && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-500 border border-amber-500/20 animate-pulse">
                Demo Fallback
              </span>
            )}
            <div className={`text-xs ${isDarkMode ? "text-zinc-500" : "text-zinc-400"} select-none hidden sm:block`}>
              Active Session: <code className="font-mono text-zinc-400 dark:text-zinc-300">{activeSession}</code>
            </div>
          </div>
        </header>

        {/* Scrollable Message History Area */}
        <div className={`flex-1 overflow-y-auto px-4 py-6 md:px-8 space-y-6 scrollbar-thin ${isDarkMode ? "scrollbar-thumb-zinc-800" : "scrollbar-thumb-zinc-300"
          } scrollbar-track-transparent`}>
          {messages.length === 0 ? (
            /* Empty State Screen (ChatGPT Style Dashboard) */
            <div className="mx-auto flex max-w-2xl flex-col items-center justify-center pt-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-lg mb-6">
                <svg className="w-6 h-6 text-white animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                </svg>
              </div>
              <h2 className={`text-2xl font-bold tracking-tight ${isDarkMode ? "text-white" : "text-zinc-900"} md:text-3xl`}>
                How can I help you today?
              </h2>
              <p className={`mt-2.5 text-sm ${isDarkMode ? "text-zinc-400" : "text-zinc-500"} max-w-md`}>
                Ask about SSE stream integration, setup FastAPI parameters, or design clean Next.js UI flows.
              </p>

              {/* Grid Suggestions Cards */}
              <div className="mt-8 grid w-full grid-cols-1 gap-3.5 sm:grid-cols-2">
                {[
                  {
                    title: "Explain SSE Streaming",
                    desc: "How do Server-Sent Events work in client components?",
                    prompt: "Can you explain how SSE streaming works and write a basic client-side decoder implementation?",
                  },
                  {
                    title: "FastAPI Backend Router",
                    desc: "Generate a chat stream generator in Python",
                    prompt: "Show me a complete FastAPI endpoint that accepts user query and streams back words using SSE.",
                  },
                  {
                    title: "Next.js State Management",
                    desc: "Tips to avoid rerender loops in inputs",
                    prompt: "What are some best practices for managing real-time chat input states and scrolling behaviors in React?",
                  },
                  {
                    title: "Visual Differentiating UI",
                    desc: "Tailwind techniques for chat styling",
                    prompt: "Give me ideas on how to differentiate user and AI messages visually in a Tailwind CSS dashboard.",
                  },
                ].map((card, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setInput(card.prompt);
                      textareaRef.current?.focus();
                    }}
                    className={`flex flex-col rounded-2xl border p-4 text-left transition-all duration-200 shadow-sm ${isDarkMode
                        ? "border-zinc-800 bg-zinc-950/40 hover:bg-zinc-800/40 text-zinc-300"
                        : "border-zinc-200 bg-white hover:bg-zinc-100 text-zinc-700"
                      }`}
                  >
                    <span className={`font-semibold text-xs ${isDarkMode ? "text-white" : "text-zinc-900"}`}>
                      {card.title}
                    </span>
                    <span className="mt-1 text-[11px] opacity-80 leading-relaxed">{card.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* Filled Message History List */
            <div className="mx-auto max-w-3xl space-y-6">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex w-full flex-col ${message.role === "user" ? "items-end" : "items-start"
                    }`}
                >
                  <div
                    className={`flex max-w-[85%] gap-3.5 ${message.role === "user" ? "flex-row-reverse" : "flex-row"
                      }`}
                  >
                    {/* Role Avatar */}
                    <div className="flex h-8.5 w-8.5 shrink-0 select-none items-center justify-center rounded-lg shadow-sm">
                      {message.role === "user" ? (
                        <div className="flex h-full w-full items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-indigo-600 text-[11px] font-semibold text-white">
                          {authUsername.slice(0, 2).toUpperCase()}
                        </div>
                      ) : (
                        <div className="flex h-full w-full items-center justify-center rounded-lg bg-gradient-to-br from-emerald-400 to-teal-500 text-white">
                          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364.364l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                          </svg>
                        </div>
                      )}
                    </div>

                    {/* Chat Bubble content wrapper */}
                    <div className="flex flex-col">
                      <span className={`text-[10px] ${isDarkMode ? "text-zinc-500" : "text-zinc-400"} font-medium mb-1 px-1.5`}>
                        {message.role === "user" ? "You" : "Antigravity AI"}
                      </span>
                      <div
                        className={`rounded-2xl px-4 py-3 text-sm shadow-sm leading-relaxed ${message.role === "user"
                            ? isDarkMode
                              ? "bg-zinc-800 text-zinc-100 rounded-tr-sm"
                              : "bg-indigo-600 text-white rounded-tr-sm"
                            : isDarkMode
                              ? "bg-zinc-950/60 text-zinc-100 border border-zinc-800 rounded-tl-sm"
                              : "bg-white text-zinc-800 border border-zinc-200/85 rounded-tl-sm"
                          }`}
                      >
                        <div className="space-y-2">
                          {renderMessageContent(message.content)}
                          {message.isStreaming && message.content === "" && (
                            /* Loading Dot indicator before text streams in */
                            <div className="flex space-x-1 py-1 items-center">
                              <div className="h-2 w-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                              <div className="h-2 w-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                              <div className="h-2 w-2 bg-emerald-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                            </div>
                          )}
                          {message.isStreaming && message.content !== "" && (
                            <span className="cursor-blink" />
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* BOTTOM INPUT CONTAINER */}
        <div className={`border-t p-4 ${isDarkMode ? "border-zinc-800/80 bg-zinc-900/40" : "border-zinc-200 bg-zinc-50/70"
          } backdrop-blur-md`}>
          <div className="mx-auto max-w-3xl">
            <div className={`relative flex items-center rounded-2xl border shadow-md focus-within:ring-2 focus-within:ring-emerald-500/50 ${isDarkMode
                ? "border-zinc-800 bg-zinc-950 focus-within:border-zinc-700"
                : "border-zinc-250 bg-white focus-within:border-zinc-300"
              }`}>
              {/* Attachment Placeholder */}
              <button
                className={`ml-2.5 rounded-lg p-2.5 transition-colors ${isDarkMode ? "hover:bg-zinc-850 text-zinc-500 hover:text-zinc-300" : "hover:bg-zinc-100 text-zinc-400 hover:text-zinc-600"
                  }`}
                title="Mock Attachment"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
              </button>

              {/* Text Input area */}
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Message Antigravity..."
                className="flex-1 resize-none overflow-y-auto bg-transparent px-3 py-3.5 text-sm outline-none placeholder:text-zinc-500 max-h-[200px]"
                style={{
                  color: isDarkMode ? "#f4f4f5" : "#18181b",
                }}
              />

              {/* Send or Stop Generation CTA button */}
              <div className="mr-2.5 flex items-center">
                {isStreaming ? (
                  <button
                    onClick={handleStopGeneration}
                    className="flex h-8.5 w-8.5 items-center justify-center rounded-xl bg-red-600 hover:bg-red-500 text-white shadow-md transition-all active:scale-95"
                    title="Stop Generating"
                  >
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                      <rect x="6" y="6" width="12" height="12" rx="1.5" />
                    </svg>
                  </button>
                ) : (
                  <button
                    onClick={() => handleSendMessage()}
                    disabled={!input.trim()}
                    className={`flex h-8.5 w-8.5 items-center justify-center rounded-xl transition-all shadow-md active:scale-95 ${input.trim()
                        ? "bg-emerald-500 hover:bg-emerald-400 text-white cursor-pointer"
                        : "bg-zinc-800 text-zinc-600 cursor-not-allowed border border-zinc-850"
                      }`}
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                    </svg>
                  </button>
                )}
              </div>
            </div>

            {/* Bottom Credits info */}
            <p className={`mt-2 text-center text-[10px] ${isDarkMode ? "text-zinc-600" : "text-zinc-400"
              }`}>
              Antigravity Chat UI can make mistakes. FastAPI stream session config active at <code>http://127.0.0.1:8000/chat/session_123</code>.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

/* CUSTOM RENDER COMPONENTS */

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
    <div className="my-4 overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800/80 bg-zinc-950 font-mono text-sm leading-relaxed shadow-sm">
      <div className="flex items-center justify-between bg-zinc-900 px-4 py-2 text-xs text-zinc-400 select-none border-b border-zinc-800/50">
        <span className="font-semibold uppercase tracking-wider text-[10px] text-zinc-500">{language || "code"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-white transition-colors"
        >
          {copied ? (
            <>
              <svg className="w-3.5 h-3.5 text-emerald-400 animate-scale" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-[10px] text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
              </svg>
              <span className="text-[10px] font-medium">Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-zinc-200">
        <code className="text-zinc-200 select-all">{code.trim()}</code>
      </pre>
    </div>
  );
}
