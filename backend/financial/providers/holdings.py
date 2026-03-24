"""
holdings.py — ETF holdings provider (batch pipeline).

Unlike our other providers which handle one item per request,
this provider processes MULTIPLE ETFs in a single run:

  for each active ETF in etf_sources:
      fetch → hash → compare → validate → store → update tracker

Design notes:
  - Hash-based change detection (SHA256 of raw data)
  - One ETF failing does NOT stop others
  - Structured summary: {processed, updated, skipped, failed}
  - Integrates with Redis metrics
  - Client is injected (replaceable)
"""

import hashlib
import json
from datetime import date, datetime

from core.logger import get_logger
from financial.crud import get_active_etfs, upsert_etf_holdings, update_etf_tracker
from financial.models import ETFHoldingRow
from financial.clients.yahoo import YahooHoldingsClient
import asyncpg

logger = get_logger(__name__)


class HoldingsProvider:
    """
    Batch ETF holdings ingestion with change detection.

    Why this doesn't extend BaseProvider:
    BaseProvider is designed for single-item pipelines
    (fetch_raw → normalize → store). Holdings needs a
    BATCH pipeline with per-ETF error isolation and
    hash-based skip logic. Different pattern, different base.
    """

    provider_name = "yahooquery"

    def __init__(self, client: YahooHoldingsClient | None = None):
        # ── Dependency injection ──
        # Passing the client in allows swapping it for testing
        # or for a different data source (Finnhub, SEC, etc.)
        self.client = client or YahooHoldingsClient()
        self.today = date.today()

    async def get_active_etfs(self, pool: asyncpg.Pool, symbols: list[str] | None = None) -> list[dict]:
        """
        Get the list of ETFs to process.

        If symbols is provided, filter to only those.
        Otherwise, fetch all ETFs with status='active' from etf_sources.
        """
        return await get_active_etfs(pool, symbols)

    def _compute_hash(self, raw_data: list[dict]) -> str:
        """
        SHA256 hash of the raw holdings data.

        Why hash?
        ETF holdings change maybe once a month. If we run
        ingestion weekly, most runs will find no changes.
        By comparing hashes, we skip the entire
        validate → store pipeline for unchanged data.
        """
        serialized = json.dumps(raw_data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def _process_one_etf(self, pool: asyncpg.Pool, etf_symbol: str, last_hash: str | None) -> dict:
        """
        Process a single ETF through the full pipeline.

        Returns a status dict:
          {"etf": "SPY", "status": "updated", "rows": 50}
          {"etf": "SPY", "status": "skipped"}
          {"etf": "SPY", "status": "failed", "error": "..."}
        """
        try:
            # Step 1: Fetch holdings from client
            raw_holdings = await self.client.get_holdings(etf_symbol)

            if not raw_holdings:
                return {"etf": etf_symbol, "status": "empty", "rows": 0}

            # Step 2: Compute hash — has anything changed?
            current_hash = self._compute_hash(raw_holdings)

            if current_hash == last_hash:
                # Nothing changed since last run — skip entirely
                return {"etf": etf_symbol, "status": "skipped"}

            # Step 3: Validate through Pydantic
            validated_rows = []
            skipped = 0

            for holding in raw_holdings:
                try:
                    row = ETFHoldingRow(
                        etf_symbol=etf_symbol,
                        holding_symbol=holding.get("holding_symbol", ""),
                        holding_name=holding.get("holding_name"),
                        weight=holding.get("weight", 0),
                        sector=holding.get("sector"),
                        country=holding.get("country"),
                        date=self.today,
                        source=self.provider_name,
                    )
                    validated_rows.append(row.model_dump())
                except Exception as e:
                    skipped += 1
                    logger.warning(f"Skipped holding in {etf_symbol}: {e}")

            if not validated_rows:
                return {"etf": etf_symbol, "status": "empty", "rows": 0}

            # Step 4: Bulk insert (skip duplicates)
            await self._store(pool, validated_rows)

            # Step 5: Update tracker (hash + timestamp)
            await self._update_tracker(pool, etf_symbol, current_hash)

            if skipped:
                logger.info(
                    f"Holdings {etf_symbol}: stored {len(validated_rows)}, "
                    f"skipped {skipped}"
                )

            return {
                "etf": etf_symbol,
                "status": "updated",
                "rows": len(validated_rows),
            }

        except Exception as e:
            logger.error(f"Failed to process {etf_symbol}: {e}")
            return {"etf": etf_symbol, "status": "failed", "error": str(e)}

    async def _store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """Bulk insert holdings — skip duplicates."""
        return await upsert_etf_holdings(pool, rows)

    async def _update_tracker(self, pool: asyncpg.Pool, etf_symbol: str, new_hash: str):
        """Update etf_sources with the new hash and timestamp."""
        await update_etf_tracker(pool, etf_symbol, new_hash)

    async def ingest(self, pool: asyncpg.Pool, symbols: list[str] | None = None) -> dict:
        """
        Main entry point: process all active ETFs.

        Pipeline:
        1. Get list of active ETFs from etf_sources
        2. Process each one independently (isolated failures)
        3. Collect results into structured summary

        Returns:
        {
          "provider": "yahooquery",
          "processed": 10,
          "updated": 3,
          "skipped": 6,
          "empty": 0,
          "failed": ["FAKE_ETF"],
          "details": [...]
        }
        """
        etfs = await self.get_active_etfs(pool, symbols)

        if not etfs:
            return {
                "provider": self.provider_name,
                "processed": 0,
                "updated": 0,
                "skipped": 0,
                "empty": 0,
                "failed": [],
                "details": [],
            }

        results = []
        for etf in etfs:
            result = await self._process_one_etf(
                pool,
                etf["etf_symbol"],
                etf.get("last_hash"),
            )
            results.append(result)
            logger.info(json.dumps({
                "event": "etf_processed",
                "etf": result["etf"],
                "status": result["status"],
            }))

        # Build summary
        updated = [r for r in results if r["status"] == "updated"]
        skipped = [r for r in results if r["status"] == "skipped"]
        empty = [r for r in results if r["status"] == "empty"]
        failed = [r for r in results if r["status"] == "failed"]

        summary = {
            "provider": self.provider_name,
            "processed": len(results),
            "updated": len(updated),
            "skipped": len(skipped),
            "empty": len(empty),
            "failed": [f["etf"] for f in failed],
            "details": results,
        }

        logger.info(json.dumps({
            "event": "holdings_ingestion_complete",
            "processed": summary["processed"],
            "updated": summary["updated"],
            "skipped": summary["skipped"],
            "failed": summary["failed"],
        }))

        return summary
