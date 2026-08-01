import os
import re
import json
import hashlib
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

# LangChain & AI Imports
# pyrefly: ignore [missing-import]
from langchain_huggingface import HuggingFaceEmbeddings
# pyrefly: ignore [missing-import]
from langchain_groq import ChatGroq
# pyrefly: ignore [missing-import]
from langchain_mongodb import MongoDBAtlasVectorSearch
# pyrefly: ignore [missing-import]
from langchain_core.prompts import ChatPromptTemplate
# pyrefly: ignore [missing-import]
from langchain_core.output_parsers import StrOutputParser
# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
import certifi

# Cross-Encoder for reranking retrieved chunks
# pyrefly: ignore [missing-import]
from sentence_transformers import CrossEncoder

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

# Local CPU embedding model — no API key, no quota, 768-dim output.
# BAAI/bge-base-en-v1.5 significantly outperforms MiniLM on code retrieval.
# Must match the model used in worker.py and the Atlas index numDimensions (768).
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-base-en-v1.5",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

# Initialize MongoDB Atlas Vector Search integration
vector_store = MongoDBAtlasVectorSearch(
    collection=collection,
    embedding=embeddings,
    index_name="vector_index", # Name of the Atlas Search Index you will create
    text_key="text",
    embedding_key="embedding",
)

# ---------------------------------------------------------
# Cross-Encoder Reranker (local CPU, no API calls)
# ---------------------------------------------------------
# After the bi-encoder retrieves top-K candidates, the cross-encoder
# scores each (query, chunk) pair jointly for much higher precision.
# Model: ms-marco-MiniLM-L-6-v2 — fast, accurate, runs on CPU.
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_TOP_K = 5  # Keep top 5 after reranking
RETRIEVAL_TOP_K = 20  # Retrieve top 20 candidates for reranking

