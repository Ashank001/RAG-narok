"""
diag_deployed.py — Diagnose the deployed RAGnarok pipeline on Render
Run: python rag-engine/diag_deployed.py
"""
import os, sys, time, json, urllib.request, urllib.error

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv("rag-engine/.env")

INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")
RAG_API      = "https://ragnarok-rag-api.onrender.com"
GW_API       = "https://ragnarok-api-gateway.onrender.com"
SESSION_ID   = "diag_deploy_002"
REPO_URL     = "https://github.com/expressjs/cors"

def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try: return e.code, json.loads(body)
        except: return e.code, body
    except Exception as e:
        return 0, str(e)

def post(url, body, headers=None, timeout=30):
    payload = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json"}
    if headers: hdrs.update(headers)
    req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try: return e.code, json.loads(body)
        except: return e.code, body
    except Exception as e:
        return 0, str(e)

auth = {"X-Internal-Key": INTERNAL_KEY}

print("=" * 60)
print("  RAGnarok Deployed Pipeline Diagnostic")
print("=" * 60)
print()

# ── Step 1: Health checks ──────────────────────────────────────
print("STEP 1: Health Checks")
code, data = get(f"{RAG_API}/health", timeout=60)
print(f"  RAG API  : HTTP {code} — {data}")
rag_ok = code == 200

code, data = get(f"{GW_API}/health", timeout=60)
print(f"  API GW   : HTTP {code} — {data}")
gw_ok = code == 200

# ── Step 2: Check deployed config ─────────────────────────────
print()
print("STEP 2: Deployed Config Check (/health/debug)")
code, data = get(f"{GW_API}/health/debug", timeout=30)
if code == 200 and isinstance(data, dict):
    cfg = data.get("config", {})
    print(f"  RAG_ENGINE_URL     : {cfg.get('RAG_ENGINE_URL', 'NOT FOUND')}")
    print(f"  REDIS              : {cfg.get('REDIS', 'NOT FOUND')}")
    print(f"  INTERNAL_KEY_SET   : {cfg.get('INTERNAL_API_KEY_SET', False)}")
    print(f"  MONGO_URI_SET      : {cfg.get('MONGO_URI_SET', False)}")
    print(f"  CORS_ORIGINS       : {cfg.get('CORS_ORIGINS', [])}")
else:
    print(f"  /health/debug not available (HTTP {code}) — deploy the latest code first")

# ── Step 3: Trigger ingestion directly at RAG API ──────────────
print()
print("STEP 3: Trigger Ingestion (direct → RAG API, bypassing BullMQ)")
code, data = post(f"{RAG_API}/api/ingest",
                  {"sessionId": SESSION_ID, "repositoryUrl": REPO_URL},
                  headers=auth, timeout=60)
print(f"  HTTP {code}: {data}")
if code not in (200, 202):
    print("  ❌ Ingest trigger failed — check INTERNAL_API_KEY and RAG API logs on Render")
    sys.exit(1)
print("  ✅ Celery task dispatched")

# ── Step 4: Poll status via API Gateway (same path as frontend) ─
print()
print("STEP 4: Polling Status via API Gateway (what the frontend sees, 3-min timeout)")
deadline = time.time() + 180
last = ""
while time.time() < deadline:
    code, data = get(f"{GW_API}/api/status/{SESSION_ID}")
    if code == 200 and isinstance(data, dict):
        status = data.get("status", data.get("errorLog", "?"))
        err    = data.get("error") or data.get("errorLog") or ""
        if status != last:
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] status={repr(status)}" + (f"  error={err[:200]}" if err else ""))
            last = status
        if status == "completed":
            print("\n  ✅ PIPELINE COMPLETED — ingestion is working end-to-end!")
            sys.exit(0)
        if status == "failed":
            print(f"\n  ❌ PIPELINE FAILED with: {err}")
            print("  → Check rag-api logs on Render for the full Python traceback")
            sys.exit(1)
    elif code == 404 and last != "404":
        print(f"  [{time.strftime('%H:%M:%S')}] 404 — session not in MongoDB yet (Celery hasn't started)")
        last = "404"
    time.sleep(5)

print(f"\n  ❌ TIMED OUT after 3 minutes — last status: {repr(last)}")
print("  DIAGNOSIS:")
print("  1. If stuck on 'queued' → BullMQ worker isn't picking up the job (check REDIS_URL on API Gateway Render)")
print("  2. If stuck on 'processing' → Celery task is failing silently (check rag-api Render logs for OOM or exception)")
print("  3. If 404 the whole time → Celery never started or MongoDB write failing (check MONGO_URI on rag-api Render)")
sys.exit(1)
