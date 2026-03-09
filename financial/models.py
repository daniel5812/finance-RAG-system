"""
models.py — Pydantic validation models for financial data.

Every row passes through validation BEFORE hitting the database.
If a row has bad data (missing date, negative price), it fails here
instead of corrupting the database.
"""

from datetime import date
from pydantic import BaseModel, Field, field_validator


class PriceRow(BaseModel):
    """Validated row for the prices table."""
    symbol: str = Field(..., min_length=1, max_length=20)
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float = Field(...)
    volume: int | None = None
    currency: str = Field(default="USD", max_length=3)
    source: str = Field(..., max_length=50)

    @field_validator("close", "open", "high", "low", mode="before")
    @classmethod
    def price_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Price must be positive, got {v}")
        return v


class FXRateRow(BaseModel):
    """Validated row for the fx_rates table."""
    base_currency: str = Field(..., min_length=3, max_length=3)
    quote_currency: str = Field(..., min_length=3, max_length=3)
    date: date
    rate: float = Field(..., gt=0)
    source: str = Field(..., max_length=50)


class MacroSeriesRow(BaseModel):
    """Validated row for the macro_series table."""
    series_id: str = Field(..., min_length=1, max_length=50)
    date: date
    value: float
    source: str = Field(..., max_length=50)


class PortfolioPositionRow(BaseModel):
    """Validated row for the portfolio_positions table."""
    symbol: str = Field(..., min_length=1, max_length=20)
    quantity: float
    cost_basis: float | None = None
    currency: str = Field(default="USD", max_length=3)
    account: str = Field(default="default", max_length=50)
    date: date
    source: str = Field(default="manual", max_length=50)


class FilingRow(BaseModel):
    """
    Validated row for the filings table.

    Each SEC filing has a globally unique accession_number
    (e.g. "0000320193-24-000123") — this is our dedup key,
    unlike prices/fx which dedup on (symbol, date, source).
    """
    cik: str = Field(..., min_length=1, max_length=20)
    ticker: str | None = Field(default=None, max_length=10)
    company_name: str | None = Field(default=None, max_length=200)
    accession_number: str = Field(..., min_length=1, max_length=30)
    filing_type: str = Field(..., max_length=10)       # "10-K", "10-Q"
    filing_date: date
    extracted_metrics: dict | None = None               # future: parsed financials
    raw_json: dict | None = None                        # original API response
    source: str = Field(default="sec_edgar", max_length=50)


class ETFHoldingRow(BaseModel):
    """
    Validated row for the etf_holdings table.

    Strict validation:
      - Symbols normalized to uppercase
      - Weight must be > 0 and ≤ 100
      - Rejects any malformed data from yahooquery
    """
    etf_symbol: str = Field(..., min_length=1, max_length=20)
    holding_symbol: str = Field(..., min_length=1, max_length=20)
    holding_name: str | None = Field(default=None, max_length=200)
    weight: float = Field(..., gt=0, le=100)
    sector: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    date: date
    source: str = Field(default="yahooquery", max_length=50)

    @field_validator("etf_symbol", "holding_symbol", mode="before")
    @classmethod
    def normalize_uppercase(cls, v):
        """Always store symbols as uppercase — prevents 'spy' vs 'SPY' mismatches."""
        if isinstance(v, str):
            return v.strip().upper()
        return v
