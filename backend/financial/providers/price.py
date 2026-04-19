"""
price.py — Price data provider (yfinance).

yfinance provides free historical daily OHLCV data for US and international stocks.
No API key or authentication required.

Design notes:
  - Primary source for daily price data
  - Fetched via yfinance library (HTTP under the hood)
  - DataFrame converted to CSV, normalized into the `prices` table schema
  - Incremental: checks last stored date and only fetches new data
"""

import csv
import io
from datetime import date, timedelta

import yfinance as yf
import asyncpg

from core.logger import get_logger
from financial.crud import upsert_prices, get_last_price_date
from financial.providers.base import BaseProvider
from financial.models import PriceRow

logger = get_logger(__name__)


class StooqProvider(BaseProvider):
    """Fetches daily OHLCV data from yfinance."""

    provider_name = "yfinance"

    def __init__(self, symbol: str, start: date | None = None, end: date | None = None):
        self.symbol = symbol.upper()
        self.start = start or date(2020, 1, 1)
        self.end = end or date.today()

    async def fetch_raw(self, **kwargs) -> str:
        """Download historical price data from yfinance. Returns raw CSV string."""
        logger.info(f"[DEBUG] Fetching {self.symbol} from {self.start} to {self.end} via yfinance")

        try:
            ticker = yf.Ticker(self.symbol)
            df = ticker.history(start=self.start, end=self.end)

            if df.empty:
                logger.warning(f"[DEBUG] yfinance returned empty data for {self.symbol}")
                return "Date,Open,High,Low,Close,Volume\n"

            # Reset index to make date a column
            df = df.reset_index()

            # Select columns in the order normalize() expects
            df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]

            # Convert to CSV string
            csv_string = df.to_csv(index=False)

            logger.info(f"[DEBUG] yfinance response length: {len(csv_string)}, first 300 chars: {csv_string[:300]}")

            return csv_string
        except Exception as e:
            logger.error(f"[DEBUG] yfinance fetch failed for {self.symbol}: {e}")
            raise

    def normalize(self, raw_data: str) -> list[dict]:
        """Parse CSV into validated PriceRow dicts."""
        # DEBUG: Log raw response to diagnose empty CSV issue
        logger.info(f"[DEBUG] Raw response length: {len(raw_data)}, first 200 chars: {raw_data[:200]}")

        reader = csv.DictReader(io.StringIO(raw_data))
        rows = []
        skipped = 0

        # DEBUG: Capture fieldnames to verify CSV structure
        logger.info(f"[DEBUG] CSV fieldnames: {reader.fieldnames}")

        row_count = 0
        for line in reader:
            row_count += 1
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
                logger.warning(f"Skipped row {row_count}: {e}")

        # DEBUG: Log totals
        logger.info(f"[DEBUG] yfinance {self.symbol}: total_lines={row_count}, parsed={len(rows)}, skipped={skipped}")

        if skipped:
            logger.info(f"yfinance {self.symbol}: parsed {len(rows)}, skipped {skipped}")

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """Upsert price rows to the database (skip duplicates)."""
        return await upsert_prices(pool, rows)

    async def get_last_date(self) -> date | None:
        """Check the latest date we have for this symbol (for incremental updates)."""
        return await get_last_price_date(self.symbol, self.provider_name)

    async def ingest_incremental(self, pool: asyncpg.Pool) -> dict:
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
