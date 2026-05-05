"""
Phase 4.5 — Ingestion Run Tracking tests.

All tests are hermetic: no real DB, no Redis, no YFinance, no network.

Run:
    docker compose exec api pytest tests/test_ingestion_runs.py -v
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _mock_pool():
    return MagicMock()


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
def anon_client():
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Service: run tracking — success ──────────────────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_run_tracking_success_writes_record(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value={"rows_ingested": 5})

    _run(refresh_prices(_mock_pool(), ["SPY", "AAPL"], 30, trigger="manual"))

    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["status"] == "success"
    assert kwargs["failed"] == 0
    assert kwargs["error_summary"] is None
    assert kwargs["trigger_type"] == "manual"
    assert kwargs["run_type"] == "price_backfill"


# ── Service: run tracking — partial failure ───────────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_run_tracking_partial_failure_writes_partial_status(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    call_count = 0

    async def side_effect(pool):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("network timeout")
        return {"rows_ingested": 3}

    instance = MockProvider.return_value
    instance.ingest_incremental.side_effect = side_effect

    _run(refresh_prices(_mock_pool(), ["SPY", "AAPL"], 30, trigger="manual"))

    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["status"] == "partial"
    assert kwargs["failed"] == 1
    assert kwargs["succeeded"] == 1
    assert kwargs["error_summary"] is not None
    assert "SPY" in kwargs["error_summary"]
    assert "network timeout" in kwargs["error_summary"]


# ── Service: run tracking — total failure ────────────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_run_tracking_total_failure_writes_failed_status(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(side_effect=RuntimeError("boom"))

    _run(refresh_prices(_mock_pool(), ["SPY", "AAPL"], 30, trigger="scheduled"))

    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failed"] == 2
    assert kwargs["succeeded"] == 0
    assert kwargs["symbols_count"] == 2


# ── Service: rows_ingested summed correctly ───────────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_run_tracking_rows_ingested_summed_correctly(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value={"rows_ingested": 5})

    _run(refresh_prices(_mock_pool(), ["SPY", "AAPL", "TSLA"], 30))

    kwargs = mock_insert.call_args.kwargs
    assert kwargs["rows_ingested"] == 15


# ── Service: insert failure does not fail refresh ────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_run_tracking_insert_failure_does_not_fail_refresh(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(return_value={"rows_ingested": 2})
    mock_insert.side_effect = RuntimeError("DB unavailable")

    result = _run(refresh_prices(_mock_pool(), ["SPY"], 30))

    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["total_symbols"] == 1


# ── Route: trigger=manual passed from backfill route ─────────────────────────

@patch("financial.routes.prices.refresh_prices", new_callable=AsyncMock)
def test_run_tracking_trigger_manual_from_backfill_route(mock_refresh, admin_client):
    mock_refresh.return_value = {
        "results": [],
        "total_symbols": 0,
        "succeeded": 0,
        "failed": 0,
    }

    resp = admin_client.post(
        "/financial/ingest/prices/backfill",
        json={},
    )

    assert resp.status_code == 200
    bound_args = mock_refresh.call_args
    # trigger is the 4th positional arg or a kwarg
    trigger_value = (
        bound_args.kwargs.get("trigger")
        or (bound_args.args[3] if len(bound_args.args) > 3 else None)
    )
    assert trigger_value == "manual"


# ── Worker: trigger=scheduled passed from worker ─────────────────────────────

@patch("worker_entrypoint.refresh_prices", new_callable=AsyncMock)
def test_run_tracking_trigger_scheduled_from_worker(mock_refresh):
    from worker_entrypoint import _handle_financial_ingestion
    from core.config import PRICE_BACKFILL_SYMBOLS, PRICE_BACKFILL_DEFAULT_DAYS

    mock_refresh.return_value = {
        "results": [],
        "total_symbols": 10,
        "succeeded": 10,
        "failed": 0,
    }

    pool = _mock_pool()
    _run(_handle_financial_ingestion(pool, {"type": "price_refresh"}))

    mock_refresh.assert_called_once_with(
        pool,
        PRICE_BACKFILL_SYMBOLS,
        PRICE_BACKFILL_DEFAULT_DAYS,
        trigger="scheduled",
    )


# ── Endpoint: auth guards ─────────────────────────────────────────────────────

def test_runs_endpoint_requires_admin_no_token(anon_client):
    resp = anon_client.get("/financial/ingest/runs")
    assert resp.status_code == 401


def test_runs_endpoint_requires_admin_scope(non_admin_client):
    resp = non_admin_client.get("/financial/ingest/runs")
    assert resp.status_code == 403


# ── Endpoint: response shape ──────────────────────────────────────────────────

@patch("financial.routes.prices.get_recent_ingestion_runs", new_callable=AsyncMock)
def test_runs_endpoint_returns_latest_runs(mock_get_runs, admin_client):
    mock_get_runs.return_value = [
        {
            "id": 1,
            "run_type": "price_refresh",
            "trigger_type": "scheduled",
            "provider": "yfinance",
            "symbols_count": 10,
            "succeeded": 10,
            "failed": 0,
            "rows_ingested": 50,
            "status": "success",
            "error_summary": None,
            "started_at": "2026-05-04T02:00:00",
            "finished_at": "2026-05-04T02:00:12",
            "duration_ms": 12000,
            "created_at": "2026-05-04T02:00:12",
        }
    ]

    resp = admin_client.get("/financial/ingest/runs")

    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "count" in data
    assert data["count"] == 1
    run = data["runs"][0]
    assert run["run_type"] == "price_refresh"
    assert run["trigger_type"] == "scheduled"
    assert run["status"] == "success"


# ── Endpoint: run_type filter forwarded ──────────────────────────────────────

@patch("financial.routes.prices.get_recent_ingestion_runs", new_callable=AsyncMock)
def test_runs_endpoint_run_type_filter(mock_get_runs, admin_client):
    mock_get_runs.return_value = []

    resp = admin_client.get("/financial/ingest/runs?run_type=price_refresh")

    assert resp.status_code == 200
    mock_get_runs.assert_called_once()
    _, kwargs = mock_get_runs.call_args
    assert kwargs.get("run_type") == "price_refresh"


# ── Service: error_summary capped at 500 chars ───────────────────────────────

@patch("financial.services.price_refresh_service.insert_ingestion_run", new_callable=AsyncMock)
@patch("financial.services.price_refresh_service.YFinancePriceProvider")
def test_error_summary_capped_at_500_chars(MockProvider, mock_insert):
    from financial.services.price_refresh_service import refresh_prices

    long_error = "x" * 2000

    instance = MockProvider.return_value
    instance.ingest_incremental = AsyncMock(side_effect=RuntimeError(long_error))

    _run(refresh_prices(_mock_pool(), ["SPY"], 30))

    kwargs = mock_insert.call_args.kwargs
    assert kwargs["error_summary"] is not None
    assert len(kwargs["error_summary"]) <= 500
