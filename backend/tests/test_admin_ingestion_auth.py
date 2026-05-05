"""
Phase 4.1 — Admin Ingestion Route Hardening: authorization tests.

Tests ONLY auth behavior for the two ingestion routes.
Provider logic is always mocked — no network calls.

Run:
    docker compose exec api pytest tests/test_admin_ingestion_auth.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def plain_client():
    """TestClient with no auth override — requests without a token will get 401."""
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def non_admin_client():
    """TestClient whose claims carry an empty scopes list — expect 403."""
    from main import app
    from core.dependencies import get_current_user_claims

    async def override():
        return {"sub": "user1", "scopes": []}

    app.dependency_overrides[get_current_user_claims] = override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


@pytest.fixture()
def no_scopes_client():
    """TestClient whose claims have no scopes key at all — expect 403."""
    from main import app
    from core.dependencies import get_current_user_claims

    async def override():
        return {"sub": "user1"}

    app.dependency_overrides[get_current_user_claims] = override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


@pytest.fixture()
def admin_client():
    """TestClient whose claims carry admin scope — expect 200 when provider mocked."""
    from main import app
    from core.dependencies import get_current_user_claims

    async def override():
        return {"sub": "admin1", "scopes": ["admin"]}

    app.dependency_overrides[get_current_user_claims] = override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


# ── Backfill route — /financial/ingest/prices/backfill ────────────────────────

def test_backfill_rejects_no_token(plain_client):
    resp = plain_client.post("/financial/ingest/prices/backfill", json={})
    assert resp.status_code == 401


def test_backfill_rejects_non_admin_token(non_admin_client):
    resp = non_admin_client.post("/financial/ingest/prices/backfill", json={})
    assert resp.status_code == 403


def test_backfill_rejects_missing_scopes(no_scopes_client):
    resp = no_scopes_client.post("/financial/ingest/prices/backfill", json={})
    assert resp.status_code == 403


@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_accepts_admin_token(MockProvider, admin_client):
    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value={
        "provider": "yfinance",
        "symbol": "SPY",
        "status": "ok",
        "rows_ingested": 3,
    })
    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": ["SPY"], "days": 7},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_symbols"] == 1
    assert data["succeeded"] == 1


# ── Single-symbol ingest route — /financial/ingest/prices ─────────────────────

def test_ingest_prices_rejects_no_token(plain_client):
    resp = plain_client.post(
        "/financial/ingest/prices",
        json={"symbol": "AAPL"},
    )
    assert resp.status_code == 401


def test_ingest_prices_rejects_non_admin_token(non_admin_client):
    resp = non_admin_client.post(
        "/financial/ingest/prices",
        json={"symbol": "AAPL"},
    )
    assert resp.status_code == 403


def test_ingest_prices_rejects_missing_scopes(no_scopes_client):
    resp = no_scopes_client.post(
        "/financial/ingest/prices",
        json={"symbol": "AAPL"},
    )
    assert resp.status_code == 403


@patch("financial.routes.prices.StooqProvider")
def test_ingest_prices_accepts_admin_token(MockProvider, admin_client):
    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value={
        "provider": "stooq",
        "status": "ok",
        "rows_ingested": 5,
    })
    resp = admin_client.post(
        "/financial/ingest/prices",
        json={"symbol": "AAPL"},
    )
    assert resp.status_code == 200


# ── Optional: chat route must NOT require admin scope ─────────────────────────
#
# Skipped: /chat depends on DB, Redis, Pinecone, OpenAI, and the full chat
# service pipeline. Mocking all of those to reach a 200 is out of scope for
# this hardening phase. The relevant assertion — that chat accepts any valid
# user token without an admin scope — is implicitly guaranteed by the fact
# that chat.py was not edited and its get_current_user dependency has no
# require_scope call. Verify via the existing chat test suite instead.
