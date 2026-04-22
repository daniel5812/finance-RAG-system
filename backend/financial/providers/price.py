"""
price.py — Price data providers (Stooq CSV + Yahoo Finance fallback).

Stooq now requires an API key (as of 2025). Use YFinancePriceProvider
for startup seeding and cases where no Stooq key is available.

Design notes:
  - StooqProvider: requires STOOQ_API_KEY in environment
  - YFinancePriceProvider: uses yfinance, no API key needed
  - Both normalize to the same prices table schema
  - Incremental: checks last stored date and only fetches new data
"""

import asyncio
import csv
import io
from datetime import date, timedelta

import httpx
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

    async def get_last_date(self, pool: asyncpg.Pool) -> date | None:
        """Check the latest date we have for this symbol (for incremental updates)."""
        return await get_last_price_date(pool, self.symbol, self.provider_name)

    async def ingest_incremental(self, pool: asyncpg.Pool) -> dict:
        """Only fetch data newer than what we already have."""
        last = await self.get_last_date(pool)
        if last:
            self.start = last + timedelta(days=1)
            if self.start > self.end:
                return {
                    "provider": self.provider_name,
                    "symbol": self.symbol,
                    "status": "up_to_date",
                    "rows_ingested": 0,
                }
        return await self.ingest(pool)


# ── Helpers ──

def _safe_float(val: str | None) -> float | None:
    if val is None or val.strip() == "":
        return None
    return float(val)


def _safe_int(val: str | None) -> int | None:
    if val is None or val.strip() == "":
        return None
    return int(float(val))


class YFinancePriceProvider(BaseProvider):
    """
    Fetches daily OHLCV data from Yahoo Finance (yfinance).
    No API key required. Used for startup seeding when Stooq key is unavailable.
    """

    provider_name = "yfinance"

    def __init__(self, symbol: str, start: date | None = None, end: date | None = None):
        self.symbol = symbol.upper()
        self.start = start or date(2020, 1, 1)
        self.end = end or date.today()

    async def fetch_raw(self, **kwargs):
        """Download OHLCV history via yfinance (sync call run in thread)."""
        import yfinance as yf

        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, yf.Ticker, self.symbol)
        hist = await loop.run_in_executor(
            None,
            lambda: ticker.history(
                start=self.start.isoformat(),
                end=self.end.isoformat(),
                interval="1d",
                auto_adjust=True,
            ),
        )
        return hist

    def normalize(self, raw_data) -> list[dict]:
        """Convert yfinance DataFrame into PriceRow dicts."""
        rows = []
        skipped = 0

        for idx, row in raw_data.iterrows():
            try:
                close_val = float(row["Close"])
                parsed = PriceRow(
                    symbol=self.symbol,
                    date=idx.date(),
                    open=_safe_float(str(row.get("Open", ""))),
                    high=_safe_float(str(row.get("High", ""))),
                    low=_safe_float(str(row.get("Low", ""))),
                    close=close_val,
                    volume=int(row["Volume"]) if row.get("Volume") else None,
                    currency="USD",
                    source=self.provider_name,
                )
                rows.append(parsed.model_dump())
            except Exception as e:
                skipped += 1
                logger.warning(f"YFinance {self.symbol} skipped row: {e}")

        if skipped:
            logger.info(f"YFinance {self.symbol}: parsed {len(rows)}, skipped {skipped}")

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """Upsert price rows to the database (skip duplicates)."""
        return await upsert_prices(pool, rows)

    async def get_last_date(self, pool: asyncpg.Pool) -> date | None:
        """Check the latest date we have for this symbol (for incremental updates)."""
        return await get_last_price_date(pool, self.symbol, self.provider_name)

    async def ingest_incremental(self, pool: asyncpg.Pool) -> dict:
        """Only fetch data newer than what we already have."""
        last = await self.get_last_date(pool)
        if last:
            self.start = last + timedelta(days=1)
            if self.start > self.end:
                return {
                    "provider": self.provider_name,
                    "symbol": self.symbol,
                    "status": "up_to_date",
                    "rows_ingested": 0,
                }
        return await self.ingest(pool)
