# RAGnarok 🔥

> **An Autonomous AI Software Engineer.** Point it at any GitHub repository — RAGnarok ingests every file, builds a semantic memory of the codebase, and lets you chat with it in real time. Ask about architecture, find bugs, or command it to write a fix and open a Pull Request automatically.

---

## What is RAGnarok?

Most developers spend days reading an unfamiliar codebase before they can contribute. RAGnarok eliminates that. Paste a GitHub URL — in minutes, an AI that has read and understood every file is ready to answer your questions, explain architecture decisions, locate bugs, and soon, write fixes autonomously.

**Built as a masterclass in distributed systems** — polyglot microservices, event-driven architecture, background job processing, vector search, streaming AI, and CI/CD.

---

## Architecture

RAGnarok is a **polyglot microservices system** across five independent services that communicate via HTTP and a shared Redis message broker.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User (Browser)                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────────┐
│              Next.js Frontend  (Port 3000)                      │
│         GitHub OAuth · Ingestion Panel · Chat UI (SSE)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────────┐
│           Node.js / Express API Gateway  (Port 3001)            │
│     Session Management · BullMQ Producer · JWT Validation       │
└──────┬────────────────────────────────────────┬─────────────────┘
       │ BullMQ Job                             │ HTTP Poll
       ▼                                        ▼
┌─────────────┐                      ┌──────────────────┐
│    Redis    │                      │  MongoDB Atlas   │
│   (Alpine)  │                      │  Sessions + Jobs │
│  Port 6379  │                      └──────────────────┘
└──────┬──────┘
       │ Celery Task
┌──────▼──────────────────────────────────────────────────────────┐
│              Python FastAPI + Celery  (Port 8000)               │
│                                                                 │
│  ┌─────────────────────┐    ┌──────────────────────────────┐    │
│  │   Celery Worker     │    │      FastAPI Endpoints       │    │
│  │                     │    │                              │    │
│  │ 1. Clone repo       │    │ POST /chat/{session_id}      │    │
│  │ 2. Filter sources   │    │   · Embed query (local)      │    │
│  │ 3. Chunk code       │    │   · Vector search Atlas      │    │
│  │ 4. Embed locally    │    │   · Rerank top-20 → top-5    │    │
│  │ 5. Store vectors    │    │   · Stream via SSE (Groq)    │    │
│  └─────────────────────┘    └──────────────────────────────┘    │
└─────────────────────────────────────┬───────────────────────────┘
                                      │ Vector Search
                              ┌───────▼──────────┐
                              │  MongoDB Atlas   │
                              │  Vector Search   │
                              │  (code_vectors)  │
                              └──────────────────┘
