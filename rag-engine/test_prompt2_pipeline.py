"""
test_prompt2_pipeline.py — Automated verification of Prompt 2 upgrades
======================================================================
Verifies:
  1. Local service health (FastAPI :8000, API Gateway :3000, Redis :6379)
  2. Ingestion via FastAPI /api/ingest (bypasses gateway to control sessionId)
  3. Status polling until "completed" (90 s timeout)
  4. MongoDB vector dimension = 768 (BAAI/bge-base-en-v1.5)
  5. Chat + Cross-Encoder reranking via POST /chat/{session_id}

Usage:
    python test_prompt2_pipeline.py
"""

import os
import sys
import time
import json
import socket
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 errors with Unicode chars)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 0. Load .env from the same directory as this script
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_FILE = _SCRIPT_DIR / ".env"

def _load_env(path: Path) -> dict[str, str]:
    """Minimal .env parser — no dependency on python-dotenv."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env

_env = _load_env(_ENV_FILE)

# ---------------------------------------------------------------------------
# Config (from .env or sensible defaults)
# ---------------------------------------------------------------------------
FASTAPI_HOST = "http://localhost:8000"
GATEWAY_HOST = "http://localhost:3000"
REDIS_HOST = "localhost"
REDIS_PORT = 6379

MONGO_URI = _env.get("MONGO_URI", os.getenv("MONGO_URI", ""))
JWT_SECRET = _env.get("JWT_SECRET_KEY", os.getenv("JWT_SECRET_KEY", ""))
JWT_ALGORITHM = _env.get("JWT_ALGORITHM", os.getenv("JWT_ALGORITHM", "HS256"))
INTERNAL_API_KEY = _env.get("INTERNAL_API_KEY", os.getenv("INTERNAL_API_KEY", ""))

SESSION_ID = "opus_test_768"
REPO_URL = "https://github.com/expressjs/cors"
POLL_INTERVAL = 3       # seconds
POLL_TIMEOUT = 240       # seconds
CHAT_QUERY = "How does cors handle preflight OPTIONS requests?"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
_results: list[tuple[str, str, str]] = []  # (test_name, status, detail)

def _pass(name: str, detail: str = ""):
    _results.append((name, "PASS", detail))

def _fail(name: str, detail: str = ""):
    _results.append((name, "FAIL", detail))

def _skip(name: str, detail: str = ""):
    _results.append((name, "SKIP", detail))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def _http_json(method: str, url: str, body: dict | None = None,
               headers: dict | None = None, timeout: float = 10.0) -> tuple[int, dict | str]:
    """Minimal HTTP helper using urllib — returns (status_code, json_or_text)."""
    data = json.dumps(body).encode("utf-8") if body else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _http_stream(method: str, url: str, body: dict | None = None,
                 headers: dict | None = None, timeout: float = 60.0) -> tuple[int, str]:
    """HTTP request that reads a streaming (SSE) response and returns all text."""
    data = json.dumps(body).encode("utf-8") if body else None
    hdrs = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            chunks = []
            for line in resp:
                decoded = line.decode("utf-8").strip()
                if decoded.startswith("data: "):
                    payload = decoded[6:]
                    try:
                        obj = json.loads(payload)
                        if "text" in obj:
                            chunks.append(obj["text"])
                        if obj.get("done"):
                            break
                        if "error" in obj:
                            return resp.status, f"[STREAM ERROR] {obj['error']}"
                    except json.JSONDecodeError:
                        chunks.append(payload)
            return resp.status, "".join(chunks)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        return e.code, raw


def _create_test_jwt() -> str:
    """
    Create a short-lived JWT for test purposes using the same secret
    and algorithm as auth.py. Falls back to INTERNAL_API_KEY header approach.
    """
    try:
        from jose import jwt as jose_jwt
        payload = {
            "sub": "test-pipeline-user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    except ImportError:
        return ""


# ===========================================================================
# TEST 1: Service Health Checks
# ===========================================================================
def test_service_health():
    print("\n" + "=" * 60)
    print("TEST 1: Service Health Checks")
    print("=" * 60)

    # Redis
    if _tcp_reachable(REDIS_HOST, REDIS_PORT):
        _pass("Redis (localhost:6379)", "TCP port open")
        print("  ✅ Redis ............. reachable")
    else:
        _fail("Redis (localhost:6379)", "TCP port closed — is Redis running?")
        print("  ❌ Redis ............. NOT reachable")

    # FastAPI (may be slow if --reload is loading models)
    fastapi_ok = False
    max_retries = 6
    for attempt in range(1, max_retries + 1):
        try:
            code, data = _http_json("GET", f"{FASTAPI_HOST}/health", timeout=15.0)
            if code == 200:
                _pass("FastAPI (localhost:8000)", f"HTTP {code}")
                print("  ✅ FastAPI ........... healthy")
                fastapi_ok = True
                break
            else:
                _fail("FastAPI (localhost:8000)", f"HTTP {code}: {data}")
                print(f"  ❌ FastAPI ........... HTTP {code}")
                break
        except Exception as e:
            if attempt < max_retries:
                print(f"  ⏳ FastAPI ........... attempt {attempt}/{max_retries} ({e}), retrying in 10s...")
                time.sleep(10)
            else:
                _fail("FastAPI (localhost:8000)", str(e))
                print(f"  ❌ FastAPI ........... {e} (after {max_retries} attempts)")

    # API Gateway
    try:
        code, data = _http_json("GET", f"{GATEWAY_HOST}/health")
        if code == 200:
            _pass("API Gateway (localhost:3000)", f"HTTP {code}")
            print("  ✅ API Gateway ....... healthy")
        else:
            _fail("API Gateway (localhost:3000)", f"HTTP {code}: {data}")
            print(f"  ❌ API Gateway ....... HTTP {code}")
    except Exception as e:
        _fail("API Gateway (localhost:3000)", str(e))
        print(f"  ❌ API Gateway ....... {e}")


# ===========================================================================
# TEST 1.5: Cleanup stale test data
# ===========================================================================
def cleanup_stale_data():
    """Delete old session + vectors for SESSION_ID so we get a clean test."""
    print("\n" + "=" * 60)
    print("CLEANUP: Removing stale test data")
    print("=" * 60)

    if not MONGO_URI:
        print("  ⚠️  No MONGO_URI — skipping cleanup")
        return

    try:
        import certifi
        from pymongo import MongoClient

        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(),
                             tlsAllowInvalidCertificates=True,
                             serverSelectionTimeoutMS=10000)

        # Delete stale session from api-gateway DB
        gw_db = client["api-gateway"]
        del_session = gw_db.sessions.delete_many({"sessionId": SESSION_ID})
        print(f"  → Deleted {del_session.deleted_count} stale session(s) from api-gateway.sessions")

        # Delete stale vectors from rag_db
        rag_db = client["rag_db"]
        del_vectors = rag_db.code_vectors.delete_many({"session_id": SESSION_ID})
        print(f"  → Deleted {del_vectors.deleted_count} stale vector(s) from rag_db.code_vectors")

        print("  ✅ Cleanup done — ready for fresh ingestion")
    except Exception as e:
        print(f"  ⚠️  Cleanup error (non-fatal): {e}")


# ===========================================================================
# TEST 2: Trigger Ingestion
# ===========================================================================
def test_trigger_ingestion() -> bool:
    print("\n" + "=" * 60)
    print("TEST 2: Trigger Ingestion")
    print("=" * 60)

    # Use FastAPI's /api/ingest directly — it lets us control the sessionId
    # and bypasses BullMQ. Requires auth via internal key or JWT.
    auth_headers = {}
    if INTERNAL_API_KEY:
        auth_headers["X-Internal-Key"] = INTERNAL_API_KEY
    else:
        token = _create_test_jwt()
        if token:
            auth_headers["Authorization"] = f"Bearer {token}"

    payload = {
        "sessionId": SESSION_ID,
        "repositoryUrl": REPO_URL,
    }

    print(f"  → POST {FASTAPI_HOST}/api/ingest")
    print(f"    sessionId:     {SESSION_ID}")
    print(f"    repositoryUrl: {REPO_URL}")

    try:
        code, data = _http_json("POST", f"{FASTAPI_HOST}/api/ingest", body=payload,
                                headers=auth_headers)
        if code in (200, 202):
            _pass("Trigger Ingestion", f"HTTP {code} — {data}")
            print(f"  ✅ Ingestion triggered (HTTP {code})")
            return True
        else:
            _fail("Trigger Ingestion", f"HTTP {code} — {data}")
            print(f"  ❌ Ingestion failed (HTTP {code}): {data}")
            return False
    except Exception as e:
        _fail("Trigger Ingestion", str(e))
        print(f"  ❌ Ingestion request failed: {e}")
        return False


# ===========================================================================
# TEST 3: Poll Status Until Completed
# ===========================================================================
def test_poll_status() -> bool:
    print("\n" + "=" * 60)
    print("TEST 3: Poll Ingestion Status")
    print("=" * 60)

    # Use the FastAPI session endpoint with auth
    auth_headers = {}
    if INTERNAL_API_KEY:
        auth_headers["X-Internal-Key"] = INTERNAL_API_KEY
    else:
        token = _create_test_jwt()
        if token:
            auth_headers["Authorization"] = f"Bearer {token}"

    url = f"{FASTAPI_HOST}/api/session/{SESSION_ID}"
    deadline = time.time() + POLL_TIMEOUT
    last_status = ""

    print(f"  → Polling {url}")
    print(f"    Timeout: {POLL_TIMEOUT}s | Interval: {POLL_INTERVAL}s")
    print()

    while time.time() < deadline:
        try:
            code, data = _http_json("GET", url, headers=auth_headers)
            if code == 200 and isinstance(data, dict):
                status = data.get("status", "unknown")
                if status != last_status:
                    print(f"    [{time.strftime('%H:%M:%S')}] status = \"{status}\"")
                    last_status = status

                if status == "completed":
                    _pass("Poll Ingestion Status", f"Completed in {POLL_TIMEOUT - int(deadline - time.time())}s")
                    print(f"\n  ✅ Ingestion completed!")
                    return True
                elif status == "failed":
                    error_log = data.get("errorLog", "No error details")
                    _fail("Poll Ingestion Status", f"Status 'failed': {error_log}")
                    print(f"\n  ❌ Ingestion failed: {error_log}")
                    return False
            elif code == 404:
                if last_status != "not_found":
                    print(f"    [{time.strftime('%H:%M:%S')}] Session not found yet (waiting for creation)")
                    last_status = "not_found"
        except Exception as e:
            print(f"    [{time.strftime('%H:%M:%S')}] Poll error: {e}")

        time.sleep(POLL_INTERVAL)

    _fail("Poll Ingestion Status", f"Timed out after {POLL_TIMEOUT}s — last status: '{last_status}'")
    print(f"\n  ❌ Timed out after {POLL_TIMEOUT}s (last status: '{last_status}')")
    return False


# ===========================================================================
# TEST 4: Verify MongoDB Vector Dimensions
# ===========================================================================
def test_vector_dimensions() -> bool:
    print("\n" + "=" * 60)
    print("TEST 4: Verify MongoDB Vector Dimensions (768)")
    print("=" * 60)

    if not MONGO_URI:
        _skip("MongoDB Vector Dimensions", "MONGO_URI not found in .env")
        print("  ⚠️  Skipped — MONGO_URI not found in .env")
        return False

    try:
        import certifi
        from pymongo import MongoClient

        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(),
                             tlsAllowInvalidCertificates=True,
                             serverSelectionTimeoutMS=10000)
        db = client["rag_db"]
        collection = db["code_vectors"]

        # Find one document from our test session
        doc = collection.find_one(
            {"session_id": SESSION_ID},
            {"embedding": 1, "session_id": 1, "_id": 0}
        )

        if not doc:
            _fail("MongoDB Vector Dimensions", f"No documents found for session_id='{SESSION_ID}'")
            print(f"  ❌ No documents found for session '{SESSION_ID}'")
            return False

        embedding = doc.get("embedding", [])
        dims = len(embedding)
        total_docs = collection.count_documents({"session_id": SESSION_ID})

        print(f"  → Found {total_docs} vector(s) for session '{SESSION_ID}'")
        print(f"  → Embedding dimensions: {dims}")

        if dims == 768:
            _pass("MongoDB Vector Dimensions", f"{dims} dims, {total_docs} vectors stored")
            print(f"  ✅ Dimensions correct: {dims} (expected 768)")
            return True
        else:
            _fail("MongoDB Vector Dimensions", f"Expected 768 dims, got {dims}")
            print(f"  ❌ Dimension mismatch: got {dims}, expected 768")
            return False

    except ImportError as e:
        _skip("MongoDB Vector Dimensions", f"Missing dependency: {e}")
        print(f"  ⚠️  Skipped — {e}")
        return False
    except Exception as e:
        _fail("MongoDB Vector Dimensions", str(e))
        print(f"  ❌ MongoDB error: {e}")
        return False


# ===========================================================================
# TEST 5: Chat + Cross-Encoder Reranking
# ===========================================================================
def test_chat_reranker():
    print("\n" + "=" * 60)
    print("TEST 5: Chat & Cross-Encoder Reranking")
    print("=" * 60)

    auth_headers = {}
    if INTERNAL_API_KEY:
        auth_headers["X-Internal-Key"] = INTERNAL_API_KEY
    else:
        token = _create_test_jwt()
        if token:
            auth_headers["Authorization"] = f"Bearer {token}"
        else:
            _skip("Chat & Cross-Encoder", "No JWT_SECRET_KEY or INTERNAL_API_KEY — can't authenticate")
            print("  ⚠️  Skipped — cannot create auth token")
            return

    url = f"{FASTAPI_HOST}/chat/{SESSION_ID}"
    payload = {"query": CHAT_QUERY}

    print(f"  → POST {url}")
    print(f"    query: \"{CHAT_QUERY}\"")
    print()

    try:
        code, response_text = _http_stream("POST", url, body=payload,
                                            headers=auth_headers, timeout=60)

        if code == 200 and response_text and not response_text.startswith("[STREAM ERROR]"):
            preview = response_text[:200].replace("\n", " ")
            _pass("Chat & Cross-Encoder", f"HTTP {code}, {len(response_text)} chars received")
            print(f"  ✅ Streaming response received ({len(response_text)} chars)")
            print(f"  → Preview: \"{preview}...\"")
        elif code == 429:
            _skip("Chat & Cross-Encoder", f"Rate limited (HTTP 429) — daily quota exhausted")
            print(f"  ⚠️  Rate limited (HTTP 429) — try again tomorrow")
        else:
            detail = response_text[:200] if isinstance(response_text, str) else str(response_text)
            _fail("Chat & Cross-Encoder", f"HTTP {code}: {detail}")
            print(f"  ❌ HTTP {code}: {detail}")
    except Exception as e:
        _fail("Chat & Cross-Encoder", str(e))
        print(f"  ❌ Chat request failed: {e}")


# ===========================================================================
# Summary
# ===========================================================================
def print_summary() -> int:
    print("\n")
    print("=" * 60)
    print("  PROMPT 2 VERIFICATION SUMMARY")
    print("=" * 60)
    print()
    print(f"  {'Test':<35} {'Result':<8} {'Detail'}")
    print(f"  {'─' * 35} {'─' * 8} {'─' * 40}")
    for name, status, detail in _results:
        icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "⚠️")
        # Truncate detail for table readability
        short_detail = (detail[:50] + "…") if len(detail) > 50 else detail
        print(f"  {icon} {name:<33} {status:<8} {short_detail}")

    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    skipped = sum(1 for _, s, _ in _results if s == "SKIP")
    total = len(_results)

    print()
    print(f"  Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print("=" * 60)

    if failed > 0:
        print("\n  ❌ OVERALL: FAIL")
        return 1
    elif skipped > 0 and passed == 0:
        print("\n  ⚠️  OVERALL: NO TESTS PASSED")
        return 1
    else:
        print("\n  ✅ OVERALL: PASS")
        return 0


# ===========================================================================
# Main
# ===========================================================================
def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   RAGnarok — Prompt 2 Pipeline Verification             ║")
    print("║   BGE-base-en-v1.5 (768d) + Cross-Encoder Reranker     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Session ID: {SESSION_ID}")

    # Step 1: Health checks
    test_service_health()

    # Bail early if FastAPI is down — nothing else will work
    fastapi_up = any(n == "FastAPI (localhost:8000)" and s == "PASS" for n, s, _ in _results)
    if not fastapi_up:
        print("\n  ⛔ FastAPI is not reachable — skipping remaining tests.")
        _skip("Trigger Ingestion", "FastAPI not reachable")
        _skip("Poll Ingestion Status", "FastAPI not reachable")
        _skip("MongoDB Vector Dimensions", "Ingestion not attempted")
        _skip("Chat & Cross-Encoder", "FastAPI not reachable")
        return print_summary()

    # Step 1.5: Clean up stale data from previous runs
    cleanup_stale_data()

    # Step 2: Trigger ingestion
    ingestion_ok = test_trigger_ingestion()

    # Step 3: Poll status
    if ingestion_ok:
        poll_ok = test_poll_status()
    else:
        _skip("Poll Ingestion Status", "Ingestion was not triggered")
        print("\n  ⚠️  Skipping status polling — ingestion not triggered")
        poll_ok = False

    # Step 4: Verify vector dimensions
    if poll_ok:
        test_vector_dimensions()
    else:
        _skip("MongoDB Vector Dimensions", "Ingestion did not complete")
        print("\n  ⚠️  Skipping vector check — ingestion not completed")

    # Step 5: Chat + reranker
    if poll_ok:
        test_chat_reranker()
    else:
        _skip("Chat & Cross-Encoder", "No vectors to query")
        print("\n  ⚠️  Skipping chat test — no vectors available")

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
