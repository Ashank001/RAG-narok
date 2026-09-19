"use client";

import React, { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { postAgentTask } from "@/lib/api";

interface AgentPanelProps {
  activeSession: string | null;
  onError: (message: string) => void;
}

type AgentStatus = "idle" | "running" | "completed" | "error";

interface AgentState {
  status: AgentStatus;
  stage: string | null;
  message: string | null;
  prUrl: string | null;
  errorDetails: string | null;
}

export default function AgentPanel({ activeSession, onError }: AgentPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [task, setTask] = useState("");
  const [agentState, setAgentState] = useState<AgentState>({
    status: "idle",
    stage: null,
    message: null,
    prUrl: null,
    errorDetails: null,
  });
  
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleSubmit = async () => {
    if (!task.trim() || !activeSession || agentState.status === "running") return;
    
    setAgentState({
      status: "running",
      stage: "INITIALIZING",
      message: "Starting autonomous agent...",
      prUrl: null,
      errorDetails: null,
    });
    
    abortControllerRef.current = new AbortController();
    
    try {
      const response = await postAgentTask(activeSession, { task }, abortControllerRef.current.signal);
      
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }
      
      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");
      
      const decoder = new TextDecoder();
      let buffer = "";
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        
        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed.startsWith("data:")) continue;
          
          try {
            const dataStr = trimmed.substring(5).trim();
            const event = JSON.parse(dataStr);
            
            if (event.stage === "COMPLETED") {
              setAgentState(prev => ({
                ...prev,
                status: "completed",
                stage: event.stage,
                message: event.message,
                prUrl: event.pr_url
              }));
              return;
            } else if (event.stage === "ERROR") {
              setAgentState(prev => ({
                ...prev,
                status: "error",
                stage: event.stage,
                message: event.message,
                errorDetails: event.details
              }));
              return;
            }
            
            setAgentState(prev => ({
              ...prev,
              stage: event.stage,
              message: event.message
            }));
            
          } catch (e) {
            console.warn("Failed to parse agent event", trimmed, e);
          }
        }
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        setAgentState(prev => ({
          ...prev,
          status: "idle",
          message: "Cancelled by user"
        }));
      } else {
        setAgentState(prev => ({
          ...prev,
          status: "error",
          message: "Connection failed",
          errorDetails: err.message
        }));
        onError(err.message);
      }
    }
  };

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  return (
    <div className="px-3 pb-3">
      <div className="rounded-xl border border-[#1e1e1e] bg-[#111111] overflow-hidden">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex w-full items-center justify-between p-3 text-sm font-medium text-zinc-300 hover:text-white hover:bg-[#1a1a1a] transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            Auto Coder
          </div>
          <svg
            className={`w-4 h-4 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="px-3 pb-3 pt-1 border-t border-[#1e1e1e]"
            >
              {!activeSession ? (
                <div className="text-xs text-zinc-500 text-center py-2">
                  Select a session to use the Auto Coder
                </div>
              ) : (
                <div className="space-y-3">
                  {agentState.status === "idle" || agentState.status === "completed" || agentState.status === "error" ? (
                    <>
                      <textarea
                        value={task}
                        onChange={(e) => setTask(e.target.value)}
                        placeholder="E.g., Add a dark mode toggle to the header..."
                        className="w-full rounded-lg border border-[#2a2a2a] bg-[#1a1a1a] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500 resize-none h-20"
                      />
                      <button
                        onClick={handleSubmit}
                        disabled={!task.trim()}
                        className="w-full rounded-lg bg-purple-600 hover:bg-purple-500 px-3 py-2 text-xs font-semibold text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Start Agent
                      </button>
                    </>
                  ) : null}

                  {agentState.status === "running" && (
                    <div className="space-y-2 p-2 rounded-lg bg-[#1a1a1a] border border-[#2a2a2a]">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 border-2 border-purple-500 border-t-transparent rounded-full animate-spin shrink-0" />
                        <span className="text-xs font-mono font-medium text-purple-400">
                          {agentState.stage}
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-400 break-words whitespace-pre-wrap">
                        {agentState.message}
                      </p>
                      <button
                        onClick={handleCancel}
                        className="w-full rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 py-1 text-xs mt-2 transition-colors"
                      >
                        Cancel Task
                      </button>
                    </div>
                  )}

                  {agentState.status === "completed" && (
                    <div className="p-2 rounded-lg border border-green-500/30 bg-green-500/10">
                      <p className="text-xs font-medium text-green-400 mb-2">
                        Success!
                      </p>
                      {agentState.prUrl && (
                        <a 
                          href={agentState.prUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 text-[10px] text-blue-400 hover:underline"
                        >
                          View Pull Request
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                          </svg>
                        </a>
                      )}
                    </div>
                  )}

                  {agentState.status === "error" && (
                    <div className="p-2 rounded-lg border border-red-500/30 bg-red-500/10">
                      <p className="text-xs font-medium text-red-400">
                        Agent Failed
                      </p>
                      <p className="text-[10px] text-zinc-300 mt-1">
                        {agentState.message}
                      </p>
                      {agentState.errorDetails && (
                        <details className="mt-2 text-[10px] text-zinc-500 cursor-pointer">
                          <summary className="hover:text-zinc-300">View details</summary>
                          <pre className="mt-1 p-1 bg-black rounded overflow-x-auto whitespace-pre-wrap font-mono">
                            {agentState.errorDetails}
                          </pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
