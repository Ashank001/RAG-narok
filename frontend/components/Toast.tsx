"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

export type ToastType = "error" | "success" | "warning" | "info";

export interface ToastData {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastProps {
  toasts: ToastData[];
  onDismiss: (id: string) => void;
}

const typeStyles: Record<ToastType, { bg: string; border: string; icon: string }> = {
  error: {
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    icon: "text-red-400",
  },
  warning: {
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    icon: "text-amber-400",
  },
  success: {
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    icon: "text-emerald-400",
  },
  info: {
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    icon: "text-blue-400",
  },
};

function ToastIcon({ type }: { type: ToastType }) {
  if (type === "error" || type === "warning") {
    return (
      <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
      </svg>
    );
  }
  if (type === "success") {
    return (
      <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    );
  }
  return (
    <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

export default function Toast({ toasts, onDismiss }: ToastProps) {
  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastData; onDismiss: (id: string) => void }) {
  const styles = typeStyles[toast.type];

  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(toast.id);
    }, toast.duration || 5000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onDismiss]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 80, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 80, scale: 0.95 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={`pointer-events-auto flex items-start gap-3 rounded-xl border ${styles.bg} ${styles.border} backdrop-blur-md px-4 py-3 shadow-2xl shadow-black/30`}
    >
      <span className={`mt-0.5 ${styles.icon}`}>
        <ToastIcon type={toast.type} />
      </span>
      <p className="flex-1 text-sm text-zinc-200 leading-relaxed">{toast.message}</p>
      <button
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 rounded-md p-1 text-zinc-500 hover:text-zinc-300 hover:bg-white/5 transition-colors"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Hook for managing toasts
// ---------------------------------------------------------------------------

export function useToast() {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  const addToast = (type: ToastType, message: string, duration?: number) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, type, message, duration }]);
  };

  const dismissToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return { toasts, addToast, dismissToast };
}
