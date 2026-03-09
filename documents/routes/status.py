"""
documents/routes/status.py — Document status polling endpoint (Stage 2).

GET /documents/{document_id}

Returns the document's current position in the processing pipeline.
This is how clients discover when their uploaded PDF has been processed.

Status lifecycle (driven by the `documents` table):
    pending_processing  ← just uploaded, worker hasn't started yet
    processing          ← text extraction / embedding in progress
    completed           ← chunks stored in Pinecone, ready to query
    failed              ← something went wrong (check logs for document_id)

The client flow:
    1. POST /documents/upload          → get document_id
    2. Poll GET /documents/{id}        → wait until status == "completed"
    3. POST /chat (with document_id)   → ask questions about the document
"""

from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from documents.crud import get_document_status as crud_get_document_status
from documents.schemas import DocumentStatusResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    summary="Get document processing status",
)
async def get_document_status(
    document_id: str,
    pool: asyncpg.Pool = Depends(get_db_pool)
) -> DocumentStatusResponse:
    """
    Poll the processing status of a previously uploaded document.

    Returns 404 if the document_id doesn't exist.
    Returns the full metadata row so the client knows:
      - Is it ready? (status == "completed")
      - Did it fail? (status == "failed")
      - Who owns it?
      - How big was it?
    """
    row = await crud_get_document_status(pool, document_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found.",
        )

    logger.info(f"Status poll: document_id={document_id} status={row['status']}")

    return DocumentStatusResponse(
        document_id=str(row["id"]),
        owner_id=row["owner_id"],
        original_filename=row["original_filename"],
        file_size_bytes=row["file_size_bytes"],
        status=row["status"],
        storage_path=row["storage_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
