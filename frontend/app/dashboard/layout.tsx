"use client";

/**
 * app/dashboard/layout.tsx
 * -------------------------
 * Dashboard layout — auth guard + sidebar + main content area.
 * Wraps all /dashboard/* routes.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      setIsAuthed(true);
    }
  }, [router]);

  // Don't render anything until auth is verified
  if (!isAuthed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a]">
        <div className="relative flex h-12 w-12 items-center justify-center">
          <div className="absolute inset-0 rounded-full border-2 border-[#1e1e1e]" />
          <div className="absolute inset-0 animate-spin rounded-full border-t-2 border-[#00ff88]" />
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
