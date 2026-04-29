"""
Tests for document aggregation service (Step 5D).

Covers:
- Full aggregation with multiple documents
- NULL handling (missing fields don't break aggregation)
- owner_id isolation: user A's data not visible to user B
- Empty user (no documents) returns zeros/nulls
- Multiple account types aggregated correctly
- Holdings summary
- Document coverage
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock


# ── Aggregation: full extraction ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregate_user_documents_with_data():
    """Full aggregation: multiple financial statements with exposures."""
    from documents.service import aggregate_user_documents

    # Mock data: 2 documents
    mock_fin_stmt_row = {
        "total_assets": 285000.0 + 150000.0,  # 2 docs
        "accounts_count": 2,  # provider1:acct1, provider2:acct2
        "avg_equity_pct": (65.5 + 45.0) / 2,  # 55.25
        "avg_fx_pct": (12.3 + 8.0) / 2,  # 10.15
        "latest_report_date": date(2024, 12, 31),
    }

    mock_type_breakdown = [
        {"account_type": "gemel", "count": 1},
        {"account_type": "hishtalmut", "count": 1},
    ]

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_fin_stmt_row)
    pool.fetch = AsyncMock(return_value=mock_type_breakdown)

    result = await aggregate_user_documents(pool, "user-1")

    assert result["total_assets_from_docs"] == 435000.0
    assert result["accounts_detected"] == 2
    assert result["account_types_breakdown"] == {"gemel": 1, "hishtalmut": 1}
    assert result["avg_equity_exposure"] == pytest.approx(55.25)
    assert result["avg_fx_exposure"] == pytest.approx(10.15)
    assert result["latest_report_date"] == date(2024, 12, 31)


@pytest.mark.asyncio
async def test_aggregate_user_documents_no_data():
    """Empty user (no documents): returns zeros and nulls."""
    from documents.service import aggregate_user_documents

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])

    result = await aggregate_user_documents(pool, "user-empty")

    assert result["total_assets_from_docs"] == 0.0
    assert result["accounts_detected"] == 0
    assert result["account_types_breakdown"] == {}
    assert result["avg_equity_exposure"] is None
    assert result["avg_fx_exposure"] is None
    assert result["latest_report_date"] is None


# ── NULL handling ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregate_handles_null_exposures():
    """Documents with NULL exposure values don't break aggregation."""
    from documents.service import aggregate_user_documents

    # One doc has equity exposure, another doesn't
    mock_fin_stmt_row = {
        "total_assets": 200000.0,
        "accounts_count": 1,
        "avg_equity_pct": 65.5,  # AVG ignores NULLs
        "avg_fx_pct": None,  # No FX exposure documents
        "latest_report_date": date(2024, 12, 31),
    }

    mock_type_breakdown = [{"account_type": "gemel", "count": 1}]

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_fin_stmt_row)
    pool.fetch = AsyncMock(return_value=mock_type_breakdown)

    result = await aggregate_user_documents(pool, "user-1")

    assert result["total_assets_from_docs"] == 200000.0
    assert result["avg_equity_exposure"] == pytest.approx(65.5)
    assert result["avg_fx_exposure"] is None


@pytest.mark.asyncio
async def test_aggregate_handles_null_balances():
    """Documents with NULL ending_balance (partial extraction) are ignored."""
    from documents.service import aggregate_user_documents

    # 2 docs: one with balance, one without
    mock_fin_stmt_row = {
        "total_assets": 150000.0,  # Only 1 doc with balance
        "accounts_count": 2,
        "avg_equity_pct": 50.0,
        "avg_fx_pct": 10.0,
        "latest_report_date": date(2024, 12, 31),
    }

    mock_type_breakdown = [{"account_type": "pension", "count": 2}]

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_fin_stmt_row)
    pool.fetch = AsyncMock(return_value=mock_type_breakdown)

    result = await aggregate_user_documents(pool, "user-1")

    assert result["total_assets_from_docs"] == 150000.0
    assert result["accounts_detected"] == 2


