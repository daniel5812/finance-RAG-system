"""
financial/routes/macro.py — Macroeconomic series ingestion endpoint.
POST /financial/ingest/macro
"""

import json
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from financial.providers.macro import FREDProvider
from financial.schemas import MacroIngestRequest

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - macro"])


@router.post("/ingest/macro")
async def ingest_macro(
    request: MacroIngestRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Ingest macroeconomic series data from FRED.

    Pass any valid FRED series_id (e.g. FEDFUNDS, CPIAUCSL, DGS10).
    If incremental=True (default), only fetches data after the last stored date.
    """
    provider = FREDProvider(
        series_id=request.series_id,
        start=request.start_date,
        end=request.end_date,
    )

    try:
        if request.incremental:
            result = await provider.ingest_incremental(pool)
        else:
            result = await provider.ingest(pool)
    except httpx.HTTPStatusError as e:
        logger.error(json.dumps({
            "event": "macro_ingestion_failed",
            "series_id": request.series_id,
            "status_code": e.response.status_code,
        }))
        raise HTTPException(
            status_code=502,
            detail=f"FRED API returned {e.response.status_code} for series {request.series_id}"
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "macro_ingestion_error",
            "series_id": request.series_id,
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=str(e))

    result["series_id"] = request.series_id
    return result
