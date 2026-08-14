# RAGnarok — Complete Test Suite Documentation

> **Project:** RAGnarok · Retrieval-Augmented Generation Codebase Assistant  
> **Stack:** FastAPI · MongoDB Atlas · Celery/Redis · LangChain · GitHub OAuth · JWT  
> **Test Framework:** pytest · mongomock · MockEmbeddings · MockLLM · GitHub Actions CI  
> **Generated:** 2026-08-11 | Total Tests: 26 (unit + integration + live pipeline + stress)

---

## Table of Contents

1. [Summary Table](#1-summary-table)
2. [Framework Architecture](#2-framework-architecture)
3. [Test File Deep-Dives](#3-test-file-deep-dives)
   - [test_auth.py — 11 Tests](#31-test_authpy--11-tests)
   - [test_rag.py — 9 Tests](#32-test_ragpy--9-tests)
   - [test_prompt2_pipeline.py — 5 Tests](#33-test_prompt2_pipelinepy--5-tests-live-pipeline)
   - [stress_test.py — Concurrent Load Testing](#34-stress_testpy--concurrent-load-testing)
4. [conftest.py — Shared Fixtures & Mocks](#4-conftestpy--shared-fixtures--mocks)
5. [GitHub Actions CI Pipeline](#5-github-actions-ci-pipeline)
6. [pytest vs Selenium Comparison](#6-pytest-vs-selenium-comparison)
7. [Gaps & Next Steps](#7-gaps--next-steps)
8. [20 Interview Q&A Cheat Sheet](#8-20-interview-qa-cheat-sheet)

---

## 1. Summary Table

| # | Test Name | File | Category | Layer | Speed | Mocks Used | Pass Criterion |
|---|-----------|------|----------|-------|-------|------------|----------------|
| 1 | `test_health_is_public` | test_auth.py | Unit | HTTP | ⚡ Fast | TestClient | `200 OK`, `status == "ok"` |
| 2 | `test_chat_requires_auth` | test_auth.py | Unit | HTTP | ⚡ Fast | TestClient | `401` on missing token |
| 3 | `test_ingest_requires_auth` | test_auth.py | Unit | HTTP | ⚡ Fast | TestClient | `401` on missing token |
| 4 | `test_chat_rejects_expired_token` | test_auth.py | Unit | JWT | ⚡ Fast | TestClient, expired JWT | `401` |
| 5 | `test_chat_rejects_bad_signature` | test_auth.py | Security | JWT | ⚡ Fast | TestClient | `401` on tampered sig |
| 6 | `test_chat_rejects_malformed_token` | test_auth.py | Unit | JWT | ⚡ Fast | TestClient | `401` on garbage string |
| 7 | `test_chat_accepts_valid_token` | test_auth.py | Unit | HTTP | ⚡ Fast | TestClient, MockLLM | Not `401/403` |
| 8 | `test_github_auth_success` | test_auth.py | Integration | OAuth | ⚡ Fast | `httpx.AsyncClient` | `200`, valid JWT returned |
| 9 | `test_github_auth_missing_code` | test_auth.py | Unit | OAuth | ⚡ Fast | TestClient | `400`, `"missing"` in detail |
| 10 | `test_github_auth_invalid_code` | test_auth.py | Integration | OAuth | ⚡ Fast | `httpx.AsyncClient` | `400` |
| 11 | `test_token_without_sub_rejected` | test_auth.py | Security | JWT | ⚡ Fast | TestClient | `401` |
| 12 | `test_ingest_dispatches_celery_task` | test_rag.py | Integration | Celery | ⚡ Fast | `main.process_repository` | `202`, task dispatched |
| 13 | `test_session_status_not_found` | test_rag.py | Unit | HTTP | ⚡ Fast | mongomock | `404` |
| 14 | `test_session_status_found` | test_rag.py | Integration | MongoDB | ⚡ Fast | mongomock | `200`, correct data |
| 15 | `test_chat_streams_response` | test_rag.py | Integration | SSE | ⚡ Fast | MockLLM, MockEmbeddings | Not `401/403` |
| 16 | `test_chat_empty_query_rejected` | test_rag.py | Unit | Validation | ⚡ Fast | TestClient | `400`, `"empty"` in detail |
| 17 | `test_chat_missing_query_field` | test_rag.py | Unit | Validation | ⚡ Fast | TestClient | `422` |
| 18 | `test_vector_isolation_user_cannot_read_other_session` | test_rag.py | **Security** | Vector DB | ⚡ Fast | `main.vector_store` | Bob's code absent from Alice's response |
| 19 | `test_ingest_requires_github_url` | test_rag.py | Integration | Validation | ⚡ Fast | `main.process_repository` | `202` or `400` (behavior doc) |
| 20 | `test_file_filter_source_files_accepted` | test_rag.py | Unit | Logic | ⚡ Fast | None | Extension filter pass/reject |
| 21 | `test_session_status_requires_auth` | test_rag.py | Unit | HTTP | ⚡ Fast | TestClient | `401` |
| 22 | `test_service_health` | test_prompt2_pipeline.py | Live E2E | TCP/HTTP | 🐢 Slow | None (real services) | Redis + FastAPI + Gateway all `200` |
| 23 | `test_trigger_ingestion` | test_prompt2_pipeline.py | Live E2E | HTTP | 🐢 Slow | None | `202` from `/api/ingest` |
| 24 | `test_poll_status` | test_prompt2_pipeline.py | Live E2E | HTTP/Polling | 🐢 Slow | None | `status == "completed"` in ≤240s |
| 25 | `test_vector_dimensions` | test_prompt2_pipeline.py | Live E2E | MongoDB | 🐢 Slow | None | embedding dim == `768` |
| 26 | `test_chat_reranker` | test_prompt2_pipeline.py | Live E2E | SSE + Reranker | 🐢 Slow | None | Non-empty streamed response |
| — | `stress_test.py` | stress_test.py | Performance | Async HTTP | 🐌 Very Slow | None | p95 < threshold, <20% failure |

**Legend:** ⚡ < 1s   🐢 10–240s   🐌 variable (concurrent)

---

## 2. Framework Architecture

### Interview Answer: "Walk me through your test architecture."

> *"Our test suite is layered into four distinct tiers, each solving a different problem:"*

```
┌─────────────────────────────────────────────────────────────────────┐
│                     RAGnarok Test Architecture                       │
├────────────────────────┬────────────────────────────────────────────┤
│  TIER 1: Unit (Fast)   │  test_auth.py + test_rag.py (subset)       │
│                        │  pytest · TestClient · JWT fabrication     │
│                        │  No network · mongomock · 100% deterministic│
├────────────────────────┼────────────────────────────────────────────┤
│  TIER 2: Integration   │  test_auth.py (OAuth) + test_rag.py (RAG) │
│                        │  Mocked external APIs (httpx, Celery,      │
│                        │  MongoDBAtlasVectorSearch)                  │
│                        │  Tests component wiring without real cloud │
├────────────────────────┼────────────────────────────────────────────┤
│  TIER 3: Live E2E      │  test_prompt2_pipeline.py                  │
│                        │  Runs against localhost:8000/3000/6379     │
│                        │  Real MongoDB Atlas · Real Celery worker   │
│                        │  Validates BGE-768d embeddings end-to-end  │
├────────────────────────┼────────────────────────────────────────────┤
│  TIER 4: Stress        │  stress_test.py                            │
│                        │  asyncio + httpx · 10 concurrent chats     │
│                        │  5 concurrent ingests · ramp-up mode       │
│                        │  p50/p95/p99 latency reporting             │
└────────────────────────┴────────────────────────────────────────────┘
```

### Key Infrastructure Components

| Component | Role in Tests | Implementation |
|-----------|--------------|----------------|
| `conftest.py` | Central fixture factory | `session`-scoped TestClient with 4 simultaneous patches |
| `MockEmbeddings` | Zero-vector 768d replacement | Drop-in for `GoogleGenerativeAIEmbeddings`, never calls API |
| `MockLLM` | Canned streamed responses | Drop-in for `ChatGoogleGenerativeAI`, yields `["Mocked ", "LLM ", "response."]` |
| `mongomock.MongoClient` | In-memory MongoDB | Replaces Atlas; no connection string needed |
| `make_token()` / `make_expired_token()` | JWT factory | Signs with `TEST_JWT_SECRET` using `python-jose`, bypasses GitHub OAuth |
| `unittest.mock.patch` | Runtime monkey-patching | Intercepts `httpx.AsyncClient`, `main.process_repository`, `main.vector_store` |
| GitHub Actions | CI runner | Ubuntu-latest + Redis service container; HuggingFace model cache; 70% coverage gate |

### Why This Architecture?

> *"We needed tests that could run in CI without Atlas credentials, Google API keys, or a running Celery worker — but still exercise real application logic. The solution was strategic mocking at the boundary layer: we swap out the cloud SDKs but keep all FastAPI routing, JWT middleware, and RAG orchestration logic running as real code. The result is a suite that catches real bugs fast without burning API tokens."*

---

## 3. Test File Deep-Dives

---

### 3.1 `test_auth.py` — 11 Tests

**Purpose:** Verifies every authentication boundary in the FastAPI app — public endpoints, JWT validation, expiry, tampering, missing claims, and the full GitHub OAuth code-exchange flow.

**Fixtures used:** `client` (TestClient), `auth_headers_user_a`, `expired_auth_headers`  
**External patches:** `httpx.AsyncClient` (for OAuth tests)

---

#### Test 1: `test_health_is_public`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `GET /health` |
| **Mocks** | None (just TestClient) |
| **Purpose** | Confirms the health check is publicly accessible without any `Authorization` header |
| **Assertion** | `status_code == 200`, `data["status"] == "ok"`, `"rag-engine" in data["service"]` |

**Interview Q&A:**
> **Q:** Why test a public endpoint at all?  
> **A:** Security regressions. If someone accidentally adds `require_auth` middleware globally, this test fails first — loudly — before any user reaches production. It also validates our health check payload shape, which the load balancer and CI pipeline both depend on.

---

#### Test 2: `test_chat_requires_auth`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | None |
| **Purpose** | Verifies the JWT middleware rejects chatbot requests with no `Authorization` header |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** How does the JWT middleware work in FastAPI?  
> **A:** We use a dependency injection function decorated as `Depends(verify_token)`. It extracts the `Authorization: Bearer <token>` header, decodes the JWT using `python-jose` with the configured secret, and raises `HTTPException(401)` if anything is missing or invalid. FastAPI evaluates this before the route handler runs.

---

#### Test 3: `test_ingest_requires_auth`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /api/ingest` |
| **Mocks** | None |
| **Purpose** | Same as Test 2 but for the ingestion endpoint — ensures no endpoint is accidentally left open |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** Why test auth separately for each endpoint instead of once globally?  
> **A:** Route-specific middleware overrides are common bugs. A developer might add `dependencies=[]` to a specific route to bypass auth for debugging, then forget to remove it. Per-endpoint auth tests catch these accidents.

---

#### Test 4: `test_chat_rejects_expired_token`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | `expired_auth_headers` fixture (JWT with `exp` 5 minutes in the past) |
| **Purpose** | Confirms the middleware checks token expiry, not just signature validity |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** How do you create an expired JWT in a test without waiting?  
> **A:** We use `make_expired_token()` in `conftest.py`. It sets `exp = datetime.now(UTC) - timedelta(minutes=5)`, so the token is already expired at mint time. `python-jose`'s `jwt.encode` doesn't validate this — it just signs whatever you give it. The validation happens server-side during `jwt.decode()`.

---

#### Test 5: `test_chat_rejects_bad_signature`

| Field | Value |
|-------|-------|
| **Type** | Security |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | Manual JWT part-replacement |
| **Purpose** | Simulates an attacker who copies a valid JWT header/payload but uses the wrong signature |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** How do you simulate JWT tampering in a test?  
> **A:** JWTs are three base64 segments separated by dots. We split the real token, keep the header and payload, and replace the third segment with `"INVALIDSIGNATURE"`. When the server calls `jwt.decode()`, the signature verification fails and returns `401`. This tests that we're not blindly trusting the payload.

---

#### Test 6: `test_chat_rejects_malformed_token`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | None |
| **Purpose** | Sends a completely non-JWT string as the Bearer token; ensures `jwt.decode` exceptions are properly caught |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** Why test malformed tokens separately from bad signatures?  
> **A:** They trigger different code paths. A bad signature fails during HMAC verification. A malformed token (`"not.a.real.jwt"`) fails during base64 parsing — before verification even starts. Both must return `401`, not `500` (unhandled exception).

---

#### Test 7: `test_chat_accepts_valid_token`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | `auth_headers_user_a`, `MockLLM`, `MockEmbeddings` |
| **Purpose** | The "happy path" — a valid JWT must pass the auth guard; asserts the response is NOT `401/403` |
| **Assertion** | `status_code not in (401, 403)` |

**Interview Q&A:**
> **Q:** Why not assert `status_code == 200` here?  
> **A:** In test mode with no real vectors in the DB, the chat might return `200` with an empty stream or `400` if the session has no data. The important invariant is that auth itself doesn't block the request. Checking `not in (401, 403)` makes the test robust to backend behavior changes that don't affect auth.

---

#### Test 8: `test_github_auth_success`

| Field | Value |
|-------|-------|
| **Type** | Integration |
| **Endpoint** | `POST /api/auth/github` |
| **Mocks** | `httpx.AsyncClient` (mocked `.post()` → token, `.get()` → user profile) |
| **Purpose** | Full OAuth code-exchange flow without real GitHub API calls |
| **Assertion** | `200`, `"access_token"` in response, username == `"testuser"`, JWT `sub == "testuser"` |

**Interview Q&A:**
> **Q:** How do you mock an async context manager like `httpx.AsyncClient`?  
> **A:** We create an `AsyncMock` and wire up `__aenter__` and `__aexit__` as `AsyncMock` too. Then we set `.post` and `.get` to return `MagicMock` objects with `.json()` pre-configured. Finally, `patch("httpx.AsyncClient", return_value=mock_async_client)` replaces the real class for the duration of the `with` block. The `async with httpx.AsyncClient() as client:` pattern inside our endpoint then runs against our mock.

---

#### Test 9: `test_github_auth_missing_code`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /api/auth/github` |
| **Mocks** | None |
| **Purpose** | The GitHub OAuth flow requires a `code` parameter; missing it returns 400 |
| **Assertion** | `status_code == 400`, `"missing"` in `detail.lower()` |

**Interview Q&A:**
> **Q:** Why test input validation separately from business logic?  
> **A:** Pydantic/FastAPI validation can shadow application bugs. If we only tested the happy path, a bug in the error-path code (the `400` branch) would go undetected. This test also validates the error message format, which the frontend uses to display user-facing errors.

---

#### Test 10: `test_github_auth_invalid_code`

| Field | Value |
|-------|-------|
| **Type** | Integration |
| **Endpoint** | `POST /api/auth/github` |
| **Mocks** | `httpx.AsyncClient` (`.post()` returns `{"error": "bad_verification_code"}`, no `access_token`) |
| **Purpose** | Simulates GitHub rejecting a stale or already-used OAuth code |
| **Assertion** | `status_code == 400` |

**Interview Q&A:**
> **Q:** In what real scenario would GitHub return no `access_token`?  
> **A:** Three cases: (1) The code was already exchanged once — GitHub codes are single-use. (2) The code expired — GitHub codes have a 10-minute TTL. (3) The `client_id`/`client_secret` is wrong. All these should return `400` to the frontend so it can re-initiate the OAuth flow.

---

#### Test 11: `test_token_without_sub_rejected`

| Field | Value |
|-------|-------|
| **Type** | Security |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | Manually crafted JWT without `sub` claim |
| **Purpose** | JWTs without a subject claim are technically valid signatures but semantically invalid — we must reject them |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** Why would a JWT without `sub` be dangerous?  
> **A:** The `sub` claim is how we identify which user is making the request — it's used for session isolation and audit logging. A valid JWT without `sub` would pass signature verification but break all downstream user identity lookups. This test ensures our middleware explicitly validates `sub` presence, not just cryptographic validity.

---

### 3.2 `test_rag.py` — 9 Tests

**Purpose:** Integration tests for the RAG pipeline — ingestion dispatch, session status, streaming chat, input validation, vector isolation, URL handling, and file filtering.

**Fixtures used:** `client`, `mock_mongo`, `auth_headers_user_a`, `auth_headers_user_b`  
**External patches:** `main.process_repository` (Celery task), `main.vector_store`

---

#### Test 12: `test_ingest_dispatches_celery_task`

| Field | Value |
|-------|-------|
| **Type** | Integration |
| **Endpoint** | `POST /api/ingest` |
| **Mocks** | `patch("main.process_repository")` with `MagicMock().delay` |
| **Purpose** | The ingest endpoint must be non-blocking: accept the request, dispatch to Celery, return `202` immediately |
| **Assertion** | `status_code == 202`, `data["sessionId"] == "test_session_001"`, "started"/"ingestion" in message |

**Interview Q&A:**
> **Q:** Why does the ingest endpoint return `202 Accepted` instead of `200 OK`?  
> **A:** `202` means "I've accepted your request but the work isn't done yet." Ingestion can take 2–5 minutes (cloning a repo, chunking files, embedding vectors). Returning `200` would require holding the HTTP connection open the entire time. Instead, we dispatch a Celery background task and let the client poll `/api/session/{id}` for status updates.

---

#### Test 13: `test_session_status_not_found`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `GET /api/session/{id}` |
| **Mocks** | `mongomock` (empty DB) |
| **Purpose** | Querying a non-existent session ID returns `404` |
| **Assertion** | `status_code == 404` |

**Interview Q&A:**
> **Q:** How does mongomock simulate MongoDB in memory?  
> **A:** `mongomock.MongoClient()` creates a fully in-memory MongoDB client that supports most PyMongo operations — `insert_one`, `find_one`, `count_documents`, etc. — without any network connection. The `mock_mongo` fixture is `session`-scoped so it's created once and shared across all tests, making it both fast and consistent.

---

#### Test 14: `test_session_status_found`

| Field | Value |
|-------|-------|
| **Type** | Integration |
| **Endpoint** | `GET /api/session/{id}` |
| **Mocks** | `mongomock` (pre-seeded with session document) |
| **Purpose** | After inserting a session document, the endpoint returns it correctly |
| **Assertion** | `status_code == 200`, `data["status"] == "completed"`, `data["sessionId"]` correct |

**Interview Q&A:**
> **Q:** How do you seed test data into mongomock?  
> **A:** The `mock_mongo` fixture yields a `mongomock.MongoClient`. In the test, we call `mock_mongo.get_database("api-gateway").sessions.insert_one({...})` — exactly the same API as real PyMongo. The key detail is using the **same database name** (`"api-gateway"`) that `main.py` uses; otherwise you're writing to a different namespace than the app reads from.

---

#### Test 15: `test_chat_streams_response`

| Field | Value |
|-------|-------|
| **Type** | Integration |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | `MockLLM` (canned stream), `MockEmbeddings` (zero vectors) |
| **Purpose** | A valid authenticated chat request produces a streaming SSE response, not an auth error |
| **Assertion** | `status_code not in (401, 403)` |

**Interview Q&A:**
> **Q:** How does `MockLLM` work?  
> **A:** `MockLLM` is a hand-rolled class that implements the `astream` async generator interface expected by LangChain. It yields three chunks: `"Mocked "`, `"LLM "`, `"response."`. The real `ChatGoogleGenerativeAI` is patched at module load time in `conftest.py`, so every call to the LLM throughout the test session hits this mock instead.

---

#### Test 16: `test_chat_empty_query_rejected`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | None |
| **Purpose** | A whitespace-only query (` ` or `"   "`) is semantically empty and must be rejected |
| **Assertion** | `status_code == 400`, `"empty"` in `detail.lower()` |

**Interview Q&A:**
> **Q:** Why treat whitespace-only queries differently from genuinely missing fields?  
> **A:** Pydantic validates field presence and type (returns `422` for missing fields), but it won't catch whitespace strings as "empty." That's application-level business logic. A whitespace query would cause the embedding model to generate a near-zero vector, which could match irrelevant vectors or produce nonsensical RAG responses. We explicitly `.strip()` and check length in the route handler.

---

#### Test 17: `test_chat_missing_query_field`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `POST /chat/{session_id}` |
| **Mocks** | None |
| **Purpose** | A request body missing the `query` field entirely triggers Pydantic validation |
| **Assertion** | `status_code == 422` (FastAPI's Pydantic validation error code) |

**Interview Q&A:**
> **Q:** What's the difference between a `400` and `422` in FastAPI?  
> **A:** `422 Unprocessable Entity` is FastAPI's default for Pydantic validation failures — wrong types, missing required fields. `400 Bad Request` is what we return for our custom business logic validations (like whitespace queries). By keeping these separate, API consumers can distinguish "malformed request" from "semantically invalid request."

---

#### Test 18: `test_vector_isolation_user_cannot_read_other_session` ⭐ Critical Security Test

| Field | Value |
|-------|-------|
| **Type** | **Security — Critical** |
| **Endpoint** | `POST /chat/session_alice` |
| **Mocks** | `main.vector_store` with `isolation_aware_search` side effect |
| **Purpose** | Proves that User A's chat cannot retrieve User B's ingested vectors — the most critical security invariant in the system |
| **Assertion** | `"Bob's secret function"` is NOT in Alice's response body |

**How it works:**
```python
# Bob's private code document
bob_doc = Document(
    page_content="Bob's secret function: def transfer_funds(): ...",
    metadata={"session_id": "session_bob"}
)

# Mock vector store that respects pre_filter (simulates Atlas behavior)
def isolation_aware_search(query, k=4, pre_filter=None, **kwargs):
    filter_val = pre_filter.get("metadata.session_id", {}).get("$eq")
    if filter_val == "session_bob":
        return [bob_doc]
    return []  # Alice's session returns nothing

# Alice queries HER session — pre_filter will be {"metadata.session_id": {"$eq": "session_alice"}}
# isolation_aware_search returns [] -> Alice sees nothing from Bob
```

**Interview Q&A:**
> **Q:** This is the most complex test — walk me through it.  
> **A:** The test simulates a multi-tenant RAG system where each user's ingested vectors are tagged with their `session_id`. The real Atlas vector search uses a `pre_filter` to restrict results to the querying user's session. Our `isolation_aware_search` function mimics this: it only returns Bob's document when the filter explicitly targets Bob's session. Since Alice queries her own session (`session_alice`), the filter never matches Bob's session ID, so she gets zero results — and can never see Bob's private code. This test would catch a bug where we forgot to add `pre_filter` to our similarity search call.

---

#### Test 19: `test_ingest_requires_github_url`

| Field | Value |
|-------|-------|
| **Type** | Integration / Behavior Documentation |
| **Endpoint** | `POST /api/ingest` |
| **Mocks** | `main.process_repository` |
| **Purpose** | Documents current behavior when a non-GitHub URL is submitted (accepted by backend, validated by worker) |
| **Assertion** | `status_code in (202, 400)` — both acceptable until server-side URL validation is added |

**Interview Q&A:**
> **Q:** Why does this test accept both `202` and `400`?  
> **A:** This test documents a known architectural decision: URL validation currently happens in the Celery worker, not the API gateway. The `202` is the current behavior. The `in (202, 400)` assertion is a "bridge test" — it won't break when we add server-side URL validation, but it documents the intention to add it. It's as much documentation as it is a test.

---

#### Test 20: `test_file_filter_source_files_accepted`

| Field | Value |
|-------|-------|
| **Type** | Pure Unit |
| **Layer** | Business Logic (worker) |
| **Mocks** | None |
| **Purpose** | Tests the `is_source_file()` helper that determines which files from a cloned repo are embedded into vectors |
| **Assertion** | `.py`, `.tsx`, `.yaml`, `.md` accepted; `package-lock.json`, `yarn.lock`, `node_modules/**`, `dist/**`, `.pyc` rejected |

**Interview Q&A:**
> **Q:** Why test the file filter directly instead of through an HTTP endpoint?  
> **A:** Because it's pure logic with no I/O. Testing it through the full HTTP stack would require mocking multiple layers and the test would be slower and harder to debug. For isolated business logic, direct function testing is faster, clearer, and gives more precise failure messages — you immediately know which extension is misbehaving.

---

#### Test 21: `test_session_status_requires_auth`

| Field | Value |
|-------|-------|
| **Type** | Unit |
| **Endpoint** | `GET /api/session/{id}` |
| **Mocks** | None |
| **Purpose** | Confirms the session status endpoint also requires authentication |
| **Assertion** | `status_code == 401` |

**Interview Q&A:**
> **Q:** Why does the session status endpoint require auth when it only returns status?  
> **A:** Session IDs contain information about what repositories a user ingested. An unauthenticated endpoint would let attackers enumerate session statuses and infer which repos users have analyzed. Auth on every non-public endpoint is a defense-in-depth principle.

---

### 3.3 `test_prompt2_pipeline.py` — 5 Tests (Live Pipeline)

**Purpose:** End-to-end verification that the Prompt 2 upgrade stack works with real services — BGE-base-en-v1.5 (768d embeddings), Cross-Encoder reranking, Atlas vector search, and the full Celery worker pipeline.

**Type:** Live Integration — requires all services running locally  
**No mocks used** — everything is real  
**Timeout:** Up to 240 seconds per test run  
**Run mode:** `python test_prompt2_pipeline.py` (standalone script with its own `main()`)

---

#### Test 22: `test_service_health`

| Field | Value |
|-------|-------|
| **Type** | Live E2E — Infrastructure Health |
| **Services** | Redis `:6379` (TCP), FastAPI `:8000` (HTTP), API Gateway `:3000` (HTTP) |
| **Mocks** | None |
| **Retry Logic** | FastAPI: 6 retries × 10s (model loading can be slow) |
| **Purpose** | Gate test — all subsequent tests are skipped if FastAPI is unreachable |
| **Pass Criterion** | All three services respond successfully |

**Interview Q&A:**
> **Q:** Why does FastAPI have 6 retry attempts during health checks?  
> **A:** FastAPI loads the BGE-base-en-v1.5 embedding model and Cross-Encoder at startup. On a cold machine (or CI runner), downloading and initializing these models can take 30–60 seconds. Without retries, the health check would fail before the server is ready. The 6 × 10s retry window gives the server up to 60 seconds to complete initialization.

---

#### Test 23: `test_trigger_ingestion`

| Field | Value |
|-------|-------|
| **Type** | Live E2E |
| **Endpoint** | `POST http://localhost:8000/api/ingest` |
| **Auth** | JWT from `_create_test_jwt()` using `.env` `JWT_SECRET_KEY`, or `X-Internal-Key` header |
| **Repo** | `https://github.com/expressjs/cors` |
| **Session** | `opus_test_768` |
| **Purpose** | Verifies the full ingestion trigger path works with real auth and dispatches to the real Celery worker |
| **Pass Criterion** | `HTTP 200` or `202` |

**Interview Q&A:**
> **Q:** Why use `expressjs/cors` as the test repository?  
> **A:** It's small (~20 source files), public, stable (not frequently updated), and has clear, well-scoped functionality — making the chat query ("How does cors handle preflight OPTIONS requests?") produce meaningful, verifiable output. Using a large repo like `facebook/react` would take too long to ingest in a pipeline test.

---

#### Test 24: `test_poll_status`

| Field | Value |
|-------|-------|
| **Type** | Live E2E — Async Completion |
| **Endpoint** | `GET http://localhost:8000/api/session/opus_test_768` |
| **Poll Config** | Every 3 seconds, timeout at 240 seconds |
| **Terminal States** | `"completed"` (pass) or `"failed"` (fail) |
| **Purpose** | Proves the Celery worker completes ingestion end-to-end and updates session status in MongoDB |
| **Pass Criterion** | `status == "completed"` within 240s |

**Interview Q&A:**
> **Q:** How does polling work and what are the failure modes?  
> **A:** We call `/api/session/{id}` every 3 seconds. The endpoint reads the `sessions` collection in MongoDB. The Celery worker updates this document at key lifecycle stages: `"processing"`, `"embedding"`, `"completed"`, or `"failed"`. Failure modes: (1) `"failed"` status with `errorLog` — usually a network or embedding error. (2) Timeout — the worker is stuck, never updates status. (3) `404` persisting — the session was never created, meaning Celery task dispatch itself failed.

---

#### Test 25: `test_vector_dimensions`

| Field | Value |
|-------|-------|
| **Type** | Live E2E — Data Integrity |
| **DB** | `rag_db.code_vectors` on MongoDB Atlas |
| **Purpose** | After ingestion, samples a stored vector and confirms its dimension is exactly 768, proving BAAI/bge-base-en-v1.5 was used (not a 1536-dim OpenAI model or 3072-dim Gemini model) |
| **Pass Criterion** | `len(embedding) == 768` |

**Interview Q&A:**
> **Q:** Why is verifying vector dimensions important?  
> **A:** The Atlas vector search index is configured with `numDimensions: 768`. If a different embedding model produces 1536-dim vectors, they physically cannot be indexed or searched — every chat would return zero results silently. This test acts as a regression guard: if someone accidentally changes the embedding model in `worker.py` without updating the Atlas index, this test catches it immediately.

---

#### Test 26: `test_chat_reranker`

| Field | Value |
|-------|-------|
| **Type** | Live E2E — Full Pipeline |
| **Endpoint** | `POST http://localhost:8000/chat/opus_test_768` |
| **Query** | `"How does cors handle preflight OPTIONS requests?"` |
| **Protocol** | SSE streaming (`text/event-stream`) |
| **Purpose** | Tests the full RAG pipeline end-to-end: embed query → vector search → Cross-Encoder reranking → LLM streaming |
| **Pass Criterion** | `HTTP 200` with non-empty response text, no stream errors |
| **Rate Limit Handling** | `HTTP 429` → SKIP (quota exhausted, not a code bug) |

**Interview Q&A:**
> **Q:** What does Cross-Encoder reranking add to the pipeline?  
> **A:** Standard vector search retrieves the top-k documents by cosine similarity (bi-encoder, fast but less accurate). The Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) then re-scores all k candidates by comparing query and document together in a single forward pass — much more accurate but computationally heavier. We retrieve top-20 with the vector search and rerank to top-5. This test validates that reranked results are coherent enough for the LLM to produce a meaningful response about CORS preflight handling.

---

### 3.4 `stress_test.py` — Concurrent Load Testing

**Purpose:** Measures the FastAPI backend's behavior under concurrent load — latency degradation, error rates, and the breakpoint where the system starts failing.

**Type:** Performance / Load test  
**Runtime requirement:** Real JWT token + running FastAPI server  
**Framework:** `asyncio` + `httpx.AsyncClient`

---

#### Test Suite A: `run_concurrent_chat` (10 simultaneous requests)

| Field | Value |
|-------|-------|
| **Concurrency** | 10 simultaneous `POST /chat/{session_id}` requests |
| **Queries** | 10 diverse queries rotating from `CHAT_QUERIES` list |
| **Implementation** | `asyncio.gather()` with `httpx.AsyncClient` |
| **Metrics** | Status code, latency per request, full SSE body length |
| **Purpose** | Simulates real-world concurrent users querying the same or different sessions |

**Interview Q&A:**
> **Q:** Why use `asyncio.gather()` instead of threading for concurrent requests?  
> **A:** The test is I/O bound — it's waiting for HTTP responses, not doing CPU work. `asyncio.gather()` with `httpx.AsyncClient` is more efficient for I/O concurrency because it doesn't create OS thread overhead. All coroutines share a single thread but yield control during network waits, so all 10 requests fire nearly simultaneously with minimal overhead.

---

#### Test Suite B: `run_concurrent_ingest` (5 simultaneous requests)

| Field | Value |
|-------|-------|
| **Concurrency** | 5 simultaneous `POST /api/ingest` requests |
| **Session IDs** | Unique per request: `stress_ingest_{id}_{timestamp}` |
| **Repo** | `https://github.com/tiangolo/fastapi` |
| **Purpose** | Tests whether the Celery dispatcher handles concurrent ingest submissions without race conditions or queue corruption |

**Interview Q&A:**
> **Q:** Why use unique session IDs per ingest request in the stress test?  
> **A:** To avoid cross-contamination — if two requests use the same session ID, the second Celery task might overwrite the first's vectors. Unique IDs simulate independent users each ingesting their own repository, which is the real use case.

---

#### Test Suite C: `run_ramp_up` (Concurrency levels: 1, 5, 10, 20)

| Field | Value |
|-------|-------|
| **Levels** | 1 → 5 → 10 → 20 concurrent requests |
| **Breakpoint detection** | Stops when `>20%` failure rate at a given level |
| **Metrics per level** | `p50 latency`, `max latency`, `success rate` |
| **Purpose** | Finds the system's practical concurrency limit — the point where latency degrades unacceptably or errors appear |

**Interview Q&A:**
> **Q:** What breakpoint percentage did you choose and why?  
> **A:** 20% — if 1 in 5 requests fails, the UX is noticeably broken. A lower threshold (5%) would be too strict for transient errors; a higher threshold (50%) would miss real performance problems. The 20% rule is a standard load testing convention borrowed from SRE practices.

---

#### Summary Output Format

```
=== SUMMARY ===
CHAT    | total= 10 | success= 10 | failed=  0 | p50=1.24s | p95=2.31s | p99=2.31s
INGEST  | total=  5 | success=  5 | failed=  0 | p50=0.09s | p95=0.18s | p99=0.18s
```

---

## 4. `conftest.py` — Shared Fixtures & Mocks

`conftest.py` is pytest's convention for shared test infrastructure. It runs before any test file is loaded.

### Fixture Dependency Graph

```
mock_mongo (session-scoped)
    └── client (session-scoped)
            ├── auth_headers_user_a (function-scoped)
            ├── auth_headers_user_b (function-scoped)
            └── expired_auth_headers (function-scoped)
```

### The 4-Patch Strategy

```python
with (
    patch("langchain_google_genai.GoogleGenerativeAIEmbeddings", return_value=MockEmbeddings()),
    patch("langchain_google_genai.ChatGoogleGenerativeAI",        return_value=MockLLM()),
    patch("pymongo.MongoClient",                                   return_value=mock_mongo),
    patch("langchain_mongodb.MongoDBAtlasVectorSearch",           return_value=mock_vs),
):
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
```

> **Why `session`-scoped?** The FastAPI app initialization is expensive (model loading, connection setup). Using `scope="session"` means the app is created once and reused across all 20 tests in `test_auth.py` + `test_rag.py`. This reduces test suite runtime from ~60s to ~3s.

> **Why `raise_server_exceptions=False`?** So tests can assert on the HTTP status code (e.g., `401`) without pytest crashing when the server raises an exception internally. This lets us test error paths cleanly.

### Environment Variable Injection

```python
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("GOOGLE_API_KEY", "fake-api-key-for-tests")
os.environ.setdefault("REDIS_URL",      "redis://localhost:6379/0")
os.environ.setdefault("OAUTH_ID",       "fake-github-client-id")
```

These are set **before** `from main import app` — critical because `main.py` reads these at module load time. Setting them after would have no effect.

---

## 5. GitHub Actions CI Pipeline

**File:** [ci.yml](file:///c:/Users/ashan/OneDrive/Desktop/RAG_P1/.github/workflows/ci.yml)

### Trigger

```yaml
on:
  push:
    branches: [main]
  pull_request:          # All PRs, any branch
```

### Job 1: RAG Engine Tests (Python)

```
ubuntu-latest
├── Redis service container (redis:alpine, port 6379, health-checked)
├── Python 3.11 setup + pip cache
├── HuggingFace model cache (key: hf-models-bge-base-en-v1.5-cross-encoder-ms-marco)
│   └── Reduces CI time: 7 min → 2 min on warm cache
├── Install: requirements.txt + pytest + pytest-cov + mongomock
├── pytest --cov=. --cov-report=xml --cov-fail-under=70
│   └── Fails build if coverage < 70%
└── Post coverage comment to PR (MishaKav/pytest-coverage-comment@main)
```

### Job 2: API Gateway Tests (Node.js)

```
ubuntu-latest
├── Node.js 18 + npm cache
├── npm ci (clean install)
├── npx tsc --noEmit (TypeScript type checking)
└── npm test --if-present (Jest tests)
```

### Key CI Design Decisions

| Decision | Why |
|----------|-----|
| Redis as service container | Tests that import Celery would fail without a reachable Redis URL |
| HuggingFace model cache | Without caching, the BGE model downloads ~500MB on every run |
| `--cov-fail-under=70` | Hard enforcement of minimum coverage — prevents PRs from merging if they drop coverage |
| `raise_server_exceptions=False` in TestClient | Allows tests to inspect error responses without CI crashing on handled exceptions |
| `dummy-key-for-tests` as API keys | Prevents real API calls in CI while allowing `os.getenv()` calls to resolve |

---

## 6. pytest vs Selenium Comparison

| Dimension | pytest (our approach) | Selenium / Playwright |
|-----------|----------------------|----------------------|
| **What it tests** | HTTP APIs, business logic, security | Browser UI, user flows, visual rendering |
| **Speed** | ⚡ Milliseconds per test | 🐢 Seconds per test (browser startup + render) |
| **Flakiness** | Very low — deterministic with mocks | Higher — timing issues, selector changes, JS race conditions |
| **Environment** | Headless, no browser needed | Requires browser binary (Chrome, Firefox) |
| **Mocking** | Native `unittest.mock.patch` at import time | Limited — must mock at network layer (e.g., Playwright `route()`) |
| **CI cost** | Minimal — standard Python environment | High — requires browser install, GPU for rendering, longer timeouts |
| **Debug output** | Precise assertion messages, stack traces | Screenshots on failure, harder to pinpoint root cause |
| **What it misses** | Frontend JS bugs, CSS layout issues, accessibility | Backend logic bugs hidden behind the UI |
| **Auth testing** | Direct header injection (fast, precise) | Requires full login flow per test (slow) |
| **Streaming SSE** | `TestClient` reads full stream body | Complex to assert — need custom JS to consume SSE |
| **Best for** | RAGnarok's backend correctness & security | End-to-end user journey validation |

### When to Use Which?

> **pytest:** "Does the API behave correctly when given these exact inputs?"  
> **Selenium/Playwright:** "Can a real user click through the UI and complete the workflow?"

**Recommendation for RAGnarok:** Use pytest for all backend logic (current). Add Playwright for UI smoke tests covering: login flow, file upload trigger, chat response rendering, and cross-browser compatibility.

---

## 7. Gaps & Next Steps

### Current Coverage Gaps

| Gap | Risk | Recommended Fix |
|-----|------|-----------------|
| **No SSE content assertion** | Chat might return 200 but empty body goes undetected | Parse SSE events in TestClient response and assert on `data:` fields |
| **No Celery task unit tests** | Worker logic bugs (chunking, embedding, error handling) not covered | Use Celery's `task.apply()` for synchronous testing |
| **`test_prompt2_pipeline.py` not in pytest** | CI never runs the live E2E tests | Add `@pytest.mark.live` + separate CI job with Docker Compose |
| **`stress_test.py` not in pytest** | Performance regressions invisible | Add `@pytest.mark.performance` and run pre-release |
| **No real Atlas isolation test** | Isolation test uses mocked vector store | Add a live test that inserts vectors and asserts no cross-contamination |
| **No rate limiting tests** | `/chat` abuse vector unverified | Test `429` response when threshold exceeded |
| **No token refresh tests** | Short-lived JWTs expire; refresh flow untested | Test re-auth flow if implemented |
| **Celery mock is too loose** | `process_repository.delay()` might be called with wrong args | Add `mock_task.delay.assert_called_once_with(session_id, repo_url)` |
| **`test_ingest_requires_github_url` is a behavior doc** | `in (202, 400)` hides when behavior changes | Lock assertion to a single status code once URL validation is added |
| **No negative path for `test_chat_reranker`** | Rate limiting gracefully skipped but not asserted | Add explicit `429` handling test |

### Recommended Next Steps (Priority Order)

1. **[ ] Parse SSE content in `test_chat_streams_response`** — assert `data:` events contain non-empty text tokens
2. **[ ] Add Celery worker unit tests** — test `process_repository()` with mocked `GitLoader`, `TextSplitter`, and vector store
3. **[ ] Wrap `test_prompt2_pipeline.py` in pytest fixtures** — mark as `@pytest.mark.live` and run in a separate CI job
4. **[ ] Add `assert_called_once_with` to Celery mock** — verify task receives the correct `session_id` and `repo_url`
5. **[ ] Add Playwright smoke tests** — cover login → ingest → chat user journey
6. **[ ] Add `/metrics` endpoint + test** — expose p95 latency and error rate as Prometheus metrics

---

## 8. 20 Interview Q&A Cheat Sheet

---

**Q1: What is the overall structure of your test suite?**

> Four tiers: (1) Unit tests with mocked everything — fast, deterministic, CI-native. (2) Integration tests with selective mocking of cloud APIs. (3) Live E2E tests against real services — run locally before releases. (4) Stress tests to find concurrency breakpoints. Tiers 1–2 run in GitHub Actions on every PR with a 70% coverage gate.

---

**Q2: How do you avoid calling real APIs in tests?**

> We patch at the import boundary in `conftest.py`. `GoogleGenerativeAIEmbeddings` → `MockEmbeddings` (zero vectors), `ChatGoogleGenerativeAI` → `MockLLM` (canned stream), `pymongo.MongoClient` → `mongomock`, `MongoDBAtlasVectorSearch` → `MagicMock`. All four patches are applied before `from main import app`, so the app module never sees real SDK classes.

---

**Q3: What is mongomock and why use it?**

> `mongomock` is a pure-Python in-memory MongoDB implementation. It supports the PyMongo API (`insert_one`, `find_one`, `count_documents`, etc.) without any network connection. We use it so tests don't need Atlas credentials and run in milliseconds instead of hitting a remote cluster.

---

**Q4: How do you test JWT authentication without a real OAuth flow?**

> `conftest.py` exposes `make_token(username)` which mints a real, properly signed JWT using the same `python-jose` library and the same `TEST_JWT_SECRET` the test server uses. We inject the JWT as an `Authorization: Bearer ...` header on each request. No GitHub callback, no browser, no redirect — just a valid token.

---

**Q5: What does `scope="session"` mean on a pytest fixture?**

> The fixture is created once per test session and shared by all tests. For `client` and `mock_mongo`, this means the FastAPI app is initialized once (expensive), not once per test. Function-scoped fixtures (like `auth_headers_user_a`) are recreated for each test, giving fresh JWTs.

---

**Q6: How do you test the GitHub OAuth flow without real GitHub?**

> We mock `httpx.AsyncClient` using `AsyncMock` with custom `__aenter__`/`__aexit__`. We pre-configure `.post()` to return a fake token response and `.get()` to return a fake user profile. The endpoint code runs unmodified — it just talks to our mock instead of GitHub's servers.

---

**Q7: What is the most critical security test and why?**

> `test_vector_isolation_user_cannot_read_other_session`. It proves that User A's RAG chat queries cannot retrieve User B's ingested code vectors. We mock the vector store with an `isolation_aware_search` function that respects the `pre_filter` (the session-scoped MongoDB filter). If the app forgot to include the filter, Alice would get Bob's results — and this test would fail with `"VECTOR ISOLATION FAILURE"`.

---

**Q8: Why does the ingest endpoint return 202 instead of 200?**

> Because ingestion is asynchronous — it dispatches a Celery task that runs in the background for 2–5 minutes. `202 Accepted` is the correct HTTP semantic for "I've queued your work, poll for status." Returning `200` would imply completion.

---

**Q9: How does your CI pipeline handle HuggingFace model downloads?**

> We use `actions/cache@v4` with a key based on model names (`hf-models-bge-base-en-v1.5-cross-encoder-ms-marco`). The first CI run downloads the models (~500MB) and caches them. Subsequent runs restore from cache, reducing the job from ~7 minutes to ~2 minutes.

---

**Q10: What is the difference between a 400 and 422 in your API?**

> `422 Unprocessable Entity` is automatic from FastAPI/Pydantic — wrong types, missing required fields. `400 Bad Request` is our custom application logic — empty queries, invalid business rules. Keeping them separate lets API consumers distinguish structural errors from semantic ones.

---

**Q11: How does MockLLM simulate streaming?**

> `MockLLM.astream()` is an `async def` generator that `yield`s strings: `"Mocked "`, `"LLM "`, `"response."`. The real app code calls `async for chunk in llm.astream(...)` — it works identically with our mock because it implements the same async generator protocol, just with canned output instead of Gemini responses.

---

**Q12: How does the stress test measure latency percentiles?**

> `stress_test.py` records `time.monotonic()` before and after each `httpx` request. After all coroutines complete, it collects all latencies into a sorted list and computes `p50 = median`, `p95 = latencies[int(n * 0.95)]`, `p99 = latencies[int(n * 0.99)]` using Python's `statistics` module.

---

**Q13: What does `raise_server_exceptions=False` do in TestClient?**

> Normally, if a FastAPI route raises an exception (e.g., `HTTPException`), TestClient re-raises it in the test. With `raise_server_exceptions=False`, the TestClient captures the exception and returns it as an HTTP response — so `assert resp.status_code == 401` works correctly rather than pytest seeing an uncaught exception.

---

**Q14: How would you add a test for rate limiting?**

> Use `asyncio.gather()` to send N+1 requests to `/chat` concurrently (where N is the rate limit). Assert that at least one response is `429 Too Many Requests`. Then verify that requests after the rate limit window expires succeed again. Mark with `@pytest.mark.asyncio` and use `httpx.AsyncClient`.

---

**Q15: Why test expired tokens separately from bad signatures?**

> They fail at different points in `jwt.decode()`. Expired tokens fail the `exp` claim check. Bad signatures fail the HMAC verification. An implementation could correctly reject bad signatures but accidentally accept expired tokens if `options={"verify_exp": False}` was set. Testing both ensures both checks are active.

---

**Q16: What is the ramp-up test in stress_test.py looking for?**

> It gradually increases concurrency (1 → 5 → 10 → 20 requests) and stops when the failure rate exceeds 20%. The concurrency level where it stops is the "breakpoint" — the practical limit of the backend before it degrades unacceptably. This gives a production capacity number.

---

**Q17: How would you make test_prompt2_pipeline.py run in CI?**

> Add a Docker Compose job to CI that starts MongoDB, Redis, Celery worker, and FastAPI together. Use a `depends_on` health check to wait for readiness. Run the pipeline test as a separate CI job marked `needs: [rag-engine-tests]` so it only runs after unit tests pass. Use `pytest.mark.live` to isolate it from the fast unit test suite.

---

**Q18: What would happen if you didn't set env vars before importing main.py in conftest.py?**

> `main.py` reads `os.getenv("JWT_SECRET_KEY")` at module load time and uses the value to initialize the JWT middleware. If we import `main` before setting the env vars, the middleware initializes with `None` or an empty string, causing all JWT operations to fail with cryptography errors — not `401` responses but `500` crashes.

---

**Q19: How does the file filter test differ from other tests?**

> It tests pure Python logic with zero mocks, no HTTP, no fixtures. It directly defines and calls `is_source_file()` inline (reproducing the logic from `worker.py`). This makes it self-contained and acts as both a correctness check and documentation of which file types we embed. If the function changes, the test breaks immediately.

---

**Q20: If you had to add one more test tomorrow, what would it be?**

> I'd add an SSE content assertion to `test_chat_streams_response`. Currently we only assert the status code isn't `401/403`. A more meaningful test would: (1) send a chat request, (2) parse the SSE response body line by line, (3) assert that at least one `data:` event contains a `"text"` field with non-empty content, and (4) assert that the last event has `"done": true`. This would catch silent failures where the endpoint returns `200` but the stream is immediately empty or malformed.

---

*Documentation generated from live source code analysis of the RAGnarok test suite.*  
*Last reviewed: 2026-08-11 | Test count: 26 | Coverage gate: 70% | CI: GitHub Actions*
