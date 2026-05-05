"""
financial/services/price_refresh_service.py — Price freshness checks and refresh logic.

Used by:
  GET  /financial/prices/freshness          (admin status endpoint)
  POST /financial/ingest/prices/backfill    (delegates refresh loop here)
  Future: worker_entrypoint.py price_refresh task
"""

from datetime import date, datetime, timedelta

import asyncpg

from core.config import PRICE_STALENESS_DAYS
from core.logger import get_logger
from financial.crud import get_latest_price_dates_bulk, insert_ingestion_run
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
    trigger: str = "manual",
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
    started_at = datetime.utcnow()

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

    total_symbols = len(normalized)
    rows_ingested = sum((r.get("rows_ingested") or 0) for r in results)

    if failed == 0:
        status = "success"
    elif failed == total_symbols:
        status = "failed"
    else:
        status = "partial"

    error_parts = [
        f"{r['symbol']}: {r['error']}"
        for r in results
        if r.get("error")
    ]
    raw_summary = "; ".join(error_parts)
    error_summary = raw_summary[:500] if raw_summary else None

    finished_at = datetime.utcnow()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    try:
        await insert_ingestion_run(
            pool=pool,
            run_type="price_backfill" if trigger == "manual" else "price_refresh",
            trigger_type=trigger,
            provider="yfinance",
            symbols_count=total_symbols,
            succeeded=succeeded,
            failed=failed,
            rows_ingested=rows_ingested,
            status=status,
            error_summary=error_summary,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.error(f"Failed to record ingestion run: {exc}")

    return {
        "results": results,
        "total_symbols": total_symbols,
        "succeeded": succeeded,
        "failed": failed,
    }
