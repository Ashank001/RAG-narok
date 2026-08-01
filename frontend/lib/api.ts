/**
 * lib/api.ts
 * ----------
 * A typed fetch wrapper that automatically attaches the stored JWT to
 * every request that goes to the backend.
 *
 * Two backend services:
 *   - RAG Engine (FastAPI):  localhost:8000 — chat, auth, sessions
 *   - Ingest Service:        localhost:3001 — repository ingestion
 */

import { getAuthToken } from "./auth";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const INGEST_BACKEND_URL =
  process.env.NEXT_PUBLIC_INGEST_BACKEND_URL ?? "http://localhost:3001";

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

export interface ApiFetchOptions extends RequestInit {
  /**
   * When true, the response is returned as-is even if !response.ok.
   * Use this for streaming/SSE endpoints where you need the raw Response
   * to inspect the status yourself before reading the body.
   */
  rawResponse?: boolean;
}

export async function apiFetch(
  path: string,
  init: ApiFetchOptions = {}
): Promise<Response> {
  const { rawResponse, ...fetchInit } = init;
  const token = getAuthToken();

  const headers = new Headers(fetchInit.headers);

  // Only set Content-Type when sending JSON (not FormData/multipart)
  if (!(fetchInit.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...fetchInit,
    headers,
  });

  // Skip error check for raw/streaming responses — caller handles status.
  if (rawResponse) return response;

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
// Ingest service fetch wrapper (port 3001)
// ---------------------------------------------------------------------------

export async function ingestFetch(
  path: string,
  init: ApiFetchOptions = {}
): Promise<Response> {
  const { rawResponse, ...fetchInit } = init;
  const token = getAuthToken();

  const headers = new Headers(fetchInit.headers);

  if (!(fetchInit.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${INGEST_BACKEND_URL}${path}`, {
    ...fetchInit,
    headers,
  });

  if (rawResponse) return response;

  if (!response.ok) {
    let errorDetail = `${response.status} ${response.statusText}`;
    try {
      const json = await response.clone().json();
      // FastAPI uses `detail`, Express/api-gateway uses `error`
      if (json?.detail) errorDetail = json.detail;
      else if (json?.error) errorDetail = json.error;
    } catch {
      // Body is not JSON
    }
    throw new Error(errorDetail);
  }

  return response;
}

// ---------------------------------------------------------------------------
// Typed helpers — Chat
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
    rawResponse: true, // SSE stream — caller inspects status & body directly
  });
}

// ---------------------------------------------------------------------------
// Typed helpers — Ingestion (port 3001)
// ---------------------------------------------------------------------------

export interface IngestRequestBody {
  repository_url: string;
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
  repositoryUrl: string
): Promise<IngestResponseBody> {
  const response = await ingestFetch("/api/ingest", {
    method: "POST",
    body: JSON.stringify({ repository_url: repositoryUrl }),
  });
  return response.json();
}

/**
 * GET /api/status/:sessionId
 * Returns current ingestion status.
 */
export interface IngestStatusResponse {
  status: "queued" | "processing" | "completed" | "failed";
  error?: string;
}

export async function getIngestStatus(
  sessionId: string
): Promise<IngestStatusResponse> {
  const response = await ingestFetch(`/api/status/${sessionId}`);
  return response.json();
}

// ---------------------------------------------------------------------------
// Typed helpers — Session info (port 8000)
// ---------------------------------------------------------------------------

export interface SessionInfo {
  status: string;
  repo_url: string;
}

/**
 * GET /api/session/:sessionId
 * Returns session metadata.
 */
export async function getSessionInfo(
  sessionId: string
): Promise<SessionInfo> {
  const response = await apiFetch(`/api/session/${sessionId}`);
  return response.json();
}
