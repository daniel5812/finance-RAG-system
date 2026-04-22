"""
price.py — Price data provider (Stooq CSV).

Stooq provides free historical daily OHLCV data as CSV downloads.
URL pattern: https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d

Design notes:
  - Primary source for daily price data
  - Fetched via HTTP (no API key needed)
  - CSV parsed and normalized into the `prices` table schema
  - Incremental: checks last stored date and only fetches new data
"""

import csv
import io
from datetime import date, timedelta

import httpx
import asyncpg
import asyncpg

from core.logger import get_logger
from financial.crud import upsert_prices, get_last_price_date
from financial.providers.base import BaseProvider
from financial.models import PriceRow

logger = get_logger(__name__)

# Stooq expects dates as YYYYMMDD
_fmt = "%Y%m%d"


class StooqProvider(BaseProvider):
    """Fetches daily OHLCV data from Stooq (CSV)."""

    provider_name = "stooq"

    def __init__(self, symbol: str, start: date | None = None, end: date | None = None):
        self.symbol = symbol.upper()
        self.start = start or date(2020, 1, 1)
        self.end = end or date.today()

    async def fetch_raw(self, **kwargs) -> str:
        """Download CSV from Stooq. Returns raw CSV string."""
        url = (
            f"https://stooq.com/q/d/l/"
            f"?s={self.symbol}&d1={self.start.strftime(_fmt)}"
            f"&d2={self.end.strftime(_fmt)}&i=d"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return resp.text

    def normalize(self, raw_data: str) -> list[dict]:
        """Parse CSV into validated PriceRow dicts."""
        reader = csv.DictReader(io.StringIO(raw_data))
        rows = []
        skipped = 0

        for line in reader:
            try:
                row = PriceRow(
                    symbol=self.symbol,
                    date=line["Date"],
                    open=_safe_float(line.get("Open")),
                    high=_safe_float(line.get("High")),
                    low=_safe_float(line.get("Low")),
                    close=float(line["Close"]),
                    volume=_safe_int(line.get("Volume")),
                    currency="USD",
                    source=self.provider_name,
                )
                rows.append(row.model_dump())
            except Exception as e:
                skipped += 1
                logger.warning(f"Skipped row: {e}")

        if skipped:
            logger.info(f"Stooq {self.symbol}: parsed {len(rows)}, skipped {skipped}")

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """Upsert price rows to the database (skip duplicates)."""
        return await upsert_prices(pool, rows)

    async def get_last_date(self) -> date | None:
        """Check the latest date we have for this symbol (for incremental updates)."""
        return await get_last_price_date(self.symbol, self.provider_name)

    async def ingest_incremental(self) -> dict:
        """Only fetch data newer than what we already have."""
        last = await self.get_last_date()
        if last:
            self.start = last + timedelta(days=1)
            if self.start > self.end:
                return {
                    "provider": self.provider_name,
                    "symbol": self.symbol,
                    "status": "up_to_date",
                    "rows_ingested": 0,
                }
        return await self.ingest()


# ── Helpers ──

def _safe_float(val: str | None) -> float | None:
    if val is None or val.strip() == "":
        return None
    return float(val)


def _safe_int(val: str | None) -> int | None:
    if val is None or val.strip() == "":
        return None
    return int(float(val))
