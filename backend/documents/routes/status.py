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

from typing import List
from fastapi import APIRouter, HTTPException, Depends
import asyncpg
from core.dependencies import get_db_pool

from core.logger import get_logger
from documents.crud import get_document_status as crud_get_document_status, get_user_documents as crud_get_user_documents
from documents.schemas import DocumentStatusResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.get(
    "/",
    response_model=List[DocumentStatusResponse],
    summary="List all documents for a user",
)
async def list_documents(
    owner_id: str = "test_advisor_user",
    pool: asyncpg.Pool = Depends(get_db_pool)
) -> List[DocumentStatusResponse]:
    """
    List all documents belonging to the specified user.
    """
    rows = await crud_get_user_documents(pool, owner_id)
    return [
        DocumentStatusResponse(
            document_id=r["document_id"],
            owner_id=r["owner_id"],
            original_filename=r["original_filename"],
            file_size_bytes=r["file_size_bytes"],
            status=r["status"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


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


@router.delete(
    "/{document_id}",
    summary="Delete a document",
)
async def delete_document(
    document_id: str,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Delete a document from the system."""
    from documents.crud import delete_document as crud_delete_document
    await crud_delete_document(pool, document_id)
    return {"status": "deleted", "document_id": document_id}

@router.get(
    "/{document_id}/text",
    summary="Get full document text",
)
async def get_document_text(
    document_id: str,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Retrieve the full extracted text of a document."""
    row = await crud_get_document_status(pool, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    
    storage_path = row["storage_path"]
    text_path = f"{storage_path}.txt"
    
    # If the original was a .txt file, it might not have a separate .txt suffix added by worker
    import os
    if not os.path.exists(text_path):
        text_path = storage_path
        
    try:
        with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {"document_id": document_id, "content": content}
    except Exception as e:
        raise HTTPException(500, f"Failed to read document text: {e}")