_log.info("Loading cross-encoder reranker", extra={"model": RERANK_MODEL_NAME})
reranker = CrossEncoder(RERANK_MODEL_NAME, device="cpu")
_log.info("Cross-encoder reranker loaded")


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
    scores = reranker.predict(pairs)

    # Attach scores and sort descending
    scored_docs = sorted(
        zip(documents, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    # Return only the top_k documents
    return [doc for doc, _score in scored_docs[:top_k]]


# ---------------------------------------------------------
# 3. LLM Configuration (Groq — free tier, 14,400 req/day)
# ---------------------------------------------------------
# llama-3.3-70b-versatile: best free model for code understanding & RAG
# Groq's LPU hardware makes this the fastest inference available.
# To swap back to Gemini: replace ChatGroq with ChatGoogleGenerativeAI
# and set model="gemini-2.5-flash" — no other code changes needed.
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
# ---------------------------------------------------------
# 4. LangChain Prompt & Chain (built dynamically per-request in /chat)
# ---------------------------------------------------------
# The chat endpoint constructs the prompt at request time based on
# whether vector context was retrieved. This avoids crashes when the
# collection is empty (no repos ingested yet).


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
    """ Locked down secure streaming RAG endpoint.
    RAG-powered chat endpoint:
    1. Converts the user's query into a vector via GoogleGenerativeAIEmbeddings.
    2. Performs similarity search on rag_db.code_vectors via MongoDBAtlasVectorSearch.
    3. If context is found, injects it into a system prompt alongside the user's question.
    4. If the collection is empty (no repos ingested), falls back to a direct LLM call.
    5. Streams Gemini's response back to the frontend as SSE chunks.
    """
    if not chat_request.query or not chat_request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    user_query = chat_request.query.strip()
    normalized_query = " ".join(user_query.lower().split())

    # -------------------------------------------------
    # LLM RESPONSE CACHE (Check)
    # -------------------------------------------------
    cache_hash = hashlib.sha256(f"{session_id}:{normalized_query}".encode("utf-8")).hexdigest()
    cache_key = f"chat_cache:{cache_hash}"

    try:
        cached_response = redis_client.get(cache_key)
        if cached_response:
            _log.info("Cache hit", extra={"session_id": session_id})
            async def stream_cache():
                yield f"data: {json.dumps({'text': cached_response})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            return StreamingResponse(stream_cache(), media_type="text/event-stream")
    except Exception as e:
        _log.warning("Cache check failed", extra={"session_id": session_id, "error": str(e)})

    async def generate_stream():
        try:
            # -------------------------------------------------
            # Step 1: Retrieve relevant code chunks from Atlas
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
                        retrieved_docs = vector_store.similarity_search(
                            user_query,
                            k=RETRIEVAL_TOP_K,
                            pre_filter={"session_id": {"$eq": session_id}},
                        )
                        break
                    except Exception as search_exc:
                        if attempt == max_search_attempts:
                            _log.error("similarity_search failed after max attempts", extra={"session_id": session_id, "attempts": max_search_attempts, "error": str(search_exc)})
                            raise search_exc
                        import asyncio
                        wait = _parse_retry_delay_secs(search_exc, default=search_backoff)
                        _log.warning("similarity_search failed, retrying", extra={"session_id": session_id, "attempt": attempt, "max_attempts": max_search_attempts, "retry_in_secs": round(wait, 1)})
                        await asyncio.sleep(wait)
                        search_backoff = min(search_backoff * 2.0, 120.0)

                if retrieved_docs:
                    # -----------------------------------------
                    # Step 1b: Rerank with cross-encoder
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
            # CONVERSATION MEMORY (Retrieve)
            # -------------------------------------------------
            history_key = f"chat_history:{session_id}"
            history_context = ""
            try:
                # LPUSH pushes to head, so index 0 is newest. Reversing it gives chronological order.
                raw_history = redis_client.lrange(history_key, 0, 5)
                if raw_history:
                    chronological_history = reversed(raw_history)
                    history_context = "\nConversation History:\n" + "\n".join(chronological_history) + "\n"
            except Exception as e:
                _log.warning("History retrieval failed", extra={"session_id": session_id, "error": str(e)})

            # -------------------------------------------------
            # Step 2: Build prompt based on whether context exists
            # -------------------------------------------------
            if context_text:
                # RAG mode: inject retrieved codebase context
                chat_prompt = ChatPromptTemplate.from_messages([
                    ("system",
                     "You are an elite software architecture assistant named RAGnarok. "
                     "Use the following retrieved codebase snippets to answer the user's question accurately. "
                     "Reference specific file names, functions, or patterns from the context when relevant. "
                     "If the answer is not contained within the provided context, state that clearly. "
                     "Do not hallucinate code that isn't there.\n\n"
                     "Codebase Context:\n{context}\n{history}"),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"context": context_text, "history": history_context, "question": user_query}
            else:
                # Fallback mode: no context available, answer directly
                chat_prompt = ChatPromptTemplate.from_messages([
                    ("system",
                     "You are an elite software architecture assistant named RAGnarok. "
                     "No codebase has been ingested yet, so you have no repository context. "
                     "Answer the user's question using your general knowledge. "
                     "If the question seems to be about a specific codebase, suggest they ingest "
                     "a repository first using the Ingest Repository panel.\n{history}"),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"history": history_context, "question": user_query}

            # -------------------------------------------------
            # Step 3: Stream the LLM response as SSE
            # -------------------------------------------------
            max_llm_attempts = 5
            llm_backoff = 5.0
            full_response = []
            for attempt in range(1, max_llm_attempts + 1):
                try:
                    yielded_chunks = False
                    full_response = []
                    async for chunk in chain.astream(stream_input):
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                        yielded_chunks = True
                    break
                except Exception as stream_exc:
                    if yielded_chunks:
                        _log.error("Stream interrupted midway", extra={"session_id": session_id, "error": str(stream_exc)})
                        raise stream_exc
                    if attempt == max_llm_attempts:
                        _log.error("Stream failed after max attempts", extra={"session_id": session_id, "attempts": max_llm_attempts, "error": str(stream_exc)})
                        raise stream_exc
                    _log.warning("Stream init failed, retrying", extra={"session_id": session_id, "attempt": attempt, "max_attempts": max_llm_attempts, "retry_in_secs": llm_backoff})
                    import asyncio
                    await asyncio.sleep(llm_backoff)
                    llm_backoff *= 2.0

            # -------------------------------------------------
            # SAVE CACHE & CONVERSATION HISTORY
            # -------------------------------------------------
            final_answer = "".join(full_response)
            try:
                if final_answer:
                    # Cache response for 1 hour
                    redis_client.setex(cache_key, 3600, final_answer)
                
                # Push User then Assistant so reverse order is chronological
                redis_client.lpush(history_key, f"User: {user_query}")
                redis_client.lpush(history_key, f"Assistant: {final_answer}")
                # Keep only last 6 messages
                redis_client.ltrim(history_key, 0, 5)
                # Auto-expire after 2 hours
                redis_client.expire(history_key, 7200)
            except Exception as e:
                _log.warning("Failed to save cache or history", extra={"session_id": session_id, "error": str(e)})

            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            _log.error("Streaming error", extra={"session_id": session_id, "error": str(e)})
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

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
    