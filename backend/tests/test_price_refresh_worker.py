"""
Phase 4.4B — Scheduled Price Refresh Worker tests.

All tests are hermetic: no real Redis, no real DB, no real YFinance, no network.

Run:
    docker compose exec api pytest tests/test_price_refresh_worker.py -v
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.run(coro)


def _mock_pool():
    return MagicMock()


# ── _handle_financial_ingestion — price_refresh dispatch ─────────────────────

@patch("worker_entrypoint.refresh_prices", new_callable=AsyncMock)
def test_handle_price_refresh_calls_service(mock_refresh):
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

    mock_refresh.assert_called_once_with(pool, PRICE_BACKFILL_SYMBOLS, PRICE_BACKFILL_DEFAULT_DAYS, trigger="scheduled")


@patch("worker_entrypoint.refresh_prices", new_callable=AsyncMock)
def test_handle_price_refresh_logs_summary(mock_refresh, caplog):
    from worker_entrypoint import _handle_financial_ingestion

    mock_refresh.return_value = {
        "results": [],
        "total_symbols": 2,
        "succeeded": 2,
        "failed": 0,
    }

    import logging
    with caplog.at_level(logging.INFO):
        _run(_handle_financial_ingestion(_mock_pool(), {"type": "price_refresh"}))

    log_text = " ".join(caplog.messages)
    assert "Price refresh complete" in log_text
    assert "2 succeeded" in log_text
    assert "0 failed" in log_text


@patch("worker_entrypoint.refresh_prices", new_callable=AsyncMock)
def test_handle_price_refresh_service_exception_does_not_crash_worker(mock_refresh):
    from worker_entrypoint import _handle_financial_ingestion

    mock_refresh.side_effect = RuntimeError("boom")

    # Must not propagate — the outer try/except in _handle_financial_ingestion absorbs it.
    _run(_handle_financial_ingestion(_mock_pool(), {"type": "price_refresh"}))


# ── _enqueue_scheduled_financial_tasks ───────────────────────────────────────

def test_enqueue_scheduled_tasks_includes_price_refresh():
    from worker_entrypoint import _enqueue_scheduled_financial_tasks

    mock_redis = MagicMock()
    mock_redis.rpush = AsyncMock()

    _run(_enqueue_scheduled_financial_tasks(mock_redis))

    assert mock_redis.rpush.call_count == 4

    pushed_payloads = [
        json.loads(call.args[1])
        for call in mock_redis.rpush.call_args_list
    ]
    task_types = {p["type"] for p in pushed_payloads}

    assert "price_refresh" in task_types
    assert "fx_ingestion" in task_types
    assert "holdings_ingestion" in task_types
    assert "proactive_insights" in task_types


def test_enqueue_scheduled_tasks_fx_is_incremental():
    from worker_entrypoint import _enqueue_scheduled_financial_tasks

    mock_redis = MagicMock()
    mock_redis.rpush = AsyncMock()

    _run(_enqueue_scheduled_financial_tasks(mock_redis))

    pushed_payloads = [
        json.loads(call.args[1])
        for call in mock_redis.rpush.call_args_list
    ]
    fx_task = next(p for p in pushed_payloads if p["type"] == "fx_ingestion")
    assert fx_task.get("incremental") is True
