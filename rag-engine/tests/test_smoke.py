"""
tests/test_smoke.py
-------------------
Post-deployment smoke tests to verify production is alive.

Tests:
  27. GET /health returns 200 (prod is alive)
  28. POST /chat/{session} without auth returns 401 (auth guard active)

Run AFTER deployment to verify prod is alive:
    pytest tests/test_smoke.py -v

Configure the production URL via the RAGNAROK_PROD_URL environment variable:
    export RAGNAROK_PROD_URL="https://your-prod-domain.com"
"""

import os
# pyrefly: ignore [missing-import]
import pytest

# ---------------------------------------------------------------------------
# Configuration — override via env var for your actual prod domain
# ---------------------------------------------------------------------------
PROD_URL = os.getenv("RAGNAROK_PROD_URL", "https://your-xyz-domain.com")

# Only run smoke tests when RAGNAROK_PROD_URL is explicitly set,
# so they don't accidentally fail during local `pytest` runs.
skip_if_no_prod = pytest.mark.skipif(
    not os.getenv("RAGNAROK_PROD_URL"),
    reason="RAGNAROK_PROD_URL not set — skipping production smoke tests",
)


# ============================================================
# 27. Production health check
# ============================================================

@skip_if_no_prod
def test_prod_health():
    """GET /health on the deployed production server must return 200."""
    import requests

    r = requests.get(f"{PROD_URL}/health", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("status") == "ok", f"Health status is not 'ok': {data}"


# ============================================================
# 28. Production auth guard is active
# ============================================================

@skip_if_no_prod
def test_prod_auth_required():
    """POST /chat/{session} without a token must return 401 in production."""
    import requests

    r = requests.post(
        f"{PROD_URL}/chat/test",
        json={"query": "smoke test"},
        timeout=10,
    )
    assert r.status_code == 401, (
        f"Expected 401 (auth required), got {r.status_code}: {r.text}"
    )
