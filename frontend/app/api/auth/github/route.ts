/**
 * app/api/auth/github/route.ts
 * ----------------------------
 * Next.js Route Handler that proxies the GitHub OAuth code exchange to the
 * FastAPI backend. The browser calls this same-origin endpoint (no CORS),
 * and this handler calls FastAPI server-to-server (also no CORS).
 *
 * Browser  →  POST /api/auth/github  →  Next.js Route Handler
 *                                              ↓  server-to-server
 *                                     POST http://localhost:8000/api/auth/github
 */

import { NextRequest, NextResponse } from "next/server";

// Use 127.0.0.1 explicitly — on Windows, 'localhost' can resolve to ::1 (IPv6)
// but uvicorn only listens on 127.0.0.1 (IPv4), causing ECONNREFUSED.
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  try {
    // 1. Parse the code from the browser's request body
    const body = await request.json();
    const { code } = body as { code?: string };

    if (!code) {
      return NextResponse.json(
        { detail: "Missing authorization code" },
        { status: 400 }
      );
    }

    console.log("[Route /api/auth/github] Forwarding code to FastAPI…");

    // 2. Forward to FastAPI — no CORS, this is pure server-to-server
    //    Retry up to 3 times to handle transient SocketErrors caused by
    //    uvicorn --reload restarting mid-request.
    const MAX_RETRIES = 3;
    let backendResponse: Response | null = null;
    let lastError: unknown = null;

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        backendResponse = await fetch(
          `${BACKEND_URL}/api/auth/github`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify({ code }),
          }
        );
        break; // success — exit retry loop
      } catch (err) {
        lastError = err;
        console.warn(
          `[Route /api/auth/github] Attempt ${attempt}/${MAX_RETRIES} failed:`,
          err instanceof Error ? err.message : err
        );
        if (attempt < MAX_RETRIES) {
          // Exponential backoff: 500ms, 1000ms
          await new Promise((r) => setTimeout(r, 500 * attempt));
        }
      }
    }

    if (!backendResponse) {
      console.error("[Route /api/auth/github] All retries exhausted:", lastError);
      return NextResponse.json(
        {
          detail:
            lastError instanceof Error
              ? lastError.message
              : "Could not reach FastAPI backend after retries",
        },
        { status: 502 }
      );
    }

    const data = await backendResponse.json();

    console.log(
      "[Route /api/auth/github] FastAPI responded:",
      backendResponse.status,
      backendResponse.ok ? "OK" : data?.detail ?? "error"
    );

    // 3. Relay the exact status and body back to the browser
    return NextResponse.json(data, { status: backendResponse.status });
  } catch (err) {
    console.error("[Route /api/auth/github] Proxy error:", err);
    return NextResponse.json(
      {
        detail:
          err instanceof Error
            ? err.message
            : "Proxy error: could not reach FastAPI backend",
      },
      { status: 502 }
    );
  }
}
