"""
fx.py — FX rate provider (Bank of Israel SDMX API).

The BOI publishes daily exchange rates for ILS against major currencies.
URL pattern:
  https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0
  ?startperiod=YYYY-MM-DD&endperiod=YYYY-MM-DD&format=csv

Design notes:
  - Returns CSV with all currencies in one response
  - We filter for DATA_TYPE="OF00" (actual rates, not % changes)
  - UNIT_MULT column handles per-100 rates (e.g. JPY)
  - Rates are stored as "1 unit of X = ? ILS"
  - Incremental: fetches only dates after latest stored
"""

import csv
import io
from datetime import date, timedelta

import httpx
import asyncpg

from core.logger import get_logger
from financial.crud import upsert_fx_rates, get_last_fx_date
from financial.providers.base import BaseProvider
from financial.models import FXRateRow

logger = get_logger(__name__)

# Only ingest currencies we actually care about
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CHF", "JPY", "AUD", "CAD"}

_BOI_URL = (
    "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/"
    "BOI.STATISTICS/EXR/1.0"
)


class BOIProvider(BaseProvider):
    """Fetches daily FX rates from Bank of Israel (CSV)."""

    provider_name = "boi"

    def __init__(self, start: date | None = None, end: date | None = None):
        self.start = start or date(2020, 1, 1)
        self.end = end or date.today()

    async def fetch_raw(self, **kwargs) -> str:
        """Download CSV from BOI SDMX API. Returns raw CSV string."""
        params = {
            "startperiod": self.start.isoformat(),
            "endperiod": self.end.isoformat(),
            "format": "csv",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_BOI_URL, params=params)
            
            # The BOI SDMX API returns 404 when there is no data for the requested dates
            # (e.g., weekends or holidays). We treat this gracefully.
            if resp.status_code == 404:
                return "DATA_TYPE,UNIT_MEASURE,BASE_CURRENCY,OBS_VALUE,UNIT_MULT,TIME_PERIOD\n"
                
            resp.raise_for_status()

        return resp.text

    def normalize(self, raw_data: str) -> list[dict]:
        """
        Parse BOI CSV into validated FXRateRow dicts.

        Filter logic:
          - DATA_TYPE must be "OF00" (actual exchange rate)
          - UNIT_MEASURE must be "ILS" (not percentage or index)
          - BASE_CURRENCY must be in our supported set

        UNIT_MULT handling:
          - "0" → rate is per 1 unit (most currencies)
          - "2" → rate is per 100 units (JPY)
          We normalize so the stored rate always means "1 unit = ? ILS".
        """
        reader = csv.DictReader(io.StringIO(raw_data))
        rows = []
        skipped = 0

        for line in reader:
            # Only keep actual exchange rates for supported currencies
            if line.get("DATA_TYPE") != "OF00":
                continue
            if line.get("UNIT_MEASURE") != "ILS":
                continue

            base_currency = line.get("BASE_CURRENCY", "")
            if base_currency not in SUPPORTED_CURRENCIES:
                continue

            try:
                raw_rate = float(line["OBS_VALUE"])
                unit_mult = int(line.get("UNIT_MULT", "0"))

                # Normalize: if UNIT_MULT=2, rate is per 100 units → divide
                if unit_mult > 0:
                    rate = raw_rate / (10 ** unit_mult)
                else:
                    rate = raw_rate

                row = FXRateRow(
                    base_currency=base_currency,
                    quote_currency="ILS",
                    date=line["TIME_PERIOD"],
                    rate=rate,
                    source=self.provider_name,
                )
                rows.append(row.model_dump())
            except Exception as e:
                skipped += 1
                logger.warning(f"Skipped FX row: {e}")

        if skipped:
            logger.info(f"BOI FX: parsed {len(rows)}, skipped {skipped}")

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """Upsert FX rows to the database (skip duplicates)."""
        return await upsert_fx_rates(pool, rows)

    async def get_last_date(self, pool: asyncpg.Pool) -> date | None:
        """Check the latest date we have for BOI rates."""
        return await get_last_fx_date(pool, self.provider_name)

    async def ingest_incremental(self, pool: asyncpg.Pool) -> dict:
        """Only fetch data newer than what we already have."""
        last = await self.get_last_date(pool)
        if last:
            self.start = last + timedelta(days=1)
            if self.start > self.end:
                return {
                    "provider": self.provider_name,
                    "status": "up_to_date",
                    "rows_ingested": 0,
                }
        return await self.ingest(pool)
