import os
import re
import json
import asyncio
import hashlib
# pyrefly: ignore [missing-import]
import redis
from datetime import datetime, timezone, timedelta
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load .env FIRST — before any os.getenv() call and before heavy C-extension imports
load_dotenv()

# Ensure thread limits are set even if .env is missing the keys.
# Must happen BEFORE numpy/torch/OpenBLAS are imported.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# pyrefly: ignore [missing-import]
from logger import get_logger

# Module-level logger for startup / non-request-scoped events
_log = get_logger(__name__)

# pyrefly: ignore [missing-import]
import httpx

# ADDED: get_current_user
# pyrefly: ignore [missing-import]
from auth import create_access_token, get_current_user

GITHUB_CLIENT_ID = os.getenv("OAUTH_ID")
GITHUB_CLIENT_SECRET = os.getenv("OAUTH_SECRET_KEY")

# pyrefly: ignore [missing-import]
# ADDED: Depends
from fastapi import FastAPI, HTTPException, Depends, Request
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse, StreamingResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

# Rate Limiting (slowapi)
# pyrefly: ignore [missing-import]
from slowapi import Limiter
# pyrefly: ignore [missing-import]
from slowapi.errors import RateLimitExceeded
# pyrefly: ignore [missing-import]
from jose import JWTError, jwt as jose_jwt

# Celery task import
# pyrefly: ignore [missing-import]
from worker import process_repository

# LangChain & AI Imports (heavy ML models are lazy-loaded below to avoid OOM on startup)
# pyrefly: ignore [missing-import]
from langchain_groq import ChatGroq
# pyrefly: ignore [missing-import]
from langchain_core.prompts import ChatPromptTemplate
# pyrefly: ignore [missing-import]
from langchain_core.output_parsers import StrOutputParser
# pyrefly: ignore [missing-import]
from langchain_core.messages import SystemMessage, HumanMessage
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
import certifi

# Cross-Encoder import moved to lazy loader (get_reranker) to save startup memory

# Groq SDK — for RateLimitError detection in the fallback chain
# pyrefly: ignore [missing-import]
from groq import RateLimitError as GroqRateLimitError

# Gemini SDK — third fallback LLM provider
# pyrefly: ignore [missing-import]
import google.genai as genai

# (load_dotenv already called at the top of this file)

# ---------------------------------------------------------
# Rate-limit helper (shared with retry loops below)
# ---------------------------------------------------------
def _parse_retry_delay_secs(exc: Exception, default: float) -> float:
    """
    Google's 429 errors embed a suggested retry delay in the message body.
    e.g. "Please retry in 37.5s."  Parse it so we honour that floor.
    """
    match = re.search(r'retry\s+in\s+(\d+(?:\.\d+)?)s', str(exc), re.IGNORECASE)
    if match:
        return min(float(match.group(1)) + 2.0, 120.0)  # +2 s headroom, cap 120 s
    return default

# ---------------------------------------------------------
# Rate Limiter — per-user, keyed by GitHub username from JWT
# ---------------------------------------------------------
_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
DAILY_CHAT_LIMIT = int(os.getenv("DAILY_CHAT_LIMIT", "10"))


