/**
 * lib/api.ts
 * ----------
 * A typed fetch wrapper that automatically attaches the stored JWT to
 * every request that goes to the FastAPI backend.
 *
 * Usage:
 *   import { apiFetch } from "@/lib/api";
 *
 *   // Streaming chat (SSE)
 *   const response = await apiFetch(`/chat/${sessionId}`, {
 *     method: "POST",
 *     body: JSON.stringify({ query }),
 *   });
 *
 *   // Ingestion
 *   const data = await apiFetch("/api/ingest", {
 *     method: "POST",
 *     body: JSON.stringify({ repositoryUrl }),
 *   });
 */

import { getAuthToken } from "./auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/**
 * Wrapper around the native fetch API.
 * Automatically adds:
 *  - `Content-Type: application/json` (unless body is FormData)
 *  - `Authorization: Bearer <token>` if a token exists in localStorage
 *
 * Throws on HTTP errors so callers can catch and handle them.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = getAuthToken();

  const headers = new Headers(init.headers);

  // Only set Content-Type when sending JSON (not FormData/multipart)
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    // Attempt to parse a JSON error body from FastAPI
    let errorDetail = `${response.status} ${response.statusText}`;
    try {
      const json = await response.clone().json();
      if (json?.detail) errorDetail = json.detail;
    } catch {
      // Body is not JSON — keep the status string
    }
    throw new Error(errorDetail);
  }

  return response;
}

// ---------------------------------------------------------------------------
// Typed helpers for specific endpoints
// ---------------------------------------------------------------------------

export interface ChatRequestBody {
  query: string;
}

/**
 * POST /chat/{sessionId}
 * Returns the raw Response so the caller can stream SSE chunks.
 */
export async function postChatMessage(
  sessionId: string,
  body: ChatRequestBody,
  signal?: AbortSignal
): Promise<Response> {
  return apiFetch(`/chat/${sessionId}`, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

export interface IngestRequestBody {
  sessionId: string;
  repositoryUrl: string;
}

export interface IngestResponseBody {
  sessionId: string;
  message?: string;
}

/**
 * POST /api/ingest
 * Queues a repository for RAG ingestion.
 */
export async function postIngestRepository(
  body: IngestRequestBody
): Promise<IngestResponseBody> {
  const response = await apiFetch("/api/ingest", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return response.json();
}
