"""
base.py — Abstract base class for all data providers.

Every provider follows the same pipeline:
    fetch_raw → normalize → validate → store → log

This enforces consistency. When you add a new data source,
you implement 3 methods and get retry, logging, and provenance for free.
"""

import json
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
import asyncpg

from financial.crud import insert_raw_ingestion_log
from core.logger import get_logger

logger = get_logger(__name__)


class BaseProvider(ABC):
    """Base class for all financial data providers."""

    # Subclasses MUST set this (e.g. "stooq", "fred", "boi")
    provider_name: str = "unknown"

    @abstractmethod
    async def fetch_raw(self, **kwargs) -> str | dict | list:
        """
        Fetch raw data from the external source.
        Returns the raw response (CSV string, JSON dict, etc.)
        """
        ...

    @abstractmethod
    def normalize(self, raw_data) -> list[dict]:
        """
        Transform raw data into a list of normalized row dicts.
        Each dict must match the target database table columns.
        """
        ...

    @abstractmethod
    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """
        Write normalized rows to the database.
        Returns the number of rows successfully inserted.
        """
        ...

    # ── Main Pipeline ──

    async def ingest(self, pool: asyncpg.Pool, **kwargs) -> dict:
        """
        Full ingestion pipeline:
        1. Fetch raw data from source
        2. Log raw response (provenance)
        3. Normalize into structured rows
        4. Store in database
        5. Return summary
        """
        t0 = datetime.now()

        try:
            # Step 1: Fetch
            raw = await self.fetch_raw(**kwargs)

            # Step 2: Normalize
            rows = self.normalize(raw)

            if not rows:
                await self._log_raw(raw, kwargs, status="empty", rows_ingested=0)
                return {
                    "provider": self.provider_name,
                    "status": "empty",
                    "rows_ingested": 0,
                }

            # Step 3: Store
            count = await self.store(pool, rows)

            # Step 4: Log success
            await self._log_raw(pool, raw, kwargs, status="success", rows_ingested=count)

            elapsed = (datetime.now() - t0).total_seconds()
            logger.info(json.dumps({
                "event": "ingestion_complete",
                "provider": self.provider_name,
                "rows": count,
                "elapsed_s": round(elapsed, 2),
            }))

            return {
                "provider": self.provider_name,
                "status": "success",
                "rows_ingested": count,
                "elapsed_s": round(elapsed, 2),
            }

        except Exception as e:
            await self._log_raw(
                pool=pool,
                raw_data=None,
                params=kwargs,
                status="error",
                error_message=traceback.format_exc(),
            )
            logger.error(json.dumps({
                "event": "ingestion_failed",
                "provider": self.provider_name,
                "error": str(e),
            }))
            raise

    # ── Provenance Logging ──

    async def _log_raw(
        self,
        pool: asyncpg.Pool,
        raw_data,
        params: dict,
        status: str = "success",
        rows_ingested: int = 0,
        error_message: str | None = None,
    ):
        """Log the raw response to raw_ingestion_log for traceability."""
        # Truncate raw_data if it's huge (keep first 10KB)
        raw_str = None
        if raw_data is not None:
            raw_str = str(raw_data)[:10_000]

        await insert_raw_ingestion_log(
            pool=pool,
            provider=self.provider_name,
            request_params=json.dumps(params, default=str),
            raw_response=raw_str,
            status=status,
            rows_ingested=rows_ingested,
            error_message=error_message,
        )
