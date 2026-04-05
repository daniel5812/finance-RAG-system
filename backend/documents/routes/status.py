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

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
import asyncpg
from pydantic import BaseModel
from core.dependencies import get_db_pool, get_current_user, get_pinecone
from typing import Any
import os

from core.logger import get_logger
from documents.crud import (
    get_document_status as crud_get_document_status,
    get_user_documents as crud_get_user_documents,
    get_folder,
    set_document_folder,
)
from documents.schemas import DocumentStatusResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.get(
    "/",
    response_model=List[DocumentStatusResponse],
    summary="List all documents for a user",
)
async def list_documents(
    folder_id: Optional[int] = Query(None, description="Filter by folder ID"),
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
) -> List[DocumentStatusResponse]:
    """
    List all documents belonging to the authenticated user.
    Pass ?folder_id=<id> to filter by folder.
    """
    rows = await crud_get_user_documents(pool, user_id, folder_id=folder_id)
    return [
        DocumentStatusResponse(
            document_id=r["document_id"],
            owner_id=r["owner_id"],
            original_filename=r["original_filename"],
            file_size_bytes=r["file_size_bytes"],
            status=r["status"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            folder_id=r.get("folder_id"),
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
    user_id: str = Depends(get_current_user),
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
    
    if row["owner_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied to this document",
        )

    logger.info(f"Status poll: document_id={document_id} status={row['status']}")

    return DocumentStatusResponse(
        document_id=str(row["document_id"]),
        owner_id=row["owner_id"],
        original_filename=row["original_filename"],
        file_size_bytes=row["file_size_bytes"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        folder_id=row.get("folder_id"),
    )


@router.delete(
    "/{document_id}",
    summary="Delete a document",
)
async def delete_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
    pinecone_index: Any = Depends(get_pinecone)
):
    """Delete a document (Ownership Verified)."""
    row = await crud_get_document_status(pool, document_id)
    if not row or row["owner_id"] != user_id:
        raise HTTPException(403, "Access denied")
        
    # 1. Delete associated vectors from Pinecone
    try:
        from rag.vector_store import delete_by_doc_id
        await delete_by_doc_id(pinecone_index, document_id)
    except Exception as e:
        logger.error(f"Failed to delete Pinecone vectors for {document_id}: {e}")

    # 2. Delete physical files
    storage_path = row.get("storage_path")
    if storage_path:
        for suffix in ["", ".txt"]:
            file_to_delete = f"{storage_path}{suffix}"
            if os.path.exists(file_to_delete):
                try:
                    os.remove(file_to_delete)
                    logger.info(f"Deleted physical file: {file_to_delete}")
                except Exception as e:
                    logger.error(f"Failed to delete physical file {file_to_delete}: {e}")
        
    # 3. Delete from database
    from documents.crud import delete_document as crud_delete_document
    await crud_delete_document(pool, document_id)
    return {"status": "deleted", "document_id": document_id}

class SetFolderRequest(BaseModel):
    folder_id: Optional[int] = None


@router.patch(
    "/{document_id}/folder",
    summary="Assign or unassign a document to/from a folder",
)
async def set_document_folder_route(
    document_id: str,
    body: SetFolderRequest,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Assign a document to a folder (or unassign by passing folder_id: null).
    Validates both document and folder ownership.
    """
    row = await crud_get_document_status(pool, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    if row["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    if body.folder_id is not None:
        folder = await get_folder(pool, folder_id=body.folder_id, owner_id=user_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found.")

    await set_document_folder(pool, document_id=document_id, folder_id=body.folder_id, owner_id=user_id)
    logger.info(f"document_folder_set document_id={document_id} folder_id={body.folder_id} user={user_id}")
    return {"status": "ok", "document_id": document_id, "folder_id": body.folder_id}


@router.get(
    "/{document_id}/text",
    summary="Get full document text",
)
async def get_document_text(
    document_id: str,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Retrieve the full extracted text (Ownership Verified)."""
    row = await crud_get_document_status(pool, document_id)
    if not row or row["owner_id"] != user_id:
        raise HTTPException(403, "Access denied")
    
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
