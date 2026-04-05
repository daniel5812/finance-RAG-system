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


# ── Portfolio Management ─────────────────────────────────────────────────────

class PortfolioPositionCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    quantity: float = Field(..., gt=0)
    cost_basis: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", max_length=3)
    account: str = Field(default="default", max_length=50)
    date: date


class PortfolioPositionResponse(BaseModel):
    id: int
    user_id: str
    symbol: str
    quantity: float
    cost_basis: float | None
    currency: str
    account: str
    date: date
    source: str
    created_at: date | None = None