```

| Service | Runtime | Responsibility |
|---|---|---|
| **frontend** | Next.js 14 / TypeScript | Chat UI, OAuth flow, ingestion panel, SSE streaming |
| **api-gateway** | Node.js 18 / Express / TypeScript | Entry point, session management, BullMQ producer |
| **rag-engine** | Python 3.11 / FastAPI / Celery | Ingestion pipeline, embedding, RAG chat, LLM streaming |
| **Redis** | Docker Alpine | BullMQ ↔ Celery message broker, session cache |
| **MongoDB Atlas** | Cloud (M0 free) | Session storage, vector index (`code_vectors`) |

---

## Key Engineering Decisions

### Why FastAPI over Go?
The bottleneck in a RAG system is never the HTTP framework — it's the LLM (500–2000ms). The real constraint is ecosystem: LangChain, sentence-transformers, Celery, cross-encoders, and every advanced RAG library are Python-first. Go has no equivalent. FastAPI's async model handles I/O-bound concurrency cleanly, and Pydantic gives compile-time-like schema validation.

### Why BullMQ + Celery (two queues)?
Node.js handles HTTP and produces BullMQ jobs. Python consumes Celery tasks. These don't natively bridge — so `ingestionWorker.ts` acts as a BullMQ consumer that forwards jobs via HTTP to FastAPI, which dispatches Celery tasks. Redis hosts both queue namespaces intentionally isolated. This keeps each service in its strongest language without coupling.

### Why MongoDB Atlas over Qdrant?
MongoDB Atlas Vector Search unified our vector store with our session, user, and job-state storage — one connection string, one free tier, one service to monitor. At our scale (<100k vectors), retrieval quality is equivalent. Qdrant would give marginally better recall at millions of vectors but adds a 6th service and a second free-tier dependency with no user-visible benefit today.

### Why local embeddings?
Gemini's hosted embedding API hit per-minute AND per-day quotas during ingestion of large repos (HTTP 429 within minutes). Switching to `BAAI/bge-base-en-v1.5` running locally via `sentence-transformers` gives 768-dimensional embeddings, zero API calls, zero rate limits, and better code retrieval quality than Gemini on most benchmarks — at the cost of CPU time during ingestion.

---

## Features

- **One-command ingestion** — Paste any public GitHub URL. RAGnarok clones it (shallow depth-1), filters source files, chunks them with AST-aware boundaries, embeds with a local 768-dim model, and stores vectors in Atlas. No file size limits enforced by APIs.
- **Streaming RAG chat** — Queries embed locally, search Atlas with session-scoped pre-filters, rerank top-20 chunks to top-5 via cross-encoder, and stream the LLM answer token-by-token via SSE. First token arrives in ~500ms.
- **Vector isolation security** — Every chunk is tagged with `session_id`. Pre-filters on every similarity search guarantee User A cannot retrieve User B's vectors. Verified by a dedicated security test.
- **GitHub OAuth + JWT** — Login with GitHub. HS256 JWT issued on OAuth code exchange. All protected endpoints validate JWT via FastAPI `Depends()`. Internal service calls use a shared `X-Internal-Key` header, bypassing user auth safely.
- **Source code filtering** — Binary files, lock files (`package-lock.json`, `yarn.lock`, `poetry.lock`), and build artifacts (`node_modules`, `dist`, `.next`, `__pycache__`) are filtered before embedding. Only meaningful source contributes to the vector index.
- **Retry + exponential backoff** — All embedding batches and LLM calls retry up to 8 times with exponential backoff. Server-suggested retry delays from 429 responses are parsed and honored.
- **Async job queue** — Ingestion never blocks the API. BullMQ jobs queue immediately, Celery workers process asynchronously, frontend polls `GET /api/session/:id` for status updates.
- **Full test suite** — 18 tests across auth and RAG pipeline, using `mongomock`, `MockEmbeddings`, `MockLLM` — zero real API calls in CI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React, TypeScript, Tailwind CSS |
| API Gateway | Node.js, Express, TypeScript, BullMQ, Mongoose |
| AI Engine | Python, FastAPI, Celery, LangChain |
| Embeddings | `BAAI/bge-base-en-v1.5` (local, 768-dim, CPU) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (local) |
| LLM | Groq `llama-3.3-70b-versatile` (streaming) |
| Vector DB | MongoDB Atlas Vector Search |
| Cache / Queue | Redis (Upstash in prod) |
| Auth | GitHub OAuth 2.0, HS256 JWT |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Deployment | Vercel (frontend), Railway (backend) |

---

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker + Docker Compose
- MongoDB Atlas account (free M0 tier)
- Groq API key (free at [console.groq.com](https://console.groq.com))
- GitHub OAuth App

### 1. Clone the repo

```bash
git clone https://github.com/Ashank001/ragnarok.git
cd ragnarok
```

### 2. Environment variables

**`api-gateway/.env`**
```env
MONGODB_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/api-gateway
REDIS_URL=redis://localhost:6379/0
INTERNAL_API_KEY=your-shared-secret
RAG_ENGINE_URL=http://localhost:8000
PORT=3001
```

**`rag-engine/.env`**
```env
MONGODB_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/
REDIS_URL=redis://localhost:6379/0
GROQ_API_KEY=gsk_...
JWT_SECRET_KEY=your-jwt-secret
INTERNAL_API_KEY=your-shared-secret
GITHUB_CLIENT_ID=your-github-oauth-client-id
GITHUB_CLIENT_SECRET=your-github-oauth-client-secret
CORS_ORIGINS=http://localhost:3000
```

**`frontend/.env.local`**
```env
NEXT_PUBLIC_API_GATEWAY_URL=http://localhost:3001
NEXT_PUBLIC_RAG_ENGINE_URL=http://localhost:8000
GITHUB_CLIENT_ID=your-github-oauth-client-id
```

### 3. MongoDB Atlas — create vector index

In your Atlas console, create a Search Index on `rag_db.code_vectors`:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "metadata.session_id"
    }
  ]
}
```

> ⚠️ Index name must be `vector_index`. This step is required — ingestion will succeed but chat will return no results without it.

### 4. Start backend with Docker

```bash
docker-compose up --build
```

This starts: Redis · API Gateway (port 3001) · RAG Engine + Celery worker (port 8000)

### 5. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

---

## API Reference

