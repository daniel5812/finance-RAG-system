"""
financial/routes/holdings.py — ETF holdings ingestion endpoint (background task).
POST /financial/ingest/holdings
"""

import json

from fastapi import APIRouter, BackgroundTasks, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from financial.providers.holdings import HoldingsProvider
from financial.schemas import HoldingsIngestRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - holdings"])


async def _run_holdings_ingestion(pool: asyncpg.Pool, symbols: list[str] | None = None):
    """
    Background task function.

    Why is this a separate function?
    BackgroundTasks.add_task() needs a callable. We define the
    actual work here, and the route just schedules it.
    Errors are logged but don't crash the API.
    """
    try:
        provider = HoldingsProvider()
        result = await provider.ingest(pool, symbols)
        logger.info(json.dumps({
            "event": "holdings_background_complete",
            "processed": result["processed"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "failed": result["failed"],
        }))
    except Exception as e:
        logger.error(json.dumps({
            "event": "holdings_background_error",
            "error": str(e),
        }))


@router.post("/ingest/holdings", status_code=202)
async def ingest_holdings(
    request: HoldingsIngestRequest,
    background_tasks: BackgroundTasks,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Trigger ETF holdings ingestion (runs in background).

    Returns 202 Accepted immediately. The actual ingestion
    continues asynchronously. Check logs or DB for results.

    - If etf_symbols is provided, only those ETFs are processed.
    - If omitted, all active ETFs from etf_sources are processed.
    """
    background_tasks.add_task(
        _run_holdings_ingestion,
        pool,
        request.etf_symbols,
    )

    return {
        "status": "accepted",
        "message": "Holdings ingestion started in background",
        "etf_symbols": request.etf_symbols or "all active",
    }
