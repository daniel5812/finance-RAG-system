"""
financial/routes/prices.py — Stock/ETF price ingestion endpoint.
POST /financial/ingest/prices
"""

import json
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from financial.providers.price import StooqProvider
from financial.schemas import PriceIngestRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - prices"])


@router.post("/ingest/prices")
async def ingest_prices(
    request: PriceIngestRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
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
