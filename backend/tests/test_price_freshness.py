"""
Phase 4.4A — Price Freshness Service & Admin Endpoint tests.

All tests are hermetic: no network, no real DB, no Redis, no external providers.

Run:
    docker compose exec api pytest tests/test_price_freshness.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_pool():
    return MagicMock()


def _run(coro):
    return asyncio.run(coro)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def admin_client():
    from main import app
    from core.dependencies import get_current_user_claims

    async def override_claims():
        return {"sub": "test_admin", "scopes": ["admin"]}

    app.dependency_overrides[get_current_user_claims] = override_claims
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


@pytest.fixture()
def non_admin_client():
    from main import app
    from core.dependencies import get_current_user_claims

    async def override_claims():
        return {"sub": "test_employee", "scopes": ["employee"]}

    app.dependency_overrides[get_current_user_claims] = override_claims
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


@pytest.fixture()
def client():
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Service unit tests — get_price_freshness ─────────────────────────────────

@patch(
    "financial.services.price_refresh_service.get_latest_price_dates_bulk",
    new_callable=AsyncMock,
)
def test_freshness_fresh_symbol(mock_bulk):
    from financial.services.price_refresh_service import get_price_freshness

    today = date.today()
    mock_bulk.return_value = {"SPY": today - timedelta(days=1)}

    result = _run(get_price_freshness(_mock_pool(), ["SPY"]))

    assert len(result) == 1
    row = result[0]
    assert row["symbol"] == "SPY"
    assert row["status"] == "fresh"
    assert row["stale"] is False
    assert row["latest_date"] == (today - timedelta(days=1)).isoformat()


@patch(
    "financial.services.price_refresh_service.get_latest_price_dates_bulk",
    new_callable=AsyncMock,
)
def test_freshness_stale_symbol(mock_bulk):
    from financial.services.price_refresh_service import get_price_freshness

    today = date.today()
    mock_bulk.return_value = {"SPY": today - timedelta(days=6)}

    result = _run(get_price_freshness(_mock_pool(), ["SPY"]))

    assert len(result) == 1
    row = result[0]
    assert row["symbol"] == "SPY"
    assert row["status"] == "stale"
    assert row["stale"] is True
    assert row["latest_date"] == (today - timedelta(days=6)).isoformat()


@patch(
    "financial.services.price_refresh_service.get_latest_price_dates_bulk",
    new_callable=AsyncMock,
)
def test_freshness_missing_symbol(mock_bulk):
    from financial.services.price_refresh_service import get_price_freshness

    mock_bulk.return_value = {"SPY": None}

    result = _run(get_price_freshness(_mock_pool(), ["SPY"]))

    assert len(result) == 1
    row = result[0]
    assert row["symbol"] == "SPY"
    assert row["status"] == "missing"
    assert row["stale"] is True
    assert row["latest_date"] is None


@patch(
    "financial.services.price_refresh_service.get_latest_price_dates_bulk",
    new_callable=AsyncMock,
)
def test_freshness_mixed_symbols(mock_bulk):
    from financial.services.price_refresh_service import get_price_freshness

    today = date.today()
    mock_bulk.return_value = {
        "SPY": today - timedelta(days=1),   # fresh
        "TSLA": today - timedelta(days=6),  # stale
        "NVDA": None,                        # missing
    }

    result = _run(get_price_freshness(_mock_pool(), ["SPY", "TSLA", "NVDA"]))

    by_symbol = {r["symbol"]: r for r in result}

    assert by_symbol["SPY"]["status"] == "fresh"
    assert by_symbol["SPY"]["stale"] is False

    assert by_symbol["TSLA"]["status"] == "stale"
    assert by_symbol["TSLA"]["stale"] is True

    assert by_symbol["NVDA"]["status"] == "missing"
    assert by_symbol["NVDA"]["stale"] is True
    assert by_symbol["NVDA"]["latest_date"] is None


# ── Service unit tests — refresh_prices ──────────────────────────────────────

@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_refresh_service_uses_configured_symbols(MockProvider):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(
        return_value={"provider": "yfinance", "status": "ok", "rows_ingested": 5}
    )

    result = _run(refresh_prices(_mock_pool(), ["SPY", "AAPL"], 30))

    assert MockProvider.call_count == 2
    assert instance.ingest_incremental.call_count == 2
    assert result["total_symbols"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0


@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_refresh_service_per_symbol_failure_isolation(MockProvider):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    call_count = 0

    async def side_effect(pool):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated network failure")
        return {"provider": "yfinance", "status": "ok", "rows_ingested": 3}

    instance.ingest_incremental.side_effect = side_effect

    result = _run(refresh_prices(_mock_pool(), ["AAPL", "TSLA"], 30))

    assert result["succeeded"] == 1
    assert result["failed"] == 1
    by_symbol = {r["symbol"]: r for r in result["results"]}
    assert by_symbol["AAPL"]["status"] == "failed"
    assert by_symbol["AAPL"]["error"] == "simulated network failure"
    assert by_symbol["TSLA"]["status"] == "success"


# ── Endpoint tests ────────────────────────────────────────────────────────────

@patch("financial.routes.prices.get_price_freshness", new_callable=AsyncMock)
def test_freshness_endpoint_shape(mock_freshness, admin_client):
    today = date.today()
    mock_freshness.return_value = [
        {"symbol": "SPY", "latest_date": (today - timedelta(days=1)).isoformat(), "status": "fresh", "stale": False},
        {"symbol": "QQQ", "latest_date": None, "status": "missing", "stale": True},
    ]

    resp = admin_client.get("/financial/prices/freshness")

    assert resp.status_code == 200
    data = resp.json()

    assert "symbols" in data
    assert "as_of" in data
    assert "staleness_days" in data
    assert data["as_of"] == today.isoformat()
    assert isinstance(data["staleness_days"], int)
    assert len(data["symbols"]) == 2

    for row in data["symbols"]:
        assert "symbol" in row
        assert "status" in row
        assert "latest_date" in row
        assert "stale" in row


def test_freshness_endpoint_requires_admin_no_token(client):
    resp = client.get("/financial/prices/freshness")
    assert resp.status_code == 401


def test_freshness_endpoint_requires_admin_non_admin(non_admin_client):
    resp = non_admin_client.get("/financial/prices/freshness")
    assert resp.status_code == 403


# ── Config tests ──────────────────────────────────────────────────────────────

def test_staleness_days_config_default():
    from core.config import PRICE_STALENESS_DAYS
    assert PRICE_STALENESS_DAYS == 5


def test_staleness_days_config_env_override(monkeypatch):
    monkeypatch.setenv("PRICE_STALENESS_DAYS", "7")
    import core.config as cfg
    importlib.reload(cfg)
    assert cfg.PRICE_STALENESS_DAYS == 7
    monkeypatch.delenv("PRICE_STALENESS_DAYS", raising=False)
    importlib.reload(cfg)
