"""
macro.py — Macroeconomic data provider (FRED API).

FRED (Federal Reserve Economic Data) publishes thousands of economic
indicator series. Each series has an ID like "FEDFUNDS" or "CPIAUCSL".

API endpoint:
  https://api.stlouisfed.org/fred/series/observations
  ?series_id=FEDFUNDS&api_key=...&file_type=json
  &observation_start=YYYY-MM-DD&observation_end=YYYY-MM-DD

Design notes:
  - Unlike BOI which returns all currencies at once, FRED is
    queried one series at a time via the series_id parameter.
  - FRED returns values as STRINGS (e.g. "1065.9"), not numbers.
  - Missing data is marked with "." (literal dot) — we skip those.
  - Requires an API key (free, 120 req/min limit — plenty for us).
  - Incremental: fetches only dates after latest stored.
"""

import httpx
import asyncpg
import asyncpg

from financial.crud import upsert_macro_series, get_last_macro_date
from core.config import FRED_API_KEY
from core.logger import get_logger
from financial.providers.base import BaseProvider
from financial.models import MacroSeriesRow
from datetime import date, timedelta

logger = get_logger(__name__)

# ── FRED API base URL ──
_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


class FREDProvider(BaseProvider):
    """Fetches macroeconomic series data from FRED (JSON)."""

    provider_name = "fred"

    def __init__(
        self,
        series_id: str,
        start: date | None = None,
        end: date | None = None,
    ):
        # ─── Why store series_id on the instance? ───
        # Unlike BOI (which fetches ALL currencies in one call),
        # FRED is called per-series. Each instance handles one series.
        self.series_id = series_id.upper()  # FRED IDs are uppercase by convention
        self.start = start or date(2020, 1, 1)
        self.end = end or date.today()

    async def fetch_raw(self, **kwargs) -> dict:
        """
        Call the FRED API and return the raw JSON response.

        Key params:
          - series_id: which economic series to fetch
          - file_type: "json" (default is XML — we don't want that)
          - observation_start/end: date range filter
          - api_key: required for all FRED requests
        """
        # ─── Fail fast if no API key ───
        # Better to raise a clear error here than get a cryptic
        # 401 from FRED and wonder what went wrong.
        if not FRED_API_KEY:
            raise ValueError(
                "FRED_API_KEY not set in environment. "
                "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
            )

        params = {
            "series_id": self.series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": self.start.isoformat(),
            "observation_end": self.end.isoformat(),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_FRED_URL, params=params)
            resp.raise_for_status()

        return resp.json()

    def normalize(self, raw_data: dict) -> list[dict]:
        """
        Parse FRED JSON into validated MacroSeriesRow dicts.

        FRED JSON structure:
        {
          "observations": [
            {"date": "2020-01-01", "value": "1.55"},
            {"date": "2020-02-01", "value": "1.58"},
            {"date": "2020-03-01", "value": "."},   ← missing data!
            ...
          ]
        }

        We need to handle:
        1. value="." → skip (FRED's way of saying "no data")
        2. value is a string → convert to float
        3. Validate each row through MacroSeriesRow (Pydantic)
        """
        observations = raw_data.get("observations", [])
        rows = []
        skipped = 0

        for obs in observations:
            value_str = obs.get("value", "")

            # ─── Skip missing data ───
            # FRED uses "." for missing observations. This is common
            # for series that haven't been released yet (e.g., GDP
            # for the current quarter) or discontinued series.
            if value_str == ".":
                skipped += 1
                continue

            try:
                row = MacroSeriesRow(
                    series_id=self.series_id,
                    date=obs["date"],
                    value=float(value_str),
                    source=self.provider_name,
                )
                rows.append(row.model_dump())
            except Exception as e:
                skipped += 1
                logger.warning(f"Skipped FRED row: {e}")

        if skipped:
            logger.info(
                f"FRED {self.series_id}: parsed {len(rows)}, skipped {skipped}"
            )

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """
        Upsert macro rows to the database (skip duplicates).

        ON CONFLICT DO NOTHING means:
        - If we already have FEDFUNDS for 2024-01-01 from "fred",
          we silently skip it instead of crashing.
        - This makes the entire pipeline idempotent — you can run
          it 10 times and get the same result.
        """
        return await upsert_macro_series(pool, rows)

    async def get_last_date(self) -> date | None:
        """
        Check the latest date we have for this specific series.

        Why filter by BOTH series_id AND source?
        Because the same series could theoretically come from
        different providers in the future. We only want to check
        what THIS provider has already stored.
        """
        return await get_last_macro_date(self.series_id, self.provider_name)

    async def ingest_incremental(self) -> dict:
        """
        Smart ingestion: only fetch data newer than what we already have.

        Flow:
        1. Check DB for the latest date for this series
        2. If we have data, set start = last_date + 1 day
        3. If start > end (today), we're already up to date
        4. Otherwise, run the normal ingest pipeline

        This saves API calls and avoids re-processing old data.
        """
        last = await self.get_last_date()
        if last:
            self.start = last + timedelta(days=1)
            if self.start > self.end:
                return {
                    "provider": self.provider_name,
                    "series_id": self.series_id,
                    "status": "up_to_date",
                    "rows_ingested": 0,
                }
        result = await self.ingest()
        result["series_id"] = self.series_id
        return result
