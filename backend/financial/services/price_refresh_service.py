"""
financial/services/price_refresh_service.py — Price freshness checks and refresh logic.

Used by:
  GET  /financial/prices/freshness          (admin status endpoint)
  POST /financial/ingest/prices/backfill    (delegates refresh loop here)
  Future: worker_entrypoint.py price_refresh task
"""

from datetime import date, timedelta

import asyncpg

from core.config import PRICE_STALENESS_DAYS
from core.logger import get_logger
from financial.crud import get_latest_price_dates_bulk
from financial.providers.price import YFinancePriceProvider

logger = get_logger(__name__)


async def get_price_freshness(
    pool: asyncpg.Pool,
    symbols: list[str],
) -> list[dict]:
    """
    Return per-symbol freshness status from DB only. No provider calls.

    Each dict: {symbol, latest_date (ISO str or None), status, stale}
    status values: "fresh" | "stale" | "missing"
    """
    if not symbols:
        return []

    normalized = [s.strip().upper() for s in symbols if s and s.strip()]
    if not normalized:
        return []

    latest_dates = await get_latest_price_dates_bulk(pool, normalized)

    today = date.today()
    stale_cutoff = today - timedelta(days=PRICE_STALENESS_DAYS)

    result = []
    for symbol in normalized:
        latest = latest_dates.get(symbol)

        if latest is None:
            result.append({
                "symbol": symbol,
                "latest_date": None,
                "status": "missing",
                "stale": True,
            })
        elif latest < stale_cutoff:
            result.append({
                "symbol": symbol,
                "latest_date": latest.isoformat(),
                "status": "stale",
                "stale": True,
            })
        else:
            result.append({
                "symbol": symbol,
                "latest_date": latest.isoformat(),
                "status": "fresh",
                "stale": False,
            })

    return result


async def refresh_prices(
    pool: asyncpg.Pool,
    symbols: list[str],
    days: int,
) -> dict:
    """
    Refresh prices for the given symbols via YFinancePriceProvider.ingest_incremental.

    Per-symbol failures are isolated — one failure does not stop the rest.
    Return shape is identical to the original backfill route response.
    """
    normalized = [s.strip().upper() for s in symbols if s and s.strip()]
    start_date = date.today() - timedelta(days=days)

    results = []
    succeeded = 0
    failed = 0

    for symbol in normalized:
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
            logger.error(f"Price refresh failed for {symbol}: {exc}")
            results.append({
                "symbol": symbol,
                "status": "failed",
                "rows_ingested": None,
                "error": str(exc),
            })
            failed += 1

    return {
        "results": results,
        "total_symbols": len(normalized),
        "succeeded": succeeded,
        "failed": failed,
    }
