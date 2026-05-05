"""
financial/routes/prices.py — Stock/ETF price ingestion endpoints.
POST /financial/ingest/prices          — single-symbol Stooq ingest
POST /financial/ingest/prices/backfill — multi-symbol YFinance backfill (admin/internal)
"""

import json
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool, require_scope

from core.logger import get_logger
from financial.providers.price import StooqProvider, YFinancePriceProvider
from financial.schemas import PriceIngestRequest, PriceBackfillRequest
from core.config import PRICE_BACKFILL_SYMBOLS, PRICE_BACKFILL_DEFAULT_DAYS

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - prices"])


@router.post("/ingest/prices")
async def ingest_prices(
    request: PriceIngestRequest,
    pool: asyncpg.Pool = Depends(get_db_pool),
    _: bool = Depends(require_scope("admin")),
):
    """
    Ingest daily price data for a symbol from Stooq.

    - If incremental=True (default), only fetches data after the last stored date.
    - If incremental=False, fetches the full date range.
    """
    provider = StooqProvider(
        symbol=request.symbol,
        start=request.start_date,
        end=request.end_date,
    )

    try:
        if request.incremental:
            result = await provider.ingest_incremental(pool)
        else:
            result = await provider.ingest(pool)
    except httpx.HTTPStatusError as e:
        logger.error(json.dumps({
            "event": "price_ingestion_failed",
            "symbol": request.symbol,
            "status_code": e.response.status_code,
        }))
        raise HTTPException(
            status_code=502,
            detail=f"Stooq returned {e.response.status_code} for symbol {request.symbol}"
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "price_ingestion_error",
            "symbol": request.symbol,
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=str(e))

    result["symbol"] = request.symbol
    return result


@router.post("/ingest/prices/backfill")
async def backfill_prices(
    request: PriceBackfillRequest,
    pool: asyncpg.Pool = Depends(get_db_pool),
    _: bool = Depends(require_scope("admin")),
):
    """
    Backfill historical daily prices for a list of symbols via Yahoo Finance.

    Uses YFinancePriceProvider (no API key required). Calls ingest_incremental
    per symbol so already-stored rows are skipped. Per-symbol failures are
    caught and reported without stopping the remaining batch.

    NOTE: This is an internal/admin route. It should be protected by an
    API-key or role check in the cross-cutting auth phase.
    """
    symbols = [s.strip().upper() for s in request.symbols] if request.symbols is not None else PRICE_BACKFILL_SYMBOLS
    days = request.days if request.days is not None else PRICE_BACKFILL_DEFAULT_DAYS
    start_date = date.today() - timedelta(days=days)

    results = []
    succeeded = 0
    failed = 0

    for symbol in symbols:
        try:
            provider = YFinancePriceProvider(symbol=symbol, start=start_date)
            outcome = await provider.ingest_incremental(pool)
            results.append({
                "symbol": symbol,
                "status": "success",
                "rows_ingested": outcome.get("rows_ingested"),
                "error": None,
            })
            succeeded += 1
        except Exception as exc:
            logger.error(json.dumps({
                "event": "price_backfill_symbol_failed",
                "symbol": symbol,
                "error": str(exc),
            }))
            results.append({
                "symbol": symbol,
                "status": "failed",
                "rows_ingested": None,
                "error": str(exc),
            })
            failed += 1

    return {
        "results": results,
        "total_symbols": len(symbols),
        "succeeded": succeeded,
        "failed": failed,
    }
