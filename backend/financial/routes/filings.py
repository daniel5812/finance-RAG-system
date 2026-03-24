"""
financial/routes/filings.py — SEC EDGAR filings ingestion endpoint.
POST /financial/ingest/filings
"""

import json

import httpx
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from financial.schemas import FilingsIngestRequest
from financial.providers.filings import EDGARProvider

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - filings"])


@router.post("/ingest/filings")
async def ingest_filings(
    request: FilingsIngestRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Ingest SEC filing metadata for a company.

    Pass a stock ticker (e.g. AAPL). We look up its CIK number,
    fetch filing history from EDGAR, and store 10-K/10-Q metadata.
    Duplicates are skipped via the unique accession_number constraint.
    """
    provider = EDGARProvider(
        ticker=request.ticker,
        filing_types=set(request.filing_types),
    )

    try:
        result = await provider.ingest(pool)
    except ValueError as e:
        # Ticker not found in SEC database
        raise HTTPException(status_code=404, detail=str(e))
    except httpx.HTTPStatusError as e:
        logger.error(json.dumps({
            "event": "filings_ingestion_failed",
            "ticker": request.ticker,
            "status_code": e.response.status_code,
        }))
        raise HTTPException(
            status_code=502,
            detail=f"SEC EDGAR returned {e.response.status_code} for ticker {request.ticker}"
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "filings_ingestion_error",
            "ticker": request.ticker,
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=str(e))

    result["ticker"] = request.ticker
    return result
