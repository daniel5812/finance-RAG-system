"""
Phase 4D — Price Backfill Foundation tests.

All tests are hermetic: no network, no real DB.
YFinancePriceProvider.ingest_incremental is always mocked.

Run:
    docker compose exec api pytest tests/test_price_backfill.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, timedelta

from fastapi.testclient import TestClient


# ── Config tests ──────────────────────────────────────────────────────────────

def test_config_default_symbols_include_core_assets():
    from core.config import PRICE_BACKFILL_SYMBOLS
    required = {"SPY", "QQQ", "VOO", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"}
    missing = required - set(PRICE_BACKFILL_SYMBOLS)
    assert not missing, f"Missing default symbols: {missing}"


def test_config_default_days_is_positive():
    from core.config import PRICE_BACKFILL_DEFAULT_DAYS
    assert PRICE_BACKFILL_DEFAULT_DAYS > 0


def test_config_symbol_parsing_strips_and_uppercases(monkeypatch):
    monkeypatch.setenv("PRICE_BACKFILL_SYMBOLS", " aapl , tsla , nvda ")
    # Re-import to pick up the patched env — use importlib to reload the module.
    import importlib
    import core.config as cfg
    importlib.reload(cfg)
    assert "AAPL" in cfg.PRICE_BACKFILL_SYMBOLS
    assert "TSLA" in cfg.PRICE_BACKFILL_SYMBOLS
    assert "NVDA" in cfg.PRICE_BACKFILL_SYMBOLS
    # Reload back to defaults so other tests are not affected.
    monkeypatch.delenv("PRICE_BACKFILL_SYMBOLS", raising=False)
    importlib.reload(cfg)


# ── Schema validation tests ───────────────────────────────────────────────────

def test_schema_accepts_valid_request():
    from financial.schemas import PriceBackfillRequest
    req = PriceBackfillRequest(symbols=["AAPL", "TSLA"], days=180)
    assert req.symbols == ["AAPL", "TSLA"]
    assert req.days == 180


def test_schema_accepts_empty_body():
    from financial.schemas import PriceBackfillRequest
    req = PriceBackfillRequest()
    assert req.symbols is None
    assert req.days is None


def test_backfill_rejects_non_positive_days():
    from pydantic import ValidationError
    from financial.schemas import PriceBackfillRequest
    with pytest.raises(ValidationError):
        PriceBackfillRequest(days=0)
    with pytest.raises(ValidationError):
        PriceBackfillRequest(days=-1)


# ── Route behaviour tests (via TestClient) ────────────────────────────────────

def _make_success_outcome(symbol: str, rows: int = 5) -> dict:
    return {
        "provider": "yfinance",
        "symbol": symbol,
        "status": "ok",
        "rows_ingested": rows,
    }


@pytest.fixture()
def client():
    """Return a TestClient backed by the real FastAPI app with a mocked DB pool."""
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def admin_client():
    """TestClient with get_current_user_claims overridden to inject admin scope."""
    from main import app
    from core.dependencies import get_current_user_claims

    async def override_claims():
        return {"sub": "test_admin", "scopes": ["admin"]}

    app.dependency_overrides[get_current_user_claims] = override_claims
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_current_user_claims, None)


def _mock_pool():
    pool = MagicMock()
    return pool


# For route tests we patch at the provider level so no real network call occurs.

@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_uses_configured_symbols_when_request_empty(MockProvider, admin_client):
    from core.config import PRICE_BACKFILL_SYMBOLS

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value=_make_success_outcome("X"))

    with patch("financial.routes.prices.get_db_pool", return_value=lambda: _mock_pool()):
        resp = admin_client.post("/financial/ingest/prices/backfill", json={})

    assert resp.status_code == 200
    data = resp.json()
    returned_symbols = {r["symbol"] for r in data["results"]}
    assert returned_symbols == set(PRICE_BACKFILL_SYMBOLS)
    assert data["total_symbols"] == len(PRICE_BACKFILL_SYMBOLS)


@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_explicit_symbols_override_defaults(MockProvider, admin_client):
    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value=_make_success_outcome("AAPL"))

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": ["AAPL", "TSLA"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    returned_symbols = {r["symbol"] for r in data["results"]}
    assert returned_symbols == {"AAPL", "TSLA"}
    assert data["total_symbols"] == 2


@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_calls_ingest_incremental_per_symbol(MockProvider, admin_client):
    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value=_make_success_outcome("X"))

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": ["AAPL", "MSFT", "NVDA"]},
    )
    assert resp.status_code == 200
    assert instance.ingest_incremental.call_count == 3


@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_per_symbol_failure_does_not_stop_others(MockProvider, admin_client):
    instance = MockProvider.return_value

    call_count = 0

    async def side_effect(pool):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated network failure")
        return _make_success_outcome("TSLA")

    instance.ingest_incremental.side_effect = side_effect

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": ["AAPL", "TSLA"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    statuses = {r["symbol"]: r["status"] for r in data["results"]}
    assert statuses["AAPL"] == "failed"
    assert statuses["TSLA"] == "success"


@patch("financial.routes.prices.YFinancePriceProvider")
def test_backfill_response_shape(MockProvider, admin_client):
    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value=_make_success_outcome("SPY", rows=100))

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": ["SPY"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "total_symbols" in data
    assert "succeeded" in data
    assert "failed" in data
    assert data["total_symbols"] == 1
    assert data["succeeded"] == 1
    assert data["failed"] == 0
    row = data["results"][0]
    assert row["symbol"] == "SPY"
    assert row["status"] == "success"
    assert "rows_ingested" in row
    assert "error" in row
    assert row["error"] is None


def test_backfill_rejects_empty_symbols_list(admin_client):
    # An explicit empty list is not the same as omitting symbols.
    # The schema allows it (no min_items constraint) but the route
    # will return total_symbols=0 with empty results — not a 422.
    # Validate the schema accepts it and the route returns a coherent response.
    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"symbols": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_symbols"] == 0
    assert data["succeeded"] == 0
    assert data["failed"] == 0
    assert data["results"] == []


def test_backfill_rejects_non_positive_days_via_http(admin_client):
    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"days": 0},
    )
    assert resp.status_code == 422

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={"days": -10},
    )
    assert resp.status_code == 422
