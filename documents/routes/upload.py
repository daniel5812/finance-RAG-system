"""
documents/routes/upload.py — Document upload endpoint (Stage 1).

POST /documents/upload
  - Accepts a PDF file via multipart form upload
  - Validates: content-type AND magic bytes (defense-in-depth)
  - Reads in chunks — avoids loading large files into memory
  - Saves to local disk under DOCUMENT_UPLOAD_DIR
  - Inserts minimal metadata row into `documents` table
  - Returns HTTP 202 Accepted immediately

What is NOT here yet (intentional):
  - Background processing / task queuing → Stage 2
  - PDF text extraction                 → Stage 3
  - AI classification agent             → Stage 4
  - Status polling endpoint             → Stage 2
  - Real authentication                 → Future (X-Owner-Id header is the placeholder)
"""

import json
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, UploadFile, File, Depends
import asyncpg
from core.dependencies import get_db_pool
from fastapi.responses import JSONResponse

import core.db as db
from core.config import DOCUMENT_UPLOAD_DIR, DOCUMENT_MAX_SIZE_MB
from core.logger import get_logger
from documents.crud import create_document
from documents.schemas import DocumentUploadResponse
from documents.worker import process_document_worker

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

# ── Constants ───────────────────────────────────────────────────────────────

PDF_MAGIC_BYTES = b"%PDF"          # First 4 bytes of every valid PDF
MAX_BYTES = DOCUMENT_MAX_SIZE_MB * 1024 * 1024
CHUNK_SIZE = 64 * 1024             # 64 KB per read — small enough to be safe


# ── Helpers ─────────────────────────────────────────────────────────────────

def _ensure_upload_dir() -> Path:
    """
    Create the upload directory if it doesn't exist and return it as a Path.

    We call this on each request rather than at startup so that:
    - Tests can override DOCUMENT_UPLOAD_DIR without restarting the app
    - Docker volume mounts can appear after the app starts
    """
    upload_path = Path(DOCUMENT_UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


async def _read_and_validate_file(
    file: UploadFile,
) -> tuple[bytes, int]:
    """
    Read the uploaded file in chunks.

    Why chunks?
    -----------
    FastAPI's UploadFile is backed by a SpooledTemporaryFile — it keeps
    small files in memory and spills larger ones to disk. But if we call
    `await file.read()` directly, we load the entire thing into memory at once.
    By reading chunk by chunk we:
      1. Enforce a size limit without buffering the whole file first.
      2. Check magic bytes on the very first chunk without waiting for the rest.

    Returns:
        (file_bytes, total_size_bytes) — the accumulated bytes and their total size.

    Raises:
        HTTPException 413 if file exceeds DOCUMENT_MAX_SIZE_MB
        HTTPException 415 if magic bytes don't match PDF signature
    """
    chunks: list[bytes] = []
    total = 0
    first_chunk = True

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break  # EOF

        if first_chunk:
            # Defense-in-depth: verify magic bytes regardless of Content-Type.
            # A client can set Content-Type: application/pdf on a .exe — we catch it here.
            if not chunk.startswith(PDF_MAGIC_BYTES):
                raise HTTPException(
                    status_code=415,
                    detail=(
                        "File content is not a valid PDF. "
                        "Expected file to begin with '%PDF'."
                    ),
                )
            first_chunk = False

        total += len(chunk)

        if total > MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File exceeds maximum allowed size of {DOCUMENT_MAX_SIZE_MB} MB."
                ),
            )

        chunks.append(chunk)

    return b"".join(chunks), total


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    status_code=202,
    response_model=DocumentUploadResponse,
    summary="Upload a financial document for processing",
)
async def upload_document(
    file: UploadFile = File(..., description="PDF file to upload"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    x_owner_id: str = Header(
        ...,
        alias="X-Owner-Id",
        description="ID of the user uploading the document.",
    ),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> JSONResponse:
    """
    Stages 1 + 3: accept the file, then immediately hand off to the indexing worker.

    The client receives 202 before any processing starts.
    The worker runs after the response is sent (FastAPI BackgroundTasks).
    """

    # ── 1. Content-Type validation ──────────────────────────────────────────
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: '{file.content_type}'. Only PDF files are accepted.",
        )

    original_filename = file.filename or "unnamed.pdf"

    # ── 2. Read and validate bytes ──────────────────────────────────────────
    file_bytes, file_size = await _read_and_validate_file(file)

    # ── 3. Generate document identity ──────────────────────────────────────
    document_id = str(uuid.uuid4())

    # ── 4. Persist to disk ─────────────────────────────────────────────────
    upload_dir = _ensure_upload_dir()
    storage_path = str(upload_dir / f"{document_id}.pdf")

    async with aiofiles.open(storage_path, "wb") as f:
        await f.write(file_bytes)

    # ── 5. Insert metadata into DB ──────────────────────────────────────────
    await create_document(
        pool,
        document_id=document_id,
        owner_id=x_owner_id,
        original_filename=original_filename,
        content_type="application/pdf",
        file_size_bytes=file_size,
        storage_path=storage_path,
    )

    # ── 6. Structured log ───────────────────────────────────────────────────
    logger.info(json.dumps({
        "event": "document_accepted",
        "document_id": document_id,
        "owner_id": x_owner_id,
        "original_filename": original_filename,
        "file_size_bytes": file_size,
    }))

    # ── 7. Schedule the indexing worker (Stage 3) ────────────────────────────
    # Runs AFTER the 202 response is sent — the client never waits for it.
    background_tasks.add_task(
        process_document_worker,
        pool=pool,
        document_id=document_id,
        file_path=storage_path,
        owner_id=x_owner_id,
    )

    # ── 8. Return 202 Accepted ───────────────────────────────────────────────
    return JSONResponse(
        status_code=202,
        content=DocumentUploadResponse(
            document_id=document_id,
            status="accepted",
            original_filename=original_filename,
        ).model_dump(),
    )
