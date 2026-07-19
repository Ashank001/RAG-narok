"""
stress_test.py
--------------
Concurrent stress test for the RAGnarok FastAPI backend.

Simulates:
  A. 10 concurrent chat (RAG query) requests
  B. 5 concurrent ingestion (repo queue) requests
  C. Ramp-up mode: gradually increases concurrency to find breakpoint

Usage:
  # Install dependencies
  pip install httpx asyncio

  # Set your real JWT token (get it from localStorage after logging in)
  export RAGNAROK_TOKEN="eyJhbG..."    # Windows: $env:RAGNAROK_TOKEN="..."

  # Run the stress test
  cd rag-engine
  python stress_test.py

  # OR specify token inline:
  python stress_test.py --token "eyJhbG..." --base-url http://localhost:8000

Output format:
  [CHAT]   request_id=3  status=200  latency=1.24s
  [INGEST] request_id=1  status=202  latency=0.08s
  ...
  === SUMMARY ===
  Chat requests:    10 total | 10 success | 0 failed | p50=1.1s | p95=2.3s
  Ingest requests:   5 total |  5 success | 0 failed | p50=0.1s | p95=0.2s
"""

import asyncio
import os
import sys
import time
import argparse
import statistics
from dataclasses import dataclass, field
from typing import Optional

try:
    import httpx  # pyrefly: ignore [missing-import]
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_SESSION_ID = "stress_test_session"

CHAT_QUERIES = [
    "What does the main entry point do?",
    "Explain the authentication flow.",
    "How are vector embeddings generated?",
    "What is the Celery task for?",
    "Describe the MongoDB schema.",
    "How does the GitLoader clone repositories?",
    "What error handling exists in the worker?",
    "Explain the SSE streaming mechanism.",
    "What are the CORS allowed origins?",
    "How is the JWT token validated?",
]

TEST_REPO_URL = "https://github.com/tiangolo/fastapi"  # small public repo


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class RequestResult:
    request_id: int
    kind: str  # "chat" | "ingest"
    status_code: int
    latency_s: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status_code in (200, 202) and self.error is None


# ---------------------------------------------------------------------------
# Individual request coroutines
# ---------------------------------------------------------------------------