# ── owner_id isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aggregate_owner_id_isolation():
    """User A's aggregation doesn't include User B's data."""
    from documents.service import aggregate_user_documents

    pool = MagicMock()

    # User A's data
    mock_user_a = {
        "total_assets": 500000.0,
        "accounts_count": 3,
        "avg_equity_pct": 60.0,
        "avg_fx_pct": 10.0,
        "latest_report_date": date(2024, 12, 31),
    }

    pool.fetchrow = AsyncMock(return_value=mock_user_a)
    pool.fetch = AsyncMock(return_value=[{"account_type": "gemel", "count": 3}])

    result_a = await aggregate_user_documents(pool, "user-a")
    assert result_a["total_assets_from_docs"] == 500000.0

    # Verify owner_id was passed to query
    pool.fetchrow.assert_called()
    call_args = pool.fetchrow.call_args
    assert "user-a" in call_args.args


# ── Multiple account types ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_types_breakdown_multiple_types():
    """Breakdown correctly counts each account type."""
    from documents.service import aggregate_user_documents

    mock_fin_stmt_row = {
        "total_assets": 1000000.0,
        "accounts_count": 5,
        "avg_equity_pct": 50.0,
        "avg_fx_pct": 10.0,
        "latest_report_date": date(2024, 12, 31),
    }

    mock_type_breakdown = [
        {"account_type": "gemel", "count": 2},
        {"account_type": "hishtalmut", "count": 2},
        {"account_type": "pension", "count": 1},
    ]

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_fin_stmt_row)
    pool.fetch = AsyncMock(return_value=mock_type_breakdown)

    result = await aggregate_user_documents(pool, "user-1")

    assert result["account_types_breakdown"]["gemel"] == 2
    assert result["account_types_breakdown"]["hishtalmut"] == 2
    assert result["account_types_breakdown"]["pension"] == 1


@pytest.mark.asyncio
async def test_account_types_empty_when_no_types():
    """No account types extracted → empty dict."""
    from documents.service import aggregate_user_documents

    mock_fin_stmt_row = {
        "total_assets": 100000.0,
        "accounts_count": 0,
        "avg_equity_pct": 50.0,
        "avg_fx_pct": 10.0,
        "latest_report_date": date(2024, 12, 31),
    }

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_fin_stmt_row)
    pool.fetch = AsyncMock(return_value=[])

    result = await aggregate_user_documents(pool, "user-1")

    assert result["account_types_breakdown"] == {}


# ── Holdings summary ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_holdings_summary_with_data():
    """Holdings aggregation: counts tickers, confidence levels."""
    from documents.service import get_user_holdings_summary

    mock_result = {
        "ticker_count": 15,
        "high_confidence_count": 12,
        "qty_count": 14,
        "docs_with_holdings": 3,
    }

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_result)

    result = await get_user_holdings_summary(pool, "user-1")

    assert result["ticker_count"] == 15
    assert result["high_confidence_count"] == 12
    assert result["tickers_with_quantity"] == 14
    assert result["total_documents_with_holdings"] == 3


@pytest.mark.asyncio
async def test_holdings_summary_no_holdings():
    """User with no holdings extractions."""
    from documents.service import get_user_holdings_summary

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)

    result = await get_user_holdings_summary(pool, "user-empty")

    assert result["ticker_count"] == 0
    assert result["high_confidence_count"] == 0
    assert result["tickers_with_quantity"] == 0
    assert result["total_documents_with_holdings"] == 0


# ── Document coverage ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_document_coverage_mixed():
    """Coverage: some docs have holdings, some have financial statements."""
    from documents.service import get_document_coverage

    mock_result = {
        "holdings_docs": 2,
        "fin_stmt_docs": 3,
        "total_docs": 5,
    }

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=mock_result)

    result = await get_document_coverage(pool, "user-1")

    assert result["docs_with_holdings"] == 2
    assert result["docs_with_financial_statements"] == 3
    assert result["total_completed_documents"] == 5


@pytest.mark.asyncio
async def test_document_coverage_empty():
    """Coverage for user with no documents."""
    from documents.service import get_document_coverage

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)

    result = await get_document_coverage(pool, "user-empty")

    assert result["docs_with_holdings"] == 0
    assert result["docs_with_financial_statements"] == 0
    assert result["total_completed_documents"] == 0
