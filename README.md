<![CDATA[<div align="center">

# ⚡ RAGnarok

**A Retrieval-Augmented Generation engine for codebase comprehension.**

Built with **FastAPI** · **Next.js 16** · **MongoDB Atlas Vector Search** · **Google Gemini**

---

</div>

## Table of Contents

- [Overview](#overview)
- [Completed Phases](#completed-phases)
- [Architecture Diagram](#architecture-diagram)
- [Directory Structure](#directory-structure)
- [Core Modules Explained](#core-modules-explained)
- [Data Flow: A → Z](#data-flow-a--z)
- [Environment Variables](#environment-variables)
- [Getting Started](#getting-started)
- [Tech Stack](#tech-stack)

---

## Overview

RAGnarok is a codebase comprehension tool that ingests Git repositories, splits them into semantically meaningful chunks, generates vector embeddings via Google's `gemini-embedding-001` model, stores them in **MongoDB Atlas Vector Search**, and exposes a real-time streaming chat interface powered by **Gemini 3.5 Flash**.

Users interact with the system through a polished **Next.js** chat UI. Every query is semantically matched against the indexed codebase, and the LLM generates contextually grounded answers streamed back token-by-token as **Server-Sent Events (SSE)**.

---

## Completed Phases

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1 — Backend Initialization** | ✅ Complete | FastAPI server configured with CORS, Pydantic request validation, health check endpoint, and a streaming `/chat/{session_id}` route. |
| **Phase 2 — MongoDB Atlas Vector Search** | ✅ Complete | Synchronous `MongoClient` connection to Atlas. `MongoDBAtlasVectorSearch` integration via LangChain with `gemini-embedding-001` embeddings. Retriever configured to return the top 4 nearest chunks. |
| **Phase 3 — Streaming Next.js Chat UI** | ✅ Complete | Full-featured React client component with SSE stream parsing, abort controller support, demo mode fallback, dark/light theming, sidebar session management, code block rendering with copy-to-clipboard, and auto-scrolling message history. |
| **Phase 4 — Celery Ingestion Worker** | ✅ Complete | Celery task (`worker.py`) that clones a Git repository via `GitLoader`, splits files with `RecursiveCharacterTextSplitter`, generates embeddings with `gemini-embedding-001`, and batch-uploads vectors to MongoDB Atlas Vector Search (`rag_db.code_vectors`). Includes automatic retry with exponential backoff and OS-safe temp directory cleanup. |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER BROWSER                            │
│                    Next.js 16  (port 3001)                      │
│                                                                 │
│   ┌──────────────┐    POST /chat/{session_id}    ┌───────────┐  │
│   │  page.tsx     │ ─────────────────────────────►│  FastAPI   │ │
│   │  (React SSR)  │ ◄─────── SSE text/event-stream │ (port 8000)│ │
│   └──────────────┘                                └─────┬─────┘ │
│                                                         │       │
│                                                         │       │
│                                              ┌──────────▼──────┐│
│                                              │  LangChain LCEL ││
│                                              │  RAG Pipeline   ││
│                                              └──────────┬──────┘│
│                                                         │       │
│                         ┌───────────────────────────────┤       │
│                         │                               │       │
│               ┌─────────▼─────────┐           ┌────────▼──────┐│
│               │  MongoDB Atlas    │           │  Google Gemini ││
│               │  Vector Search    │           │  3.5 Flash     ││
│               │  (rag_db /        │           │  (LLM)         ││
│               │   code_vectors)   │           └────────────────┘│
│               └───────────────────┘                             │
│                                                                 │
│   ┌──────────────┐         ┌───────────┐                        │
│   │  worker.py    │ ◄──────│   Redis    │  (Celery broker)      │
│   │  (Celery)     │ ───────│ (port 6379)│                       │
│   └──────────────┘         └───────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
RAG_P1/
├── docker-compose.yml          # Multi-container orchestration (Redis, API Gateway, RAG Engine, Frontend)
├── .gitignore                  # Unified ignore rules for Python, Node.js, and environment files
│
├── api-gateway/                # Express.js gateway (placeholder — future session routing layer)
│   ├── src/                    # Source directory for gateway logic
│   ├── package.json            # Node.js dependencies
│   └── .env.example            # Environment variable template
│
├── rag-engine/                 # Python FastAPI backend — the core intelligence layer
│   ├── main.py                 # FastAPI application entry point (routes, RAG chain, streaming)
│   ├── worker.py               # Celery background task for Git repo ingestion, embedding & vector upload
│   ├── config.py               # Shared configuration (Celery app, Motor async client, PyMongo sync client)
│   ├── requirements.txt        # Python dependencies (FastAPI, LangChain, pymongo, Celery, etc.)
│   ├── .env                    # Runtime secrets (gitignored)
│   └── .env.example            # Template: REDIS_URL, MONGO_URI, GOOGLE_API_KEY
│
└── frontend/                   # Next.js 16 application — the user-facing chat interface
    ├── app/
    │   ├── layout.tsx           # Root layout with Geist font family and global CSS imports
    │   ├── page.tsx             # Main chat UI (SSE consumer, message renderer, sidebar, theming)
    │   ├── globals.css          # Tailwind v4 CSS layer with light/dark CSS custom properties
    │   └── favicon.ico          # App favicon
    ├── public/                  # Static assets
    ├── package.json             # Next.js 16, React 19, Tailwind CSS v4
    ├── tsconfig.json            # TypeScript configuration
    ├── next.config.ts           # Next.js build configuration
    └── eslint.config.mjs        # ESLint flat config
```

---

## Core Modules Explained

### `rag-engine/main.py` — FastAPI Application Server

This is the heart of the backend. It performs four responsibilities on startup:

1. **CORS Middleware** — Allows cross-origin requests from the Next.js dev server (or any origin during development) using `CORSMiddleware`.

2. **MongoDB Atlas Vector Store** — Connects to the `rag_db.code_vectors` collection via `pymongo.MongoClient`. Initializes `MongoDBAtlasVectorSearch` with Google's `gemini-embedding-001` embedding model and configures an Atlas Search index named `vector_index`.

3. **LangChain LCEL Pipeline** — Constructs a Retrieval-Augmented Generation chain using LangChain Expression Language:
   ```
   Retriever (top-4 chunks) → format_docs → ChatPromptTemplate → Gemini 3.5 Flash → StrOutputParser
   ```
   The system prompt instructs the LLM to act as "RAGnarok," an architecture assistant that answers strictly from retrieved context.

4. **Streaming Endpoint** — Exposes `POST /chat/{session_id}` which accepts a `{ "query": "..." }` JSON body, invokes the LCEL chain via `rag_chain.astream()`, and yields each token as an SSE-formatted `data: {"text": "..."}` event. A final `data: {"done": true}` event signals stream completion.

---

### `frontend/app/page.tsx` — Next.js Chat Interface

An 800-line React client component (`"use client"`) that serves as the entire chat experience:

| Feature | Implementation |
|---------|---------------|
| **SSE Stream Parsing** | Uses `fetch()` with `ReadableStream` reader. Decodes chunks via `TextDecoder`, splits on `\n\n` boundaries, and parses each `data: {...}` JSON payload to progressively append tokens to the assistant message. |
| **Abort Controller** | Supports cancellation mid-stream. A `useRef<AbortController>` is passed to `fetch()` and wired to a "Stop Generating" button. |
| **Demo Mode Fallback** | On startup, probes `http://127.0.0.1:8000/chat/session_123`. If the backend is unreachable, switches to an in-memory simulated stream with canned responses for SSE, FastAPI, and general queries. |
| **Markdown Rendering** | Custom `renderMessageContent()` parser handles fenced code blocks (` ``` `), inline code (`` ` ``), and bold (`**text**`). Code blocks render in a `CodeBlock` component with language labels and a copy-to-clipboard button. |
| **Sidebar** | Left drawer with session history, new chat button, API connection status indicator (Online / Demo / Offline), dark/light theme toggle, and user profile display. Responsive — collapses on mobile with an overlay backdrop. |
| **Auto-Scroll** | A `useRef` div at the bottom of the message list triggers `scrollIntoView({ behavior: "smooth" })` on every message state change. |

---

### `rag-engine/worker.py` — Celery Ingestion Worker

The complete ingestion pipeline that transforms a GitHub repository URL into searchable vector embeddings:

1. **Celery Task Wrapper** — The `@celery_app.task(name='process-repo', bind=True, max_retries=2)` decorator registers the function with the Redis-brokered Celery queue. It accepts `sessionId` and `repositoryUrl` either as keyword arguments or nested inside a `payload` dict. Failed tasks are automatically retried with exponential backoff (60s, 120s).

2. **Repository Cloning** — Uses LangChain's `GitLoader` to clone the target repository into an OS-safe temporary directory created via `tempfile.mkdtemp()` (works on Windows, Linux, and macOS). Defaults to the `main` branch.

3. **Document Splitting** — Applies `RecursiveCharacterTextSplitter` with a chunk size of 1,000 characters and 200-character overlap. Each chunk's metadata is enriched with `session_id` and `repo_url` for traceability.

4. **Vector Embedding** — Initializes `GoogleGenerativeAIEmbeddings` with the `gemini-embedding-001` model to convert text chunks into 768-dimensional vectors.

5. **Atlas Vector Upload** — Creates a `MongoDBAtlasVectorSearch` instance pointed at `rag_db.code_vectors` (matching the retriever in `main.py`) and batch-uploads documents in groups of 50 via `vector_store.add_documents()` to avoid embedding API rate limits.

6. **Status Tracking** — Updates the MongoDB `sessions` collection at each stage: `processing` → `completed` (or `failed` with an `errorLog` field).

7. **Cleanup** — Removes the cloned repository from the temp directory in a `finally` block regardless of success or failure.

---

### `rag-engine/config.py` — Shared Configuration

Centralizes infrastructure clients used across the backend:

- **Celery App** — Configured with Redis as both broker and result backend (`redis://localhost:6379/0`).
- **Motor Client (async)** — An `AsyncIOMotorClient` for non-blocking MongoDB operations used by the worker's session status updates.
- **PyMongo Client (sync)** — A synchronous `MongoClient` required by LangChain's `MongoDBAtlasVectorSearch` for embedding uploads.
- **`get_db()`** — Returns the async Motor database instance, falling back to `"api-gateway"` if the URI doesn't specify a default database.
- **`get_sync_collection(db_name, collection_name)`** — Returns a synchronous pymongo collection for LangChain vector store operations.

---

## Data Flow: A → Z

The complete lifecycle of a user query, from keypress to rendered answer:

### Step 1 — User Submits a Message

The user types a query into the `<textarea>` in `page.tsx` and presses **Enter** (or clicks the send button). The `handleSendMessage()` function fires:

- The input is trimmed and validated (empty strings are rejected).
- A **user message** object is appended to the `messages` state array.
- An empty **assistant placeholder** message (with `isStreaming: true`) is appended immediately after — this is where streamed tokens will accumulate.
- A new `AbortController` is instantiated and stored in a ref for cancellation support.

### Step 2 — HTTP Request to FastAPI

The frontend issues a `POST` request to:

```
http://127.0.0.1:8000/chat/session_123
```

With the JSON body:

```json
{ "query": "How does the authentication middleware work?" }
```

The request is **not** using the EventSource API. Instead, it uses a standard `fetch()` call and manually reads the response body as a stream — this is necessary because SSE via `EventSource` only supports `GET` requests.

### Step 3 — FastAPI Receives the Request

The `chat()` route handler in `main.py`:

1. Validates the incoming `ChatRequest` model via Pydantic (ensures `query` is non-empty).
2. Returns a `StreamingResponse` with `media_type="text/event-stream"`.
3. The response body is produced by the `generate_stream()` async generator.

### Step 4 — LangChain RAG Pipeline Executes

Inside `generate_stream()`, the LCEL chain `rag_chain.astream(request.query)` is invoked. This triggers the following sequence:

```
User Query
    │
    ▼
┌─────────────────────────────────────────────┐
│  1. RETRIEVER                                │
│     MongoDBAtlasVectorSearch.as_retriever()   │
│     • Embeds the query using gemini-embedding-001 │
│     • Performs a vector similarity search     │
│       against the "vector_index" Atlas index  │
│     • Returns the top 4 matching documents   │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  2. FORMAT DOCUMENTS                         │
│     format_docs() joins the 4 documents      │
│     with "---" separators into a single      │
│     context string                           │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  3. PROMPT TEMPLATE                          │
│     ChatPromptTemplate injects:              │
│     • system: RAGnarok persona + {context}   │
│     • human: {question}                      │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  4. LLM (Gemini 3.5 Flash)                  │
│     temperature=0.2, streaming=True          │
│     Generates a response grounded in the     │
│     retrieved codebase context               │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  5. OUTPUT PARSER                            │
│     StrOutputParser() extracts the raw       │
│     string content from each AIMessageChunk  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
              Streamed tokens
```

### Step 5 — Server-Sent Events are Emitted

Each token produced by the chain is wrapped in SSE format and yielded:

```
data: {"text": "The"}

data: {"text": " authentication"}

data: {"text": " middleware"}

...

data: {"done": true}

```

Each event is a JSON object preceded by `data: ` and followed by two newline characters (`\n\n`), which is the standard SSE wire format.

### Step 6 — Frontend Parses the Stream

Back in `page.tsx`, the `response.body.getReader()` reads raw bytes from the HTTP stream:

1. **Decode** — `TextDecoder` converts `Uint8Array` chunks to strings.
2. **Buffer & Split** — The accumulated string is split on `\n\n` boundaries. The last fragment is retained in a buffer in case it's incomplete.
3. **Parse** — Each complete event has its `data: ` prefix stripped, then is `JSON.parse()`'d.
4. **Append** — If the parsed object contains a `text` field, it is concatenated to the assistant placeholder message's `content` via a state update.
5. **Terminate** — When `{"done": true}` is received, the stream loop exits.
6. **Finalize** — The placeholder message's `isStreaming` flag is set to `false`, removing the blinking cursor indicator.

### Step 7 — MongoDB's Role in Persistence

MongoDB Atlas serves two distinct functions in this architecture:

| Database | Collection | Purpose |
|----------|------------|---------|
| `rag_db` | `code_vectors` | Stores chunked code documents with their vector embeddings. Queried at runtime by the retriever via Atlas Vector Search. |
| `api-gateway` | `sessions` | Tracks ingestion job status (`processing`, `completed`, `failed`) and error logs. Updated by `worker.py` during repo ingestion. |

The `code_vectors` collection uses an Atlas Search index named `vector_index` with the following field mapping:

- `text` — The raw text content of each code chunk.
- `embedding` — The 768-dimensional vector generated by `gemini-embedding-001`.

---

## Environment Variables

Create a `.env` file in the `rag-engine/` directory using the provided template:

```env
REDIS_URL=redis://localhost:6379/0
MONGO_URI=mongodb+srv://<username>:<password>@ragnarok.qmlmqbg.mongodb.net/?appName=RAGnarok
GOOGLE_API_KEY=your_google_api_key_here
```

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | Yes | Connection string for the Redis instance used as Celery's message broker and result backend. |
| `MONGO_URI` | Yes | MongoDB Atlas connection URI. Must include credentials and the cluster address. |
| `GOOGLE_API_KEY` | Yes | API key for Google Generative AI (used by both the embedding model and Gemini LLM). |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- A MongoDB Atlas cluster with Vector Search enabled
- A Google Cloud API key with Generative AI access
- Redis (for Celery worker — optional if not running ingestion)

### Backend (FastAPI)

```bash
cd rag-engine
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # Fill in your credentials
uvicorn main:app --reload       # Starts on http://127.0.0.1:8000
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev                     # Starts on http://localhost:3000
```

### Celery Worker (Optional)

```bash
cd rag-engine
celery -A config.celery_app worker --loglevel=info
```

### Docker (Full Stack)

```bash
docker-compose up --build
```

> **Note:** The `docker-compose.yml` currently runs placeholder commands. Update the `command` fields to start the actual services for production use.

---

## Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Frontend Framework | Next.js | 16.2.9 |
| UI Library | React | 19.2.4 |
| CSS Framework | Tailwind CSS | 4.x |
| Typography | Geist (Sans + Mono) | via `next/font/google` |
| Backend Framework | FastAPI | ≥ 0.100.0 |
| ASGI Server | Uvicorn | ≥ 0.22.0 |
| LLM | Google Gemini 3.5 Flash | via `langchain-google-genai` |
| Embeddings | Google `gemini-embedding-001` | 768 dimensions |
| Vector Store | MongoDB Atlas Vector Search | via `langchain-mongodb` |
| RAG Orchestration | LangChain (LCEL) | ≥ 0.1.0 |
| Task Queue | Celery | ≥ 5.3.6 |
| Message Broker | Redis | ≥ 5.0.0 |
| Database Driver | PyMongo (sync) / Motor (async) | ≥ 4.6.0 / ≥ 3.4.0 |

---

<div align="center">

**RAGnarok** — *Codebase comprehension through retrieval-augmented generation.*

</div>
]]>
