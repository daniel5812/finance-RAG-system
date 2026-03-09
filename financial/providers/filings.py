"""
filings.py — SEC EDGAR filing metadata provider.

The SEC publishes all company filings (10-K, 10-Q, 8-K, etc.) through
the EDGAR system. We use two endpoints:

1. Ticker → CIK lookup:
   https://www.sec.gov/files/company_tickers.json

2. Company submissions (filing history):
   https://data.sec.gov/submissions/CIK{padded_cik}.json

Design notes:
  - Unlike our other providers, EDGAR doesn't use an API key.
    Instead, SEC requires a User-Agent header with a contact email.
  - The response uses COLUMNAR arrays (parallel arrays for each field)
    rather than row-based data. We zip them together in normalize().
  - Dedup is on accession_number (globally unique per filing),
    not on (symbol, date) like prices/fx.
  - Rate limit: 10 req/sec (SEC enforces strictly). Fine for us
    since we only make 2 requests per ingestion.
"""

import json

import httpx
import asyncpg

from core.logger import get_logger
from financial.crud import upsert_filings
from financial.providers.base import BaseProvider
from financial.models import FilingRow

logger = get_logger(__name__)

# ── SEC API URLs ──
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# ── SEC requires this header on every request ──
# They use it to contact you if your code misbehaves.
# Without it, you get 403 Forbidden.
_HEADERS = {
    "User-Agent": "InvestEngine admin@investengine.local",
    "Accept-Encoding": "gzip, deflate",
}

# Only ingest these filing types by default
DEFAULT_FILING_TYPES = {"10-K", "10-Q"}


class EDGARProvider(BaseProvider):
    """Fetches SEC filing metadata for a given ticker."""

    provider_name = "sec_edgar"

    def __init__(
        self,
        ticker: str,
        filing_types: set[str] | None = None,
    ):
        # ─── Why uppercase? ───
        # SEC tickers are stored uppercase. Normalizing here
        # prevents mismatches like "aapl" vs "AAPL".
        self.ticker = ticker.upper()
        self.filing_types = filing_types or DEFAULT_FILING_TYPES

        # These get populated during the pipeline
        self._cik: str | None = None
        self._company_name: str | None = None

    async def _ticker_to_cik(self) -> str:
        """
        Look up a company's CIK number from its ticker symbol.

        Why is this needed?
        The SEC doesn't use ticker symbols as IDs. They use CIK
        (Central Index Key) — a numeric ID like 320193 for Apple.
        The submissions API requires CIK, so we translate first.

        The lookup file is a JSON dict like:
        {
          "0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc."},
          "1": {"cik_str": "789019", "ticker": "MSFT", "title": "Microsoft Corp"},
          ...
        }
        """
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.get(_TICKERS_URL)
            resp.raise_for_status()

        data = resp.json()

        # Search through the mapping for our ticker
        for entry in data.values():
            if entry.get("ticker", "").upper() == self.ticker:
                self._cik = str(entry["cik_str"])
                self._company_name = entry.get("title")
                return self._cik

        raise ValueError(f"Ticker '{self.ticker}' not found in SEC database")

    async def fetch_raw(self, **kwargs) -> dict:
        """
        Fetch the company's full submission history from EDGAR.

        Two-step process:
        1. Resolve ticker → CIK (if not already done)
        2. Fetch submissions JSON using CIK

        The CIK must be zero-padded to 10 digits.
        E.g., Apple's CIK 320193 → "0000320193"
        """
        # Step 1: Resolve ticker to CIK
        if not self._cik:
            await self._ticker_to_cik()

        # Step 2: Fetch submissions
        # ─── Why zero-pad? ───
        # The SEC URL requires exactly 10 digits.
        # CIK "320193" must become "0000320193".
        padded_cik = self._cik.zfill(10)
        url = _SUBMISSIONS_URL.format(cik=padded_cik)

        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return resp.json()

    def normalize(self, raw_data: dict) -> list[dict]:
        """
        Parse EDGAR's columnar submission data into FilingRow dicts.

        EDGAR returns data in COLUMNAR format (not rows!):
        {
          "filings": {
            "recent": {
              "form":            ["10-K", "10-Q", "8-K", ...],
              "filingDate":      ["2024-11-01", "2024-08-02", ...],
              "accessionNumber": ["0000320193-24-000123", ...],
              "primaryDocument": ["aapl-20240928.htm", ...],
              ...
            }
          }
        }

        Index 0 across all arrays = first filing
        Index 1 across all arrays = second filing
        ...and so on. We "zip" them together into rows.
        """
        # Navigate to the recent filings data
        recent = raw_data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])

        if not forms:
            return []

        rows = []
        skipped = 0

        # ─── Zip the parallel arrays together ───
        # This is like reading across columns in a spreadsheet:
        # forms[i], dates[i], accessions[i] all describe the SAME filing.
        for i in range(len(forms)):
            form_type = forms[i]

            # Only keep filing types we care about (10-K, 10-Q)
            if form_type not in self.filing_types:
                continue

            try:
                row = FilingRow(
                    cik=self._cik,
                    ticker=self.ticker,
                    company_name=self._company_name,
                    accession_number=accessions[i],
                    filing_type=form_type,
                    filing_date=dates[i],
                    raw_json=None,  # could store full filing later
                    source=self.provider_name,
                )
                rows.append(row.model_dump())
            except Exception as e:
                skipped += 1
                logger.warning(f"Skipped EDGAR filing: {e}")

        if skipped:
            logger.info(
                f"EDGAR {self.ticker}: parsed {len(rows)}, skipped {skipped}"
            )

        return rows

    async def store(self, pool: asyncpg.Pool, rows: list[dict]) -> int:
        """
        Upsert filings to the database.

        ON CONFLICT (accession_number) DO NOTHING means:
        - Each filing has a globally unique accession number
        - If we already stored this filing, skip it silently
        - This is different from prices/fx which conflict on (symbol, date, source)
        """
        return await upsert_filings(pool, rows)
