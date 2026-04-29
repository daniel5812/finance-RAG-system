"""
documents/service.py — Document aggregation service (Step 5D).

Read-only aggregation over extracted document data.
Computes financial signals from document holdings and statements.

Rules:
- owner_id isolation enforced at query level
- NULL values ignored in aggregations
- No portfolio updates
- No LLM
- Deterministic SQL only
"""

import asyncpg
from typing import Dict, Any, Optional
from datetime import date


async def aggregate_user_documents(
    pool: asyncpg.Pool,
    owner_id: str,
) -> Dict[str, Any]:
    """
    Aggregate all extracted document data for a user.

    Returns:
        Dict with keys:
        - total_assets_from_docs (float): SUM(ending_balance)
        - accounts_detected (int): COUNT(DISTINCT provider, account_number)
        - account_types_breakdown (dict): {account_type: count}
        - avg_equity_exposure (float): AVG(equity_exposure_pct)
        - avg_fx_exposure (float): AVG(fx_exposure_pct)
        - latest_report_date (date or None): MAX(report_date)

        Empty user (no documents) returns zeros and nulls.
    """

    # Aggregate financial statements data
    result = await pool.fetchrow(
        """
        SELECT
            COALESCE(SUM(ending_balance), 0)::float AS total_assets,
            COUNT(DISTINCT CASE WHEN account_number IS NOT NULL THEN provider || ':' || account_number END)::int AS accounts_count,
            AVG(equity_exposure_pct) AS avg_equity_pct,
            AVG(fx_exposure_pct) AS avg_fx_pct,
            MAX(report_date) AS latest_report_date
        FROM document_financial_statements
        WHERE owner_id = $1
        """,
        owner_id,
    )

    # Account type breakdown
    type_breakdown = await pool.fetch(
        """
        SELECT
            account_type,
            COUNT(*) AS count
        FROM document_financial_statements
        WHERE owner_id = $1
          AND account_type IS NOT NULL
        GROUP BY account_type
        ORDER BY count DESC
        """,
        owner_id,
    )

    account_types = {row["account_type"]: row["count"] for row in type_breakdown}

    return {
        "total_assets_from_docs": result["total_assets"] if result else 0.0,
        "accounts_detected": result["accounts_count"] if result else 0,
        "account_types_breakdown": account_types,
        "avg_equity_exposure": result["avg_equity_pct"] if result else None,
        "avg_fx_exposure": result["avg_fx_pct"] if result else None,
        "latest_report_date": result["latest_report_date"] if result else None,
    }


async def get_user_holdings_summary(
    pool: asyncpg.Pool,
    owner_id: str,
) -> Dict[str, Any]:
    """
    Aggregate holdings extracted from broker/portfolio statements.

    Returns:
        Dict with keys:
        - ticker_count (int): COUNT(DISTINCT ticker)
        - high_confidence_count (int): COUNT(*) where confidence='high'
        - tickers_with_quantity (int): COUNT(*) where quantity IS NOT NULL
        - total_documents_with_holdings (int): COUNT(DISTINCT document_id)
    """

    result = await pool.fetchrow(
        """
        SELECT
            COUNT(DISTINCT ticker)::int AS ticker_count,
            COUNT(CASE WHEN confidence = 'high' THEN 1 END)::int AS high_confidence_count,
            COUNT(CASE WHEN quantity IS NOT NULL THEN 1 END)::int AS qty_count,
            COUNT(DISTINCT document_id)::int AS docs_with_holdings
        FROM document_holdings
        WHERE owner_id = $1
        """,
        owner_id,
    )

    return {
        "ticker_count": result["ticker_count"] if result else 0,
        "high_confidence_count": result["high_confidence_count"] if result else 0,
        "tickers_with_quantity": result["qty_count"] if result else 0,
        "total_documents_with_holdings": result["docs_with_holdings"] if result else 0,
    }


async def get_document_coverage(
    pool: asyncpg.Pool,
    owner_id: str,
) -> Dict[str, Any]:
    """
    Coverage summary: how many documents extracted each signal type.

    Returns:
        Dict with keys:
        - docs_with_holdings (int): docs that had holdings extracted
        - docs_with_financial_statements (int): docs with financial statement extraction
        - total_completed_docs (int): total completed documents
    """

    counts = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(DISTINCT document_id) FROM document_holdings WHERE owner_id = $1)::int AS holdings_docs,
            (SELECT COUNT(DISTINCT document_id) FROM document_financial_statements WHERE owner_id = $1)::int AS fin_stmt_docs,
            (SELECT COUNT(*) FROM documents WHERE owner_id = $1 AND status = 'completed')::int AS total_docs
        """,
        owner_id,
    )

    return {
        "docs_with_holdings": counts["holdings_docs"] if counts else 0,
        "docs_with_financial_statements": counts["fin_stmt_docs"] if counts else 0,
        "total_completed_documents": counts["total_docs"] if counts else 0,
    }
