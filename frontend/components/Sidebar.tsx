"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import IngestPanel from "./IngestPanel";
import { getUsername, getAvatarUrl, clearAuthToken } from "@/lib/auth";
import { useRouter } from "next/navigation";

interface ChatSession {
  id: string;
  title: string;
  repoUrl?: string;
  timestamp: string;
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  activeSession: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onSessionReady: (sessionId: string, repoUrl: string) => void;
  onError: (message: string) => void;
}



const itemVariants = {
  hidden: { opacity: 0, x: -12 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.04, duration: 0.25, ease: "easeOut" as const },
  }),
};

export default function Sidebar({
  isOpen,
  onClose,
  sessions,
  activeSession,
  onSelectSession,
  onNewChat,
  onSessionReady,
  onError,
}: SidebarProps) {
  const router = useRouter();
  const username = getUsername() || "User";
  const avatarUrl = getAvatarUrl(username);

  const handleLogout = () => {
    clearAuthToken();
    router.replace("/login");
  };

  return (
    <>
      {/* Mobile Overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[280px] flex-col border-r border-[#1e1e1e] bg-[#0a0a0a] transition-transform duration-300 ease-in-out lg:static lg:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between px-4 border-b border-[#1e1e1e]">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#00ff88] to-emerald-500 shadow-lg shadow-[#00ff88]/10">
              <svg
                className="w-4.5 h-4.5 text-black"
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
            <span className="font-semibold text-white tracking-wide text-sm font-mono">
              RAGnarok
            </span>
          </div>

          {/* Close button — mobile only */}
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-500 hover:bg-[#1a1a1a] hover:text-white transition-colors lg:hidden"
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
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3">
          <button
            onClick={onNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#1e1e1e] bg-[#111111] hover:bg-[#1a1a1a] hover:border-[#2a2a2a] px-4 py-2.5 text-sm font-medium text-white transition-all duration-200 group"
          >
            <svg
              className="w-4 h-4 text-[#00ff88] group-hover:rotate-90 transition-transform duration-200"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 4v16m8-8H4"
              />
            </svg>
            New Chat
          </button>
        </div>

        {/* Ingest Panel */}
        <IngestPanel onSessionReady={onSessionReady} onError={onError} />

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {sessions.length > 0 && (
            <div>
              <span className="px-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                Recent Chats
              </span>
              <div className="mt-2 space-y-0.5">
                {sessions.map((session, i) => (
                  <motion.button
                    key={session.id}
                    custom={i}
                    initial="hidden"
                    animate="visible"
                    variants={itemVariants}
                    onClick={() => onSelectSession(session.id)}
                    className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-all group ${
                      activeSession === session.id
                        ? "bg-[#00ff88]/8 text-white font-medium border-l-2 border-[#00ff88] pl-2.5"
                        : "hover:bg-[#111111] text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    <span className="truncate max-w-[170px] font-mono text-xs">
                      {session.title}
                    </span>
                    <span className="text-[10px] text-zinc-600 group-hover:text-zinc-400 transition-colors">
                      {session.timestamp}
                    </span>
                  </motion.button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer — User Info + Logout */}
        <div className="border-t border-[#1e1e1e] p-4 bg-[#0a0a0a]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={username}
                  className="h-8 w-8 rounded-full ring-1 ring-[#2a2a2a]"
                />
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent-indigo to-purple-600 text-white font-semibold text-xs">
                  {username.slice(0, 2).toUpperCase()}
                </div>
              )}
              <div className="flex flex-col">
                <span className="text-sm font-medium text-white leading-none">
                  {username}
                </span>
                <span className="text-[10px] text-zinc-600">GitHub</span>
              </div>
            </div>

            <button
              id="logout-btn"
              onClick={handleLogout}
              className="rounded-lg p-2 text-zinc-500 hover:bg-red-500/10 hover:text-red-400 transition-colors"
              title="Sign out"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                />
              </svg>
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
