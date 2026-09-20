import asyncio
import httpx
import uuid
from dotenv import load_dotenv
import os, sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv("rag-engine/.env")

LOCAL_API = "http://127.0.0.1:8000"
INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "ragnarok-internal-service-key-2026")

async def test_cache():
    session_id = "test-local-cache-12345"
    url = f"{LOCAL_API}/chat/{session_id}"
    
    headers = {
        "X-Internal-Key": INTERNAL_KEY,
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }
    
    query = {"query": "What is the primary function of this application?"}
    
    print(f"=== Request 1 (expect Cache MISS + LLM call) ===")
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=query, headers=headers) as response:
            print(f"Status: {response.status_code}")
            print(f"X-Cache: {response.headers.get('X-Cache', 'not set')}")
            text = ""
            async for chunk in response.aiter_text():
                text += chunk
            print(f"Response (first 200 chars): {text[:200]}")
    print()
    
    print(f"=== Request 2 (expect Cache HIT, no LLM call) ===")
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=query, headers=headers) as response:
            print(f"Status: {response.status_code}")
            print(f"X-Cache: {response.headers.get('X-Cache', 'not set')}")
            text = ""
            async for chunk in response.aiter_text():
                text += chunk
            print(f"Response (first 200 chars): {text[:200]}")
    print()

if __name__ == "__main__":
    asyncio.run(test_cache())
