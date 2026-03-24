"""
financial/routes/portfolio.py — Portfolio upload endpoint (DEPRECATED, returns 410).

The old CSV/XLSX intake system has been removed.
A new PDF-first document analysis pipeline is in development under documents/.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/financial", tags=["financial - portfolio"])


@router.post("/ingest/portfolio-upload", status_code=410)
async def upload_portfolio_file_deprecated():
    """
    [DEPRECATED] CSV/XLSX portfolio upload has been removed.
    A new document analysis pipeline (PDF-first, agent-based) is under development.
    """
    return JSONResponse(
        status_code=410,
        content={
            "detail": "This endpoint has been removed.",
            "reason": "CSV/XLSX upload replaced by document analysis pipeline (coming soon).",
        },
    )