async def send_chat(
    client: httpx.AsyncClient,
    request_id: int,
    token: str,
    session_id: str,
    query: str,
) -> RequestResult:
    start = time.monotonic()
    try:
        resp = await client.post(
            f"/chat/{session_id}",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        latency = time.monotonic() - start
        # Consume the full SSE stream
        body = resp.text
        print(f"  [CHAT]   id={request_id:>2}  status={resp.status_code}  latency={latency:.2f}s  chars={len(body)}")
        return RequestResult(request_id, "chat", resp.status_code, latency)
    except Exception as e:
        latency = time.monotonic() - start
        print(f"  [CHAT]   id={request_id:>2}  ERROR  latency={latency:.2f}s  error={e}")
        return RequestResult(request_id, "chat", 0, latency, error=str(e))


async def send_ingest(
    client: httpx.AsyncClient,
    request_id: int,
    token: str,
) -> RequestResult:
    session_id = f"stress_ingest_{request_id}_{int(time.time())}"
    start = time.monotonic()
    try:
        resp = await client.post(
            "/api/ingest",
            json={"sessionId": session_id, "repositoryUrl": TEST_REPO_URL},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        latency = time.monotonic() - start
        print(f"  [INGEST] id={request_id:>2}  status={resp.status_code}  latency={latency:.2f}s  session={session_id}")
        return RequestResult(request_id, "ingest", resp.status_code, latency)
    except Exception as e:
        latency = time.monotonic() - start
        print(f"  [INGEST] id={request_id:>2}  ERROR  latency={latency:.2f}s  error={e}")
        return RequestResult(request_id, "ingest", 0, latency, error=str(e))


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

async def run_concurrent_chat(base_url: str, token: str, session_id: str, concurrency: int) -> list[RequestResult]:
    """Fire `concurrency` chat requests simultaneously."""
    print(f"\n{'='*60}")
    print(f"  CONCURRENT CHAT TEST — {concurrency} simultaneous requests")
    print(f"{'='*60}")

    async with httpx.AsyncClient(base_url=base_url) as client:
        tasks = [
            send_chat(client, i, token, session_id, CHAT_QUERIES[i % len(CHAT_QUERIES)])
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


async def run_concurrent_ingest(base_url: str, token: str, concurrency: int) -> list[RequestResult]:
    """Fire `concurrency` ingest requests simultaneously."""
    print(f"\n{'='*60}")
    print(f"  CONCURRENT INGEST TEST — {concurrency} simultaneous requests")
    print(f"{'='*60}")

    async with httpx.AsyncClient(base_url=base_url) as client:
        tasks = [
            send_ingest(client, i, token)
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


async def run_ramp_up(base_url: str, token: str, session_id: str, levels: list[int]) -> None:
    """
    Gradually increase concurrency to find the breakpoint.
    Levels = [1, 5, 10, 25, 50]
    """
    print(f"\n{'='*60}")
    print(f"  RAMP-UP TEST — levels: {levels}")
    print(f"{'='*60}")

    for n in levels:
        print(f"\n  -- Concurrency: {n} --")
        async with httpx.AsyncClient(base_url=base_url) as client:
            tasks = [
                send_chat(client, i, token, session_id, CHAT_QUERIES[i % len(CHAT_QUERIES)])
                for i in range(n)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        latencies = [r.latency_s for r in results]
        failures = [r for r in results if not r.success]
        print(f"  Concurrency={n}: success={n - len(failures)}/{n}  "
              f"p50={statistics.median(latencies):.2f}s  "
              f"max={max(latencies):.2f}s")

        if len(failures) > n * 0.2:  # >20% failure rate
            print(f"  ⚠️  BREAKPOINT DETECTED at concurrency={n} ({len(failures)} failures)")
            break

        await asyncio.sleep(2)  # Brief pause between ramp levels


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(results: list[RequestResult], kind: str) -> None:
    filtered = [r for r in results if r.kind == kind]
    if not filtered:
        return

    successes = [r for r in filtered if r.success]
    failures = [r for r in filtered if not r.success]
    latencies = sorted(r.latency_s for r in filtered)

    p50 = statistics.median(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if len(latencies) >= 100 else max(latencies, default=0)

    print(f"\n  {kind.upper():8} | total={len(filtered):>3} | "
          f"success={len(successes):>3} | "
          f"failed={len(failures):>3} | "
          f"p50={p50:.2f}s | p95={p95:.2f}s | p99={p99:.2f}s")

    if failures:
        print(f"  Failed requests:")
        for r in failures[:5]:  # show first 5
            print(f"    id={r.request_id}  status={r.status_code}  error={r.error}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(base_url: str, token: str) -> None:
    session_id = f"stress_{int(time.time())}"

    print(f"\nRAGnarok Stress Test")
    print(f"  Backend: {base_url}")
    print(f"  Session: {session_id}")
    print(f"  Token:   {token[:20]}...")

    # Verify server is up
    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            health = await client.get("/health", timeout=5.0)
            if health.status_code != 200:
                print(f"ERROR: /health returned {health.status_code}")
                sys.exit(1)
        print(f"  Health:  OK\n")
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {base_url}: {e}")
        sys.exit(1)

    all_results: list[RequestResult] = []

    # --- Test A: 10 concurrent chat requests ---
    chat_results = await run_concurrent_chat(base_url, token, session_id, concurrency=10)
    all_results.extend(chat_results)

    # --- Test B: 5 concurrent ingest requests ---
    ingest_results = await run_concurrent_ingest(base_url, token, concurrency=5)
    all_results.extend(ingest_results)

    # --- Test C: Ramp-up ---
    await run_ramp_up(base_url, token, session_id, levels=[1, 5, 10, 20])

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print_summary(all_results, "chat")
    print_summary(all_results, "ingest")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAGnarok concurrent stress test")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="FastAPI base URL")
    parser.add_argument(
        "--token",
        default=os.environ.get("RAGNAROK_TOKEN", ""),
        help="JWT access token (or set RAGNAROK_TOKEN env var)",
    )
    args = parser.parse_args()

    if not args.token:
        print(
            "ERROR: No JWT token provided.\n"
            "  Set the RAGNAROK_TOKEN environment variable:\n"
            "    Windows PowerShell: $env:RAGNAROK_TOKEN = 'eyJhbG...'\n"
            "    Bash/zsh:           export RAGNAROK_TOKEN='eyJhbG...'\n"
            "\n"
            "  OR pass it directly:\n"
            "    python stress_test.py --token 'eyJhbG...'\n"
            "\n"
            "  Get your token from the browser DevTools:\n"
            "    Application → Local Storage → ragnarok_access_token"
        )
        sys.exit(1)

    asyncio.run(main(args.base_url, args.token))
