from datetime import date
from pydantic import BaseModel, Field


class PriceIngestRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, examples=["SPY", "AAPL"])
    start_date: date | None = None
    end_date: date | None = None
    incremental: bool = True   # default: only fetch new data


class MacroIngestRequest(BaseModel):
    series_id: str = Field(
        ..., min_length=1, max_length=50,
        examples=["FEDFUNDS", "CPIAUCSL", "DGS10"],
    )
    start_date: date | None = None
    end_date: date | None = None
    incremental: bool = True


class HoldingsIngestRequest(BaseModel):
    etf_symbols: list[str] | None = Field(
        default=None,
        examples=[["SPY", "QQQ", "IVV"]],
        description="Specific ETFs to ingest. If omitted, all active ETFs are processed.",
    )


class FXIngestRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    incremental: bool = True


class FilingsIngestRequest(BaseModel):
    ticker: str = Field(
        ..., min_length=1, max_length=10,
        examples=["AAPL", "MSFT", "GOOGL"],
    )
    filing_types: list[str] = Field(default=["10-K", "10-Q"])
