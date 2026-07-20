import os
import re
import json
from datetime import datetime, timezone, timedelta
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load .env FIRST — before any os.getenv() call
load_dotenv()

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
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

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

# Connect to Atlas using synchronous MongoClient for LangChain
# tlsCAFile=certifi.where() fixes TLSV1_ALERT_INTERNAL_ERROR on Windows/older OpenSSL
# tlsAllowInvalidCertificates=True is a dev-only fallback for Windows TLS handshake issues
mongo_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)

# IMPORTANT: Ensure these match what you set in your ingestion worker!
DB_NAME = "rag_db" 
COLLECTION_NAME = "code_vectors" 
collection = mongo_client[DB_NAME][COLLECTION_NAME]

# Local CPU embedding model — no API key, no quota, 384-dim output.
# Must match the model used in worker.py and the Atlas index numDimensions.
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
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
                            k=4,
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
                    context_text = "\n\n---\n\n".join(
                        doc.page_content for doc in retrieved_docs
                    )
                    _log.info("Context retrieved", extra={"session_id": session_id, "chunk_count": len(retrieved_docs)})
                else:
                    _log.info("No matching documents for session", extra={"session_id": session_id})
            except Exception as retrieval_err:
                err_detail = str(retrieval_err)
                _log.error("Vector retrieval failed", extra={"session_id": session_id, "error": err_detail})
                yield f"data: {json.dumps({'error': f'Vector retrieval failed — your repository may still be indexing or the Atlas Search index is not ready. Detail: {err_detail}'})}\n\n"
                return

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
                     "Codebase Context:\n{context}"),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"context": context_text, "question": user_query}
            else:
                # Fallback mode: no context available, answer directly
                chat_prompt = ChatPromptTemplate.from_messages([
                    ("system",
                     "You are an elite software architecture assistant named RAGnarok. "
                     "No codebase has been ingested yet, so you have no repository context. "
                     "Answer the user's question using your general knowledge. "
                     "If the question seems to be about a specific codebase, suggest they ingest "
                     "a repository first using the Ingest Repository panel."),
                    ("human", "{question}")
                ])
                chain = chat_prompt | llm | StrOutputParser()
                stream_input = {"question": user_query}

            # -------------------------------------------------
            # Step 3: Stream the LLM response as SSE
            # -------------------------------------------------
            max_llm_attempts = 5
            llm_backoff = 5.0
            for attempt in range(1, max_llm_attempts + 1):
                try:
                    yielded_chunks = False
                    async for chunk in chain.astream(stream_input):
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

            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            _log.error("Streaming error", extra={"session_id": session_id, "error": str(e)})
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

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
    