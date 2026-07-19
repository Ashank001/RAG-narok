"""
tests/conftest.py
-----------------
Shared pytest fixtures for all RAGnarok backend tests.

Provides:
  - Real JWT token minting (no GitHub OAuth needed)
  - Mocked Google Embedding API (no tokens burned)
  - Mocked Gemini LLM (deterministic canned responses)
  - In-memory MongoDB via mongomock (no Atlas connection)
  - FastAPI TestClient

Install test dependencies:
  pip install pytest pytest-asyncio httpx mongomock python-jose[cryptography]
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure the rag-engine root and tests/ are on sys.path so pytest can
# resolve 'from conftest import ...' and 'from main import app' correctly.
_here = os.path.dirname(os.path.abspath(__file__))
_rag_root = os.path.dirname(_here)
for _p in (_rag_root, _here):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# pyrefly: ignore [missing-import]
import pytest
# pyrefly: ignore [missing-import]
from fastapi.testclient import TestClient
from jose import jwt  # pyrefly: ignore [missing-import, missing-source-for-stubs]


# ---------------------------------------------------------------------------
# Test environment — set BEFORE importing the app so env-dependent module
# initialisation (MONGO_URI, JWT_SECRET_KEY) succeeds.
# ---------------------------------------------------------------------------
TEST_JWT_SECRET = "test-secret-key-for-testing-only"
TEST_ALGORITHM = "HS256"

os.environ.setdefault("JWT_SECRET_KEY", TEST_JWT_SECRET)
os.environ.setdefault("JWT_ALGORITHM", TEST_ALGORITHM)
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/test_rag_db")
os.environ.setdefault("GOOGLE_API_KEY", "fake-api-key-for-tests")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OAUTH_ID", "fake-github-client-id")
os.environ.setdefault("OAUTH_SECRET_KEY", "fake-github-client-secret")


# ---------------------------------------------------------------------------
# Token factory
# ---------------------------------------------------------------------------

def make_token(username: str, expires_in_minutes: int = 60) -> str:
    """
    Mint a valid JWT for the given username WITHOUT going through GitHub OAuth.
    This is what the tests use to authenticate against the FastAPI endpoints.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_ALGORITHM)


def make_expired_token(username: str) -> str:
    """Mint a JWT that is already expired."""
    expire = datetime.now(timezone.utc) - timedelta(minutes=5)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_ALGORITHM)


# ---------------------------------------------------------------------------
# Embedding mock: returns a zero vector without calling Google API
# ---------------------------------------------------------------------------

class MockEmbeddings:
    """Drop-in for GoogleGenerativeAIEmbeddings that never makes network calls."""

    def embed_query(self, text: str):
        return [0.0] * 768

    def embed_documents(self, texts: list[str]):
        return [[0.0] * 768 for _ in texts]

    async def aembed_query(self, text: str):
        return [0.0] * 768

    async def aembed_documents(self, texts: list[str]):
        return [[0.0] * 768 for _ in texts]


# ---------------------------------------------------------------------------
# LLM mock: returns canned streaming chunks without calling Gemini
# ---------------------------------------------------------------------------

class MockLLM:
    """Drop-in for ChatGoogleGenerativeAI that never makes network calls."""

    async def astream(self, input, **kwargs):
        chunks = ["Mocked ", "LLM ", "response."]
        for chunk in chunks:
            yield chunk

    def stream(self, input, **kwargs):
        yield from ["Mocked ", "LLM ", "response."]


# ---------------------------------------------------------------------------
# MongoDB mock: in-memory via mongomock
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_mongo():
    """
    Provides an in-memory MongoDB client using mongomock.
    Session-scoped so the same fake DB is shared across all tests in a session,
    avoiding repeated setup/teardown overhead.
    """
    try:
        import mongomock  # pyrefly: ignore [missing-import]
        client = mongomock.MongoClient()
        yield client
    except ImportError:
        pytest.skip("mongomock not installed -- run: pip install mongomock")


# ---------------------------------------------------------------------------
# FastAPI TestClient with all external dependencies mocked
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client(mock_mongo) -> Generator:
    """
    Returns a synchronous TestClient for the FastAPI app.

    Patches:
      - GoogleGenerativeAIEmbeddings  ->  MockEmbeddings
      - ChatGoogleGenerativeAI        ->  MockLLM
      - MongoClient                   ->  mongomock client
      - MongoDBAtlasVectorSearch      ->  MagicMock with similarity_search stub
    """
    # Build a mock vector store that returns empty results by default
    mock_vs = MagicMock()
    mock_vs.similarity_search.return_value = []
    mock_vs.add_documents.return_value = None

    with (
        patch("langchain_google_genai.GoogleGenerativeAIEmbeddings", return_value=MockEmbeddings()),
        patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=MockLLM()),
        patch("pymongo.MongoClient", return_value=mock_mongo),
        patch("langchain_mongodb.MongoDBAtlasVectorSearch", return_value=mock_vs),
    ):
        # pyrefly: ignore [missing-import]
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Convenience auth header builders
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_headers_user_a() -> dict:
    return {"Authorization": f"Bearer {make_token('user_alice')}"}

@pytest.fixture
def auth_headers_user_b() -> dict:
    return {"Authorization": f"Bearer {make_token('user_bob')}"}

@pytest.fixture
def expired_auth_headers() -> dict:
    return {"Authorization": f"Bearer {make_expired_token('user_expired')}"}
