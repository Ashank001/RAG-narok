"use client";

/**
 * app/dashboard/page.tsx
 * -----------------------
 * Main dashboard page — orchestrates the sidebar, chat window, and all state.
 * Handles SSE streaming, demo mode fallback, session management.
 */

import React, { useState, useEffect, useRef, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import ChatWindow, { type Message, type IngestStep } from "@/components/ChatWindow";
import Toast, { useToast } from "@/components/Toast";
import { getUsername } from "@/lib/auth";
import { apiFetch } from "@/lib/api";

interface ChatSession {
  id: string;
  title: string;
  repoUrl?: string;
  timestamp: string;
}

export default function DashboardPage() {
  const username = getUsername() || "User";

  // Sidebar
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [activeRepoUrl, setActiveRepoUrl] = useState<string | null>(null);

  // Load sessions from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem("ragnarok_sessions");
      if (saved) {
        setSessions(JSON.parse(saved));
      }
      const active = localStorage.getItem("ragnarok_active_session");
      if (active) {
        setActiveSession(active);
        const savedUrl = localStorage.getItem("ragnarok_active_repo");
        if (savedUrl) setActiveRepoUrl(savedUrl);
      }
    } catch (e) {
      console.error("Failed to load sessions from localStorage", e);
    }
  }, []);

  // Save sessions to localStorage whenever they change
  useEffect(() => {
    localStorage.setItem("ragnarok_sessions", JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    if (activeSession) {
      localStorage.setItem("ragnarok_active_session", activeSession);
    } else {
      localStorage.removeItem("ragnarok_active_session");
    }
  }, [activeSession]);

  useEffect(() => {
    if (activeRepoUrl) {
      localStorage.setItem("ragnarok_active_repo", activeRepoUrl);
    } else {
      localStorage.removeItem("ragnarok_active_repo");
    }
  }, [activeRepoUrl]);

  // Chat
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Ingestion progress
  const [ingestStep, setIngestStep] = useState<IngestStep | null>(null);
  const [ingestRepoUrl, setIngestRepoUrl] = useState<string | null>(null);

  // Demo mode
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);

  // Toast
  const { toasts, addToast, dismissToast } = useToast();

  // Check API on first chat attempt
  const checkApiOnce = useRef(false);
  const ensureApiCheck = useCallback(async () => {
    if (checkApiOnce.current) return apiConnected;
    checkApiOnce.current = true;
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      await apiFetch("/health", { method: "GET", signal: controller.signal });
      clearTimeout(timeoutId);
      setApiConnected(true);
      return true;
    } catch {
      setApiConnected(false);
      return false;
    }
  }, [apiConnected]);

  // ---------------------------------------------------------------------------
  // Session management
  // ---------------------------------------------------------------------------

  const handleNewChat = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setMessages([]);
    setInput("");
    setActiveSession(null);
    setActiveRepoUrl(null);
    setIngestStep(null);
    setIngestRepoUrl(null);
    setIsStreaming(false);
    setIsSidebarOpen(false);
  };

  const handleSelectSession = (id: string) => {
    const session = sessions.find((s) => s.id === id);
    if (session) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      setActiveSession(session.id);
      setActiveRepoUrl(session.repoUrl || null);
      setMessages([]);
      setInput("");
      setIsStreaming(false);
      setIngestStep(null);
      setIngestRepoUrl(null);
      setIsSidebarOpen(false);
    }
  };

  const handleSessionReady = (sessionId: string, repoUrl: string) => {
    setActiveSession(sessionId);
    setActiveRepoUrl(repoUrl);
    setIngestStep(null);
    setIngestRepoUrl(null);
    setMessages([]);

    // Add to sessions list
    const repoName = repoUrl.replace("https://github.com/", "");
    setSessions((prev) => {
      const exists = prev.find((s) => s.id === sessionId);
      if (exists) return prev;
      return [
        { id: sessionId, title: repoName, repoUrl, timestamp: "Just now" },
        ...prev,
      ];
    });
  };

  const handleError = useCallback(
    (message: string) => {
      addToast("error", message);
    },
    [addToast]
  );

  // ---------------------------------------------------------------------------
  // SSE Streaming Chat
  // ---------------------------------------------------------------------------

  const handleSendMessage = async (textToSend?: string) => {
    const queryText = (textToSend || input).trim();
    if (!queryText || isStreaming) return;

    if (!textToSend) {
      setInput("");
    }

    // If no active session, we need one to chat
    if (!activeSession) {
      addToast(
        "warning",
        "Please ingest a repository first, or select an existing chat session."
      );
      return;
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

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    // Check API connectivity
    const isConnected = await ensureApiCheck();

    if (!isConnected) {
      simulateStreamingResponse(queryText, assistantPlaceholder.id);
      return;
    }

    try {
      const response = await apiFetch(`/chat/${activeSession}`, {
        method: "POST",
        body: JSON.stringify({ query: queryText }),
        signal: abortController.signal,
        rawResponse: true,
      });

      if (!response.ok) {
        let errorDetail = `${response.status} ${response.statusText}`;
        try {
          const json = await response.clone().json();
          if (json?.detail) errorDetail = json.detail;
        } catch {
          /* body not JSON */
        }

        if (response.status === 401) {
          addToast("error", "Session expired. Please log in again.");
          return;
        }
        if (response.status === 429) {
          addToast(
            "warning",
            "Daily query limit reached. Resets at midnight."
          );
          return;
        }
        throw new Error(`Backend error: ${errorDetail}`);
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
        buffer = parts.pop() || "";

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed) continue;

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
    } catch (error: unknown) {
      if (error instanceof Error && error.name === "AbortError") {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantPlaceholder.id
              ? {
                  ...msg,
                  content:
                    msg.content +
                    "\n\n*[Response generation cancelled by user]*",
                }
              : msg
          )
        );
      } else {
        const errorMessage =
          error instanceof Error ? error.message : "Unknown error";
        console.error("Fetch error:", error);
        addToast("error", `Connection failed: ${errorMessage}`);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantPlaceholder.id
              ? {
                  ...msg,
                  content: `⚠️ Connection failed.\n\n${errorMessage}`,
                }
              : msg
          )
        );
      }
    } finally {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantPlaceholder.id
            ? { ...msg, isStreaming: false }
            : msg
        )
      );
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  };

  // ---------------------------------------------------------------------------
  // Demo mode simulation
  // ---------------------------------------------------------------------------

  const simulateStreamingResponse = (query: string, placeholderId: string) => {
    let mockResponse = "";
    const lowerQuery = query.toLowerCase();

    if (lowerQuery.includes("architect")) {
      mockResponse = `## Architecture Overview\n\nThis codebase follows a **layered architecture** with clear separation of concerns:\n\n### Layers\n1. **API Layer** — Handles HTTP requests and routing\n2. **Service Layer** — Business logic and orchestration\n3. **Data Layer** — Database models and repositories\n\n\`\`\`\n┌──────────────┐\n│   API Layer  │\n├──────────────┤\n│ Service Layer│\n├──────────────┤\n│  Data Layer  │\n└──────────────┘\n\`\`\`\n\nThe application uses **dependency injection** for loose coupling between layers.\n\n*Note: Running in Demo Mode — connect the backend to analyze your actual codebase.*`;
    } else if (lowerQuery.includes("bug")) {
      mockResponse = `## Potential Issues Found\n\n### 1. Missing Error Handling\n\`\`\`python\n# ⚠️ Current code\nasync def process_request(data):\n    result = await db.query(data)  # No try/catch!\n    return result\n\n# ✅ Recommended fix\nasync def process_request(data):\n    try:\n        result = await db.query(data)\n        return result\n    except DatabaseError as e:\n        logger.error(f"Query failed: {e}")\n        raise HTTPException(status_code=500)\n\`\`\`\n\n### 2. No Input Validation\nUser input is not sanitized before database queries.\n\n*Running in Demo Mode*`;
    } else {
      mockResponse = `I received your query: **"${query}"**.\n\nSince the FastAPI backend is offline, I'm running in **Demo Mode**.\n\nHere's what RAGnarok can do with a connected backend:\n\n- **Semantic code search** across your entire repository\n- **Architecture analysis** with dependency graphs\n- **Bug detection** with fix suggestions\n- **Function explanations** with usage examples\n- **Streaming responses** for real-time interaction\n\nTo get started, make sure your backend is running at \`http://127.0.0.1:8000\` and ingest a repository!`;
    }

    const words = mockResponse.split(/( )/);
    let index = 0;

    const interval = setInterval(() => {
      if (abortControllerRef.current?.signal.aborted) {
        clearInterval(interval);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === placeholderId
              ? {
                  ...msg,
                  content:
                    msg.content +
                    "\n\n*[Response generation cancelled by user]*",
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
            msg.id === placeholderId
              ? { ...msg, content: msg.content + nextWord }
              : msg
          )
        );
        index++;
      }
    }, 20);
  };

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[#0a0a0a] text-zinc-100">
      <Toast toasts={toasts} onDismiss={dismissToast} />

      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        sessions={sessions}
        activeSession={activeSession}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onSessionReady={handleSessionReady}
        onError={handleError}
      />

      <ChatWindow
        messages={messages}
        input={input}
        onInputChange={setInput}
        onSend={handleSendMessage}
        onStopGeneration={handleStopGeneration}
        isStreaming={isStreaming}
        username={username}
        activeSession={activeSession}
        activeRepoUrl={activeRepoUrl}
        ingestStep={ingestStep}
        ingestRepoUrl={ingestRepoUrl}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
      />
    </div>
  );
}
