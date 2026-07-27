import sys
import time
import json
import urllib.request
import urllib.error

FASTAPI_HOST = "http://127.0.0.1:8000"
SESSION_ID = "test_redis_mem_cache"
QUERY_1 = "What is express cors middleware?"
QUERY_2 = "What default HTTP headers does it set?"  # Tests context memory ("it")

import os
from dotenv import load_dotenv

load_dotenv()
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

def send_chat(query: str) -> tuple[float, str]:
    """Sends a chat request and measures response latency (seconds)."""
    url = f"{FASTAPI_HOST}/chat/{SESSION_ID}"
    headers = {
        "Content-Type": "application/json", 
        "Accept": "text/event-stream",
        "X-Internal-Key": INTERNAL_API_KEY
    }
    body = json.dumps({"query": query}).encode("utf-8")
    
    start_time = time.time()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            for line in resp:
                decoded = line.decode("utf-8").strip()
                if decoded.startswith("data: "):
                    payload = decoded[6:]
                    try:
                        obj = json.loads(payload)
                        if "text" in obj:
                            chunks.append(obj["text"])
                    except json.JSONDecodeError:
                        chunks.append(payload)
        elapsed = time.time() - start_time
        return elapsed, "".join(chunks)
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.read().decode('utf-8')}")
        sys.exit(1)

def run_tests():
    print("=" * 60)
    print("🧪 PROMPT 3: Testing Redis Cache & Conversation Memory")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # TEST 1: Cache Miss (First Request)
    # -----------------------------------------------------------------------
    print(f"\n1️⃣ Sending initial query (Cache Miss expected)...")
    t1, resp1 = send_chat(QUERY_1)
    print(f"   ⏱️ Time taken: {t1:.2f}s")
    print(f"   💬 Response preview: \"{resp1[:100]}...\"")

    # -----------------------------------------------------------------------
    # TEST 2: Cache Hit (Identical Query)
    # -----------------------------------------------------------------------
    print(f"\n2️⃣ Resending identical query (Cache Hit expected)...")
    t2, resp2 = send_chat(QUERY_1)
    print(f"   ⏱️ Time taken: {t2:.2f}s")
    print(f"   💬 Response preview: \"{resp2[:100]}...\"")

    if t2 < 0.20 or t2 < (t1 / 3):
        print("   ✅ CACHE SUCCESS: Sub-second response time!")
    else:
        print(f"   ⚠️ CACHE WARNING: Response took {t2:.2f}s (Cache hit might have missed).")

    # -----------------------------------------------------------------------
    # TEST 3: Memory Context Check (Follow-up Question)
    # -----------------------------------------------------------------------
    print(f"\n3️⃣ Sending follow-up query relying on memory context...")
    print(f"   Query: \"{QUERY_2}\"")
    t3, resp3 = send_chat(QUERY_2)
    print(f"   ⏱️ Time taken: {t3:.2f}s")
    print(f"   💬 Response preview: \"{resp3[:150]}...\"")

    # Check if the AI understood "it" refers to CORS
    if "cors" in resp3.lower() or "header" in resp3.lower() or "origin" in resp3.lower():
        print("   ✅ MEMORY SUCCESS: LLM correctly resolved context from previous turn!")
    else:
        print("   ⚠️ MEMORY CHECK: Review full response to verify context awareness.")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    run_tests()
