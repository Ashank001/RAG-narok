"""
diag_pipeline.py — Quick diagnostic for the RAGnarok ingestion pipeline
Run from rag-engine directory: python diag_pipeline.py
"""
import os, sys, time, json, urllib.request, urllib.error

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")
SESSION_ID = "diag_test_001"
REPO_URL = "https://github.com/expressjs/cors"
FASTAPI = "http://localhost:8000"

# ─── Step 1: Health checks ──────────────────────────────────────────
print("=== STEP 1: Health Checks ===")
for name, url in [
    ("FastAPI  :8000", f"{FASTAPI}/health"),
    ("API GW   :3001", "http://localhost:3001/health"),
]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(f"  ✅ {name}: HTTP {r.status}")
    except Exception as e:
        print(f"  ❌ {name}: {e}")

# ─── Step 2: Delete stale session ───────────────────────────────────
print("\n=== STEP 2: Cleanup stale session ===")
try:
    import certifi
    from pymongo import MongoClient
    MONGO_URI = os.getenv("MONGO_URI", "")
    if MONGO_URI:
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=8000)
        n = client["api-gateway"].sessions.delete_many({"sessionId": SESSION_ID}).deleted_count
        print(f"  Deleted {n} stale session(s)")
        v = client["rag_db"].code_vectors.delete_many({"metadata.session_id": SESSION_ID}).deleted_count
        print(f"  Deleted {v} stale vector(s)")
    else:
        print("  MONGO_URI not set — skipping cleanup")
except Exception as e:
    print(f"  Cleanup error (non-fatal): {e}")

# ─── Step 3: Trigger ingestion ──────────────────────────────────────
print("\n=== STEP 3: Trigger Ingestion (direct to FastAPI) ===")
payload = json.dumps({"sessionId": SESSION_ID, "repositoryUrl": REPO_URL}).encode()
req = urllib.request.Request(
    f"{FASTAPI}/api/ingest", data=payload,
    headers={"Content-Type": "application/json", "X-Internal-Key": INTERNAL_KEY},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read().decode()
        print(f"  ✅ HTTP {r.status}: {body}")
except urllib.error.HTTPError as e:
    body = e.read().decode() if e.fp else ""
    print(f"  ❌ HTTP {e.code}: {body}")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ Request error: {e}")
    sys.exit(1)

# ─── Step 4: Poll status ────────────────────────────────────────────
print("\n=== STEP 4: Polling Status (120s timeout) ===")
print(f"  Session: {SESSION_ID}")
deadline = time.time() + 120
last_status = ""

while time.time() < deadline:
    try:
        req2 = urllib.request.Request(
            f"{FASTAPI}/api/session/{SESSION_ID}",
            headers={"X-Internal-Key": INTERNAL_KEY},
            method="GET",
        )
        with urllib.request.urlopen(req2, timeout=5) as r:
            data = json.loads(r.read().decode())
            status = data.get("status", "?")
            error = data.get("errorLog", "")
            if status != last_status:
                print(f"  [{time.strftime('%H:%M:%S')}] status={repr(status)}" +
                      (f"  error={error[:200]}" if error else ""))
                last_status = status
            if status == "completed":
                print("\n  ✅ PIPELINE COMPLETED SUCCESSFULLY!")
                sys.exit(0)
            if status == "failed":
                print(f"\n  ❌ PIPELINE FAILED: {error}")
                sys.exit(1)
    except urllib.error.HTTPError as e:
        if e.code == 404 and last_status != "404":
            print(f"  [{time.strftime('%H:%M:%S')}] Session not found yet (404)")
            last_status = "404"
    except Exception as e:
        print(f"  [{time.strftime('%H:%M:%S')}] Poll error: {e}")
    time.sleep(3)

print(f"\n  ❌ TIMED OUT after 120s — last status: {repr(last_status)}")
print("  ⚠️  Check Celery worker terminal for the actual exception stacktrace.")
sys.exit(1)