### RAG Engine (FastAPI — port 8000)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Health check |
| `POST` | `/api/auth/github` | None | GitHub OAuth code exchange → JWT |
| `POST` | `/api/ingest` | JWT or Internal Key | Dispatch Celery ingestion task |
| `GET` | `/api/session/{session_id}` | JWT | Poll ingestion status |
| `POST` | `/chat/{session_id}` | JWT | Streaming RAG chat (SSE) |

### API Gateway (Express — port 3001)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/ingest` | JWT | Create session + enqueue BullMQ job |
| `GET` | `/api/status/:sessionId` | JWT | Poll session status from MongoDB |

---

## Testing

```bash
cd rag-engine

# Install test dependencies
pip install -r requirements.txt

# Run full test suite
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing

# Run stress tests (requires live server)
python stress_test.py
```

**Test coverage:**

| File | Tests | What's covered |
|---|---|---|
| `test_auth.py` | 10 | JWT validation, OAuth flow, expired/tampered tokens, missing claims |
| `test_rag.py` | 8 | Ingestion dispatch, session CRUD, streaming chat, vector isolation security, file filter |

All tests use in-memory mocks — no Atlas connection, no Groq API call, no GitHub OAuth required.

---

## Challenges & Solutions

| # | Challenge | Solution |
|---|---|---|
| 1 | Gemini API quota exhausted during ingestion (HTTP 429) | Switched to local `bge-base-en-v1.5` — zero API calls, better code quality |
| 2 | Frontend had no way to know when ingestion finished | Added `GET /api/session/{id}` polling endpoint with auth guard |
| 3 | User A could retrieve User B's vectors (data leak) | Added `pre_filter: {session_id: $eq}` to every similarity search + security test |
| 4 | Windows TLS handshake failures with MongoDB Atlas | Added `tlsCAFile=certifi.where()` to all `MongoClient()` initializations |
| 5 | `shutil.rmtree()` fails on Windows (WinError 5) | Version-conditional `_rmtree_safe()` with `os.chmod` before retry |
| 6 | BullMQ (Node) and Celery (Python) don't natively bridge | BullMQ worker forwards jobs via HTTP to FastAPI, which dispatches Celery |
| 7 | BullMQ worker has no JWT to call protected FastAPI endpoints | `X-Internal-Key` shared secret bypasses user JWT for service-to-service calls |
| 8 | Celery connects to `localhost:6379` inside Docker (wrong host) | `REDIS_URL=redis://redis:6379/0` env override in `docker-compose.yml` |
| 9 | Celery retry flipped session to "failed" prematurely | Only set `failed` when `retries >= max_retries`, stay `processing` during retries |
| 10 | Binary files + lock files polluted the vector index | `is_source_file()` two-level filter: extension allowlist + directory blocklist |

---

## Project Structure

```
ragnarok/
├── frontend/                  # Next.js 14 app
│   ├── app/
│   │   ├── page.tsx           # Main chat + ingestion UI
│   │   └── auth/callback/     # GitHub OAuth callback
│   └── package.json
│
├── api-gateway/               # Node.js Express gateway
│   ├── src/
│   │   ├── index.ts           # Server entry point
│   │   ├── routes/ingest.ts   # POST /api/ingest, GET /api/status
│   │   ├── workers/ingestionWorker.ts  # BullMQ consumer
│   │   ├── models/            # Mongoose session models
│   │   └── config/            # DB + queue config
│   └── package.json
│
├── rag-engine/                # Python FastAPI + Celery
│   ├── main.py                # FastAPI app, /chat endpoint, SSE streaming
│   ├── worker.py              # Celery task: clone → filter → chunk → embed → store
│   ├── auth.py                # GitHub OAuth, JWT middleware
│   ├── config.py              # Celery + MongoDB initialization
│   ├── start.sh               # Docker entrypoint (uvicorn + celery)
│   ├── stress_test.py         # Concurrent load testing harness
│   ├── tests/
│   │   ├── conftest.py        # Mocks: MongoDB, embeddings, LLM, JWT
│   │   ├── test_auth.py       # 10 auth tests
│   │   └── test_rag.py        # 8 RAG pipeline tests
│   └── requirements.txt
│
├── docker-compose.yml         # Redis + api-gateway + rag-engine
└── README.md
```

---


## Author

**Ashank Ramakrishnan**
- GitHub: [@Ashank001](https://github.com/Ashank001)
- LinkedIn: [Ashank001](https://linkedin.com/in/Ashank001)

---
