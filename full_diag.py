"""
Full end-to-end diagnosis of the deployed RAGnarok pipeline.
Tests every single link in the chain and reports exactly what breaks.
"""
import os, sys, time, json, urllib.request, urllib.error, certifi

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv("rag-engine/.env")
from pymongo import MongoClient

INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")
MONGO_URI    = os.getenv("MONGO_URI", "")
RAG_API      = "https://ragnarok-rag-api.onrender.com"
GW_API       = "https://ragnarok-api-gateway.onrender.com"
SESSION_ID   = f"fulldiag_{int(time.time())}"
REPO_URL     = "https://github.com/expressjs/cors"

mongo = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=10000)

def http(method, url, body=None, headers=None, timeout=90):
    payload = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"}
    if headers: hdrs.update(headers)
    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            try: return r.status, json.loads(raw)
            except: return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try: return e.code, json.loads(raw)
        except: return e.code, raw
    except Exception as e:
        return 0, str(e)

auth = {"X-Internal-Key": INTERNAL_KEY}

# ===================================================================
print("=" * 65)
print("  FULL END-TO-END PIPELINE DIAGNOSIS")
print("=" * 65)
print(f"  Session: {SESSION_ID}")
print(f"  Repo:    {REPO_URL}")
print()

# 1. MongoDB connectivity
print("1. MONGODB CONNECTIVITY")
try:
    mongo.admin.command("ping")
    print("   OK - MongoDB Atlas reachable")
    # Count existing data
    vcount = mongo["rag_db"]["code_vectors"].count_documents({})
    scount = mongo["api-gateway"]["sessions"].count_documents({})
    print(f"   Existing data: {vcount} vectors, {scount} sessions")
except Exception as e:
    print(f"   FAIL - {e}")

# 2. RAG API health
print()
print("2. RAG API HEALTH (may take 60s for cold start)")
code, data = http("GET", f"{RAG_API}/health", timeout=90)
print(f"   HTTP {code}: {data}")
if code != 200:
    print("   FAIL - RAG API is down. Cannot proceed.")
    sys.exit(1)

# 3. API Gateway health + config
print()
print("3. API GATEWAY HEALTH + CONFIG")
code, data = http("GET", f"{GW_API}/health/debug", timeout=30)
if code == 200 and isinstance(data, dict):
    cfg = data.get("config", {})
    for k, v in cfg.items():
        print(f"   {k}: {v}")
else:
    print(f"   HTTP {code}: {data}")

# 4. Create session in MongoDB (simulate what API Gateway does)
print()
print("4. CREATE SESSION IN MONGODB (what API Gateway does on POST /api/ingest)")
mongo["api-gateway"]["sessions"].insert_one({
    "sessionId": SESSION_ID,
    "status": "queued",
    "repositoryUrl": REPO_URL,
})
verify = mongo["api-gateway"]["sessions"].find_one({"sessionId": SESSION_ID})
print(f"   Created: {verify.get('sessionId')} status={verify.get('status')}")

# 5. Trigger ingestion DIRECTLY on RAG API (bypass BullMQ entirely)
print()
print("5. TRIGGER INGESTION (direct POST to RAG API, bypassing BullMQ)")
code, data = http("POST", f"{RAG_API}/api/ingest",
                  body={"sessionId": SESSION_ID, "repositoryUrl": REPO_URL},
                  headers=auth, timeout=90)
print(f"   HTTP {code}: {data}")
if code not in (200, 202):
    print("   FAIL - Could not trigger ingestion")
    sys.exit(1)

# 6. Poll MongoDB directly (not through API Gateway - eliminates caching issues)
print()
print("6. POLLING MONGODB DIRECTLY FOR STATUS (4-minute timeout)")
print("   This bypasses all HTTP caching / API Gateway issues")
deadline = time.time() + 240
last = ""
while time.time() < deadline:
    s = mongo["api-gateway"]["sessions"].find_one(
        {"sessionId": SESSION_ID},
        {"status": 1, "errorLog": 1, "_id": 0}
    )
    status = s.get("status", "?") if s else "NOT_FOUND"
    err = s.get("errorLog", "") if s else ""
    if status != last:
        ts = time.strftime("%H:%M:%S")
        msg = f"   [{ts}] status={status}"
        if err:
            msg += f"  errorLog={err[:300]}"
        print(msg)
        last = status
    if status == "completed":
        print()
        print("   === PIPELINE COMPLETED SUCCESSFULLY ===")
        # Verify vectors were stored
        new_vectors = mongo["rag_db"]["code_vectors"].count_documents({"session_id": SESSION_ID})
        print(f"   Vectors stored for this session: {new_vectors}")
        sys.exit(0)
    if status == "failed":
        print()
        print(f"   === PIPELINE FAILED ===")
        print(f"   Error: {err}")
        print()
        print("   DIAGNOSIS:")
        if "no loadable documents" in err.lower():
            print("   -> The repo was cloned but file filter rejected all files.")
            print("   -> This means cloning works, embedding would work, but the repo has no recognized source files.")
        elif "oom" in err.lower() or "killed" in err.lower() or "memory" in err.lower():
            print("   -> Out of Memory - the embedding model is too large for 512MB")
        elif "redis" in err.lower() or "connection" in err.lower():
            print("   -> Redis/network connectivity issue")
        else:
            print("   -> Unknown error. Check Render ragnarok-rag-api logs for Python traceback.")
        sys.exit(1)
    time.sleep(5)

print()
print(f"   === TIMED OUT (4 min) - last status: {last} ===")
print()
print("   DIAGNOSIS:")
if last == "processing":
    print("   -> Celery task is either still running (large repo) OR it OOM-crashed silently")
    print("   -> Check Render logs for ragnarok-rag-api - look for:")
    print("      - 'Killed' or 'signal 9' = OOM crash")  
    print("      - 'Cloning repository' = task started but embedding crashed")
    print("      - No task logs at all = Celery never picked up the task from Redis")
elif last == "queued":
    print("   -> Celery never started processing. Either:")
    print("      - Celery worker is not running (check start.sh output in Render logs)")
    print("      - Redis connection failed (REDIS_URL misconfigured)")
sys.exit(1)
