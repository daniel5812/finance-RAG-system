"""
financial/routes/fx.py — FX rate ingestion endpoint.
POST /financial/ingest/fx
"""

import json
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from financial.providers.fx import FXProvider
from financial.schemas import FXIngestRequest
from financial.providers.fx import BOIProvider

logger = get_logger(__name__)
router = APIRouter(prefix="/financial", tags=["financial - fx"])


@router.post("/ingest/fx")
async def ingest_fx(
    request: FXIngestRequest,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Ingest daily FX rates from Bank of Israel.

    Fetches all supported currencies (USD, EUR, GBP, CHF, JPY, AUD, CAD)
    against ILS in a single API call.
    """
    provider = BOIProvider(
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
            "event": "fx_ingestion_failed",
            "status_code": e.response.status_code,
        }))
        raise HTTPException(
            status_code=502,
            detail=f"BOI API returned {e.response.status_code}"
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "fx_ingestion_error",
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=str(e))

    return result
