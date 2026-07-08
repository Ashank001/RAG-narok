"""
tests/test_auth.py
------------------
Unit tests for authentication endpoints and JWT middleware.

Tests:
  1. /health is publicly accessible (no auth required)
  2. /chat rejects requests with no token (401)
  3. /chat rejects requests with an expired token (401)
  4. /chat rejects requests with a tampered/invalid token (401)
  5. /api/ingest rejects unauthenticated requests (401)
  6. /api/auth/github succeeds with a valid GitHub OAuth mock
  7. /api/auth/github returns 400 when no code is supplied
  8. /api/auth/github returns 400 when GitHub rejects the code
"""

import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from conftest import make_token, make_expired_token, TEST_JWT_SECRET, TEST_ALGORITHM

# ============================================================
# 1. Public health endpoint
# ============================================================

def test_health_is_public(client):
    """GET /health must succeed without any Authorization header."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "rag-engine" in data["service"]


# ============================================================
# 2. Unauthenticated access → 401
# ============================================================

def test_chat_requires_auth(client):
    """POST /chat without a token must return 401."""
    resp = client.post("/chat/test_session", json={"query": "hello"})
    assert resp.status_code == 401


def test_ingest_requires_auth(client):
    """POST /api/ingest without a token must return 401."""
    resp = client.post(
        "/api/ingest",
        json={"sessionId": "s1", "repositoryUrl": "https://github.com/owner/repo"},
    )
    assert resp.status_code == 401


# ============================================================
# 3. Expired token → 401
# ============================================================

def test_chat_rejects_expired_token(client, expired_auth_headers):
    """POST /chat with an expired JWT must return 401."""
    resp = client.post(
        "/chat/test_session",
        json={"query": "what does main.py do?"},
        headers=expired_auth_headers,
    )
    assert resp.status_code == 401


# ============================================================
# 4. Tampered / invalid token → 401
# ============================================================

def test_chat_rejects_bad_signature(client):
    """A JWT signed with a wrong secret must be rejected."""
    bad_token = make_token("hacker", expires_in_minutes=60)
    # Re-sign with a different secret to simulate tampering
    from jose import jwt as _jwt
    parts = bad_token.split(".")
    # Corrupt the signature
    tampered = f"{parts[0]}.{parts[1]}.INVALIDSIGNATURE"
    resp = client.post(
        "/chat/test_session",
        json={"query": "exploit"},
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert resp.status_code == 401


def test_chat_rejects_malformed_token(client):
    """A completely invalid token string must return 401."""
    resp = client.post(
        "/chat/test_session",
        json={"query": "hello"},
        headers={"Authorization": "Bearer not.a.real.jwt"},
    )
    assert resp.status_code == 401


# ============================================================
# 5. Valid token → protected endpoint accessible
# ============================================================

def test_chat_accepts_valid_token(client, auth_headers_user_a):
    """
    A valid JWT must pass the auth guard. The actual response may be an empty
    stream (no vectors ingested in test DB), but the HTTP status should NOT be
    401 or 403.
    """
    resp = client.post(
        "/chat/test_session",
        json={"query": "explain the architecture"},
        headers=auth_headers_user_a,
    )
    # 200 (stream) or 400 (empty query) — never 401/403
    assert resp.status_code not in (401, 403)


# ============================================================
# 6. /api/auth/github — successful code exchange
# ============================================================

def test_github_auth_success(client):
    """
    Mocks the external GitHub API calls inside the endpoint so no real
    HTTP traffic is made. Verifies that a valid JWT is returned.
    """
    mock_token_response = MagicMock()
    mock_token_response.json.return_value = {"access_token": "gho_faketoken"}

    mock_user_response = MagicMock()
    mock_user_response.json.return_value = {"login": "testuser"}

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)
    mock_async_client.post = AsyncMock(return_value=mock_token_response)
    mock_async_client.get = AsyncMock(return_value=mock_user_response)

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        resp = client.post("/api/auth/github", json={"code": "valid_github_code"})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["username"] == "testuser"
    assert data["token_type"] == "bearer"

    # Verify the returned token is a real JWT with the correct subject
    from jose import jwt as _jwt
    payload = _jwt.decode(data["access_token"], TEST_JWT_SECRET, algorithms=[TEST_ALGORITHM])
    assert payload["sub"] == "testuser"


# ============================================================
# 7. /api/auth/github — missing code → 400
# ============================================================

def test_github_auth_missing_code(client):
    """POST /api/auth/github with no 'code' field must return 400."""
    resp = client.post("/api/auth/github", json={})
    assert resp.status_code == 400
    assert "missing" in resp.json()["detail"].lower()


# ============================================================
# 8. /api/auth/github — GitHub rejects the code → 400
# ============================================================

def test_github_auth_invalid_code(client):
    """
    When GitHub returns no access_token (e.g. code already used),
    the endpoint must return 400.
    """
    mock_token_response = MagicMock()
    mock_token_response.json.return_value = {"error": "bad_verification_code"}  # no access_token

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)
    mock_async_client.post = AsyncMock(return_value=mock_token_response)

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        resp = client.post("/api/auth/github", json={"code": "stale_code"})

    assert resp.status_code == 400


# ============================================================
# 9. JWT sub field must be present
# ============================================================

def test_token_without_sub_rejected(client):
    """A JWT missing the 'sub' claim must be rejected as unauthenticated."""
    from jose import jwt as _jwt
    from datetime import datetime, timedelta
    payload = {"exp": datetime.utcnow() + timedelta(minutes=60)}  # no 'sub'
    no_sub_token = _jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_ALGORITHM)
    resp = client.post(
        "/chat/test_session",
        json={"query": "hello"},
        headers={"Authorization": f"Bearer {no_sub_token}"},
    )
    assert resp.status_code == 401