def _rate_limit_key(request: Request) -> str:
    """
    Extract the GitHub username from the JWT Bearer token so slowapi
    can rate-limit per authenticated user rather than per IP address.
    Falls back to 'anonymous' for unauthenticated or malformed tokens.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header else ""
    if not token:
        return "anonymous"
    try:
        payload = jose_jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return payload.get("sub", "anonymous")
    except JWTError:
        return "anonymous"


limiter = Limiter(key_func=_rate_limit_key)

app = FastAPI()
app.state.limiter = limiter


# ---------------------------------------------------------
# Custom 429 handler — tells the user when the limit resets
# ---------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    # Daily window resets at midnight UTC
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_at = tomorrow.isoformat()

    _log.warning("Rate limit exceeded", extra={
        "user": _rate_limit_key(request),
        "endpoint": str(request.url.path),
        "reset_at": reset_at,
    })

    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": f"You have exceeded the daily limit of {DAILY_CHAT_LIMIT} chat requests.",
            "limit": DAILY_CHAT_LIMIT,
            "reset_at": reset_at,
            "message": f"Your quota resets at midnight UTC ({reset_at}). "
                       "Please try again after that.",
        },
    )

# ---------------------------------------------------------
# 1. Setup CORS Middleware for Next.js
# ---------------------------------------------------------
# Read allowed origins from env (comma-separated). Falls back to localhost
# defaults so local dev works without an explicit .env entry.
_raw_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,"
    "http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002,http://127.0.0.1:3003",
)
CORS_ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_log.info("CORS configured", extra={"allowed_origins": CORS_ALLOWED_ORIGINS})

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    query: str

class IngestRequest(BaseModel):
    sessionId: str
    repositoryUrl: str

# ---------------------------------------------------------
# 2. Database & Vector Store Configuration
# ---------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("CRITICAL: MONGO_URI missing from .env")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Connect to Atlas using synchronous MongoClient for LangChain
# tlsCAFile=certifi.where() fixes TLSV1_ALERT_INTERNAL_ERROR on Windows/older OpenSSL
# tlsAllowInvalidCertificates=True is a dev-only fallback for Windows TLS handshake issues
mongo_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)

# IMPORTANT: Ensure these match what you set in your ingestion worker!
DB_NAME = "rag_db"
COLLECTION_NAME = "code_vectors"
collection = mongo_client[DB_NAME][COLLECTION_NAME]

# ---------------------------------------------------------
# Lazy-loaded ML models (avoids OOM on Railway 512 MB free tier)
# Models are loaded on first request, not at startup.
# ---------------------------------------------------------
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_TOP_K = 5  # Keep top 5 after reranking
RETRIEVAL_TOP_K = 20  # Retrieve top 20 candidates for reranking

_embeddings = None
_reranker = None
_vector_store = None


def get_embeddings():
    """Lazy-load the HuggingFace embedding model on first use."""
    global _embeddings
    if _embeddings is None:
        _log.info("Lazy-loading embedding model", extra={"model": "BAAI/bge-base-en-v1.5"})
        # pyrefly: ignore [missing-import]
        from langchain_huggingface import HuggingFaceEmbeddings
        _embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-base-en-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        _log.info("Embedding model loaded")
    return _embeddings


def get_reranker():
    """Lazy-load the cross-encoder reranker on first use."""
    global _reranker
    if _reranker is None:
        _log.info("Lazy-loading cross-encoder reranker", extra={"model": RERANK_MODEL_NAME})
        # pyrefly: ignore [missing-import]
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANK_MODEL_NAME, device="cpu")
        _log.info("Cross-encoder reranker loaded")
    return _reranker


def get_vector_store():
    """Lazy-load the MongoDB Atlas Vector Search integration on first use."""
    global _vector_store
    if _vector_store is None:
        _log.info("Lazy-loading vector store")
        # pyrefly: ignore [missing-import]
        from langchain_mongodb import MongoDBAtlasVectorSearch
        _vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=get_embeddings(),
            index_name="vector_index",
            text_key="text",
            embedding_key="embedding",
        )
        _log.info("Vector store loaded")
    return _vector_store


def rerank_documents(query: str, documents: list, top_k: int = RERANK_TOP_K) -> list:
    """
    Reranks retrieved documents using the cross-encoder.

    Args:
        query:     The user's search query.
        documents: List of LangChain Document objects from similarity_search.
        top_k:     Number of top-scoring documents to keep.

    Returns:
        The top_k documents sorted by cross-encoder relevance score (descending).
    """
    if not documents:
        return []

    # Build (query, passage) pairs for the cross-encoder
    pairs = [(query, doc.page_content) for doc in documents]

    # Score all pairs in one batch (much faster than one-by-one)
    scores = get_reranker().predict(pairs)

    # Attach scores and sort descending
    scored_docs = sorted(
        zip(documents, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    # Return only the top_k documents
    return [doc for doc, _score in scored_docs[:top_k]]


# ---------------------------------------------------------
# 3. LLM Configuration — Primary + Fallback Providers
# ---------------------------------------------------------
# Provider 1: Groq — llama-3.3-70b-versatile (primary)
# Groq's LPU hardware makes this the fastest inference available.
# Free tier: 14,400 tokens/day.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("CRITICAL: GROQ_API_KEY missing from .env — get a free key at https://console.groq.com")

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    streaming=True,
    max_retries=3,
    groq_api_key=GROQ_API_KEY,
)

# Provider 2: Cloudflare Workers AI — @cf/meta/llama-3.1-8b-instruct (first fallback)
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
    _log.warning("Cloudflare Workers AI credentials not set — Cloudflare fallback disabled")

# Provider 3: Gemini Flash — gemini-1.5-flash (second fallback)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    _log.warning("GEMINI_API_KEY not set — Gemini fallback disabled")


# ---------------------------------------------------------
# 4. LLM Fallback Chain — Streaming Providers
# ---------------------------------------------------------
# Each provider is an async generator yielding text chunks.
# The fallback orchestrator tries them in order: Groq → Cloudflare → Gemini.
# If a provider fails BEFORE yielding any tokens, the next one is tried.
# If it fails AFTER partial streaming, the error is propagated (can't retry).

async def _stream_groq(system_prompt: str, user_query: str):
    """
    Stream response from Groq via LangChain ChatGroq.
    Uses direct message objects to avoid curly-brace escaping issues
    in code context that would break ChatPromptTemplate interpolation.
    """
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_query)]
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content


async def _stream_cloudflare(system_prompt: str, user_query: str):
    """
    Stream response from Cloudflare Workers AI via httpx SSE.
    Model: @cf/meta/llama-3.1-8b-instruct
    Endpoint: POST https://api.cloudflare.com/client/v4/accounts/{id}/ai/run/{model}
    """
    model_path = "@cf/meta/llama-3.1-8b-instruct"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model_path}"
    )
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    text = chunk.get("response", "")
                    if text:
                        yield text
                except json.JSONDecodeError:
                    continue


async def _stream_gemini(system_prompt: str, user_query: str):
    """
    Stream response from Google Gemini Flash via google-generativeai SDK.
    Model: gemini-1.5-flash
    Uses async streaming: generate_content_async(stream=True).
    """
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_prompt,
    )
    response = await model.generate_content_async(user_query, stream=True)
    async for chunk in response:
        if chunk.text:
            yield chunk.text


def _get_available_providers():
    """
    Returns an ordered list of (provider_name, stream_function) tuples
    for all LLM providers whose credentials are configured.
    """
    providers = []
    if GROQ_API_KEY:
        providers.append(("groq", _stream_groq))
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
        providers.append(("cloudflare", _stream_cloudflare))
    if GEMINI_API_KEY:
        providers.append(("gemini", _stream_gemini))
    return providers


# ---------------------------------------------------------
# 5. API Endpoints
# ---------------------------------------------------------
@app.post("/api/ingest", status_code=202)
async def ingest(request: IngestRequest, current_user: str = Depends(get_current_user)):
    """ Locked Down Ingestion route.
    Accepts a sessionId and repositoryUrl, dispatches the ingestion
    task to the Celery worker via Redis, and returns immediately.
    """
    process_repository.delay(
        payload={"sessionId": request.sessionId, "repositoryUrl": request.repositoryUrl}
    )
    return JSONResponse(
        status_code=202,
        content={
            "message": "Ingestion started in the background.",
            "sessionId": request.sessionId,
        },
    )

@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-engine-active"}

@app.post("/chat/{session_id}")
@limiter.limit(f"{DAILY_CHAT_LIMIT}/day")
async def chat(request: Request, session_id: str, chat_request: ChatRequest, current_user: str = Depends(get_current_user)):
    """ Locked down secure streaming RAG endpoint with LLM fallback chain,
    Redis response caching, and conversation memory.

    Order of operations per request:
    1. Check Redis cache → if HIT, stream word-by-word and return immediately.
    2. Load conversation history from Redis (last 6 message pairs).
    3. Embed query locally and vector-search MongoDB Atlas (existing code).
    4. Rerank retrieved chunks with cross-encoder (existing code).
    5. Build RAG prompt WITH conversation history.
    6. Try LLM providers in fallback order: Groq → Cloudflare → Gemini.
    7. Stream response to client as SSE.
    8. After stream ends: save to Redis cache + save to conversation history.
    """
    if not chat_request.query or not chat_request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    user_query = chat_request.query.strip()

    # -------------------------------------------------
    # STEP 1: LLM RESPONSE CACHE — Check
    # -------------------------------------------------
    cache_key = "llm_cache:" + hashlib.sha256(
        f"{session_id}:{user_query.strip().lower()}".encode()
    ).hexdigest()

    try:
        cached_response = redis_client.get(cache_key)
        if cached_response:
            _log.info("Cache hit, serving from Redis", extra={"session_id": session_id})

            async def stream_cache():
                words = cached_response.split(" ")
                for i, word in enumerate(words):
                    # Reconstruct spacing: first word has no leading space,
                    # subsequent words get a space prepended.
                    token = word if i == 0 else " " + word
                    yield f"data: {json.dumps({'text': token})}\n\n"
                    await asyncio.sleep(0.02)
                yield f"data: {json.dumps({'done': True})}\n\n"

            return StreamingResponse(
                stream_cache(),
                media_type="text/event-stream",
                headers={"X-Cache": "HIT"},
            )
    except Exception as e:
        _log.warning("Cache check failed", extra={"session_id": session_id, "error": str(e)})

    # -------------------------------------------------
    # STEP 2: CONVERSATION MEMORY — Retrieve
    # -------------------------------------------------
    history_key = f"chat_history:{session_id}"
    history_context = ""
    try:
        # LRANGE 0 11 → last 12 items (6 user + 6 assistant messages).
        # LPUSH pushes to head, so index 0 is newest. Reverse for chronological order.
        raw_history = redis_client.lrange(history_key, 0, 11)
        if raw_history:
            chronological = list(reversed(raw_history))
            history_context = "\n\nPrevious conversation:\n"
            for i in range(0, len(chronological) - 1, 2):
                try:
                    item_a = json.loads(chronological[i])
                    item_b = json.loads(chronological[i + 1])
                    if item_a.get("role") == "user" and item_b.get("role") == "assistant":
                        history_context += f"User: {item_a['content']}\nAssistant: {item_b['content']}\n"
                    elif item_a.get("role") == "assistant" and item_b.get("role") == "user":
                        history_context += f"User: {item_b['content']}\nAssistant: {item_a['content']}\n"
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        _log.warning("History retrieval failed", extra={"session_id": session_id, "error": str(e)})

    async def generate_stream():
        try:
            # -------------------------------------------------
            # STEP 3: Retrieve relevant code chunks from Atlas
            # -------------------------------------------------
            context_text = ""
            try:
                # GAP-3 FIX: Scope the search to this session only so User A
                # cannot retrieve User B's code vectors (vector isolation).
                # Retry similarity search on transient API errors (e.g. 429/503)
                retrieved_docs = None
                max_search_attempts = 5
                search_backoff = 3.0
                for attempt in range(1, max_search_attempts + 1):
                    try:
                        retrieved_docs = get_vector_store().similarity_search(
                            user_query,
                            k=RETRIEVAL_TOP_K,
                            pre_filter={"session_id": {"$eq": session_id}},
                        )
                        break
                    except Exception as search_exc:
                        if attempt == max_search_attempts:
                            _log.error("similarity_search failed after max attempts", extra={"session_id": session_id, "attempts": max_search_attempts, "error": str(search_exc)})
                            raise search_exc
                        wait = _parse_retry_delay_secs(search_exc, default=search_backoff)
                        _log.warning("similarity_search failed, retrying", extra={"session_id": session_id, "attempt": attempt, "max_attempts": max_search_attempts, "retry_in_secs": round(wait, 1)})
                        await asyncio.sleep(wait)
                        search_backoff = min(search_backoff * 2.0, 120.0)

                if retrieved_docs:
                    # -----------------------------------------
                    # STEP 4: Rerank with cross-encoder
                    # -----------------------------------------
                    _log.info("Reranking candidates", extra={
                        "session_id": session_id,
                        "candidates": len(retrieved_docs),
                        "rerank_top_k": RERANK_TOP_K,
                    })
                    reranked_docs = rerank_documents(user_query, retrieved_docs, top_k=RERANK_TOP_K)

                    context_text = "\n\n---\n\n".join(
                        doc.page_content for doc in reranked_docs
                    )
                    _log.info("Context retrieved and reranked", extra={
                        "session_id": session_id,
                        "candidates_retrieved": len(retrieved_docs),
                        "chunks_after_rerank": len(reranked_docs),
                    })
                else:
                    _log.info("No matching documents for session", extra={"session_id": session_id})
            except Exception as retrieval_err:
                err_detail = str(retrieval_err)
                _log.error("Vector retrieval failed", extra={"session_id": session_id, "error": err_detail})
                yield f"data: {json.dumps({'error': f'Vector retrieval failed — your repository may still be indexing or the Atlas Search index is not ready. Detail: {err_detail}'})}\n\n"
                return

            # -------------------------------------------------
            # STEP 5: Build RAG prompt WITH conversation history
            # -------------------------------------------------
            if context_text:
                # RAG mode: inject retrieved codebase context + history
                system_prompt = (
                    "You are an elite software architecture assistant named RAGnarok. "
                    "Use the following retrieved codebase snippets to answer the user's question accurately. "
                    "Reference specific file names, functions, or patterns from the context when relevant. "
                    "If the answer is not contained within the provided context, state that clearly. "
                    "Do not hallucinate code that isn't there.\n\n"
                    f"Codebase Context:\n{context_text}"
                    f"{history_context}"
                )
            else:
                # Fallback mode: no context available, answer directly
                system_prompt = (
                    "You are an elite software architecture assistant named RAGnarok. "
                    "No codebase has been ingested yet, so you have no repository context. "
                    "Answer the user's question using your general knowledge. "
                    "If the question seems to be about a specific codebase, suggest they ingest "
                    "a repository first using the Ingest Repository panel."
                    f"{history_context}"
                )

            # -------------------------------------------------
            # STEP 6 & 7: LLM Fallback Chain — Stream to client
            # -------------------------------------------------
            full_response = []
            provider_used = None
            providers = _get_available_providers()
            last_error = None

            for provider_name, stream_fn in providers:
                try:
                    yielded_any = False
                    full_response = []
                    async for chunk in stream_fn(system_prompt, user_query):
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                        yielded_any = True
                    provider_used = provider_name
                    _log.info("LLM provider used", extra={"provider": provider_name, "session_id": session_id})
                    break  # Success — exit the fallback loop
                except Exception as provider_exc:
                    # pyrefly: ignore [unbound-name]
                    if yielded_any:
                        # Partial data already sent to client — cannot retry/fallback
                        _log.error("Stream interrupted midway", extra={
                            "provider": provider_name,
                            "session_id": session_id,
                            "error": str(provider_exc),
                        })
                        raise provider_exc
                    # Log the appropriate level based on error type
                    if isinstance(provider_exc, GroqRateLimitError) or "429" in str(provider_exc):
                        _log.warning("LLM provider rate-limited, trying next", extra={
                            "provider": provider_name,
                            "session_id": session_id,
                            "error": str(provider_exc),
                        })
                    else:
                        _log.warning("LLM provider failed, trying next", extra={
                            "provider": provider_name,
                            "session_id": session_id,
                            "error": str(provider_exc),
                        })
                    last_error = provider_exc
                    continue

            if provider_used is None:
                _log.error("All LLM providers exhausted", extra={
                    "session_id": session_id,
                    "last_error": str(last_error),
                })
                yield f"data: {json.dumps({'error': 'All LLM providers exhausted. Try again later.'})}\n\n"
                return

            # -------------------------------------------------
            # STEP 8 & 9: Save to Redis cache + conversation history
            # -------------------------------------------------
            final_answer = "".join(full_response)
            try:
                # Cache the full response for 1 hour (3600 seconds)
                if final_answer:
                    redis_client.set(cache_key, final_answer, ex=3600)

                # Store conversation pair as JSON in Redis list
                # LPUSH user first, then assistant (so head = newest assistant)
                redis_client.lpush(
                    history_key,
                    json.dumps({"role": "user", "content": user_query}),
                )
                redis_client.lpush(
                    history_key,
                    json.dumps({"role": "assistant", "content": final_answer}),
                )
                # Keep only last 12 items (6 user + 6 assistant = 6 pairs)
                redis_client.ltrim(history_key, 0, 11)
                # Reset TTL to 2 hours on each message
                redis_client.expire(history_key, 7200)
            except Exception as e:
                _log.warning("Failed to save cache or history", extra={
                    "session_id": session_id,
                    "error": str(e),
                })

            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            _log.error("Streaming error", extra={"session_id": session_id, "error": str(e)})
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"X-Cache": "MISS"},
    )

# ---------------------------------------------------------
# Ingestion API (Triggered by api-gateway BullMQ worker)
# ---------------------------------------------------------
@app.post("/api/ingest", status_code=202)
async def trigger_ingestion(request: IngestRequest, current_user: str = Depends(get_current_user)):
    """
    Receives an ingestion request from the api-gateway's BullMQ worker 
    and dispatches it to the Celery task queue.
    """
    _log.info("Dispatching Celery task", extra={"session_id": request.sessionId, "repo": request.repositoryUrl})
    process_repository.delay(
        payload={
            "sessionId": request.sessionId,
            "repositoryUrl": request.repositoryUrl
        }
    )
    return {"message": "Ingestion started", "sessionId": request.sessionId}

# ---------------------------------------------------------
# GAP-2 FIX: Session status polling endpoint
# Frontend polls this to know when Celery ingestion finishes.
# ---------------------------------------------------------
@app.get("/api/session/{session_id}")
async def get_session_status(session_id: str, current_user: str = Depends(get_current_user)):
    """Returns the current ingestion status for a given session."""
    # Bug #2 Fix: Always use the explicit database name that both the
    # api-gateway (Mongoose) and this service agree on.  The Atlas URI in
    # .env has no database path component, so get_default_database() would
    # throw and the old fallback was non-deterministic.
    db = mongo_client.get_database("api-gateway")
    session = db.sessions.find_one(
        {"sessionId": session_id},
        {"_id": 0, "sessionId": 1, "status": 1, "errorLog": 1}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/auth/github")
async def github_login(payload: dict):
    """
    Exchanges a GitHub authorization code for an application JWT token.
    """
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Step 1: Exchange code for GitHub access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            }
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Invalid code or GitHub credentials")

        # Step 2: Fetch user profile from GitHub
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {access_token}"}
        )
        user_profile = user_response.json()
        github_username = user_profile.get("login") # This will fetch "ashank"

    # Step 3: Issue our own application JWT token rooted in their GitHub identity
    app_jwt = create_access_token(data={"sub": github_username})
    
    return {"access_token": app_jwt, "token_type": "bearer", "username": github_username}