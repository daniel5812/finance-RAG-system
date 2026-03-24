"""
documents/worker.py — Stage 3: The Indexing Worker.

Converts an uploaded PDF into searchable vector knowledge in Pinecone.
Called as a background task immediately after a successful upload.

Pipeline:
    1. ✅ Status lifecycle  (pending_processing → processing → completed/failed)
    2. ✅ PDF text extraction  (CPU-bound → asyncio.to_thread)
    3. ✅ Text chunking         (CPU-bound → asyncio.to_thread)
    4. ✅ Embedding             (CPU-bound → asyncio.to_thread)
    5. ✅ Pinecone upsert       (I/O-bound → asyncio.get_running_loop().run_in_executor)

Design rules:
    - Fail safely: any unhandled exception → status = "failed", never crash the API
    - CPU vs I/O: extraction/chunking/embedding run in a thread (not the event loop)
    - Never log chunk text or PII — only IDs, counts, and latency
"""

import asyncio
import time
import json
import threading
import asyncpg
from typing import Any

_embed_lock = threading.Lock()

from documents.crud import update_document_status
from core.logger import get_logger
from rag.processing import chunk_text

logger = get_logger(__name__)


# ── Status helpers ────────────────────────────────────────────────────────────

async def _set_status(pool: asyncpg.Pool, document_id: str, status: str) -> None:
    """Update the document's pipeline status in PostgreSQL."""
    await update_document_status(pool, document_id, status)


# ── Step 2: PDF text extraction (CPU-bound) ───────────────────────────────────

def _extract_text(file_path: str) -> str:
    """
    Extract all text from a PDF file using pypdf.

    Why pypdf?
    ----------
    - Pure Python, no system dependencies (no poppler, no ghostscript)
    - Works well for PDFs with embedded text (broker reports, pension statements)
    - Handles multi-page documents automatically

    Why run in a thread?
    --------------------
    pypdf is synchronous and CPU-bound. Calling it directly in an async
    function would block the entire event loop, freezing all concurrent requests.
    The caller must wrap this with asyncio.to_thread().

    Returns:
        Full extracted text (all pages joined with newlines).
        Empty string if no text could be extracted (e.g. scanned image PDF).

    Raises:
        FileNotFoundError: if the file doesn't exist.
        pypdf.errors.PdfReadError: if the PDF is corrupt or encrypted.
    """
    if not file_path.lower().endswith(".pdf"):
        # For non-PDFs (like .txt), just read the content directly.
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    import pypdf  # local import — keeps startup fast if pypdf not yet installed

    text_parts: list[str] = []

    with open(file_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        total_pages = len(reader.pages)

        for page_num, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
            except Exception as e:
                # Log but don't abort — a single bad page shouldn't fail the whole doc
                logger.warning(json.dumps({
                    "event": "page_extraction_skip",
                    "file_path": file_path,
                    "page": page_num,
                    "total_pages": total_pages,
                    "error": str(e),
                }))

    return "\n".join(text_parts)


# ── Step 4: Embed chunks (CPU-bound) ─────────────────────────────────────────

def _embed_chunks(embed_model: Any, chunks: list[str]) -> list[list[float]]:
    """
    Encode a list of text chunks into dense vectors using SentenceTransformer.

    Why run in a thread?
    --------------------
    SentenceTransformer.encode() is synchronous and CPU/GPU intensive.
    Running it in the event loop would block all concurrent API requests
    for the duration of the heavy computation.

    Why batch all chunks at once?
    -----------------------------
    SentenceTransformer.encode() is significantly faster when processing
    chunks in a single batch rather than one by one — it can use GPU
    parallelism and avoids Python loop overhead.

    Returns:
        List of float vectors, one per chunk, each of length 384
        (all-MiniLM-L6-v2 output dimension).
    """
    if embed_model is None:
        raise RuntimeError(
            "Embedding model is not loaded. "
            "Check startup logs for 'Embedding model not available'."
        )

    with _embed_lock:
        vectors = embed_model.encode(chunks, show_progress_bar=False)
        
    return vectors.tolist()


# ── Step 5: Upsert to Pinecone (I/O-bound) ───────────────────────────────────

async def _upsert_vectors(
    pinecone_index: Any,
    document_id: str,
    owner_id: str,
    chunks: list[str],
    vectors: list[list[float]],
) -> int:
    """
    Batch-upsert all chunk vectors into Pinecone in a single API call.

    Vector ID format:
        "{document_id}_{chunk_index}"
        e.g. "abc123-..._0", "abc123-..._1"

        Using document_id as a prefix makes it easy to delete all chunks
        for a document later (wildcard delete, or fetch by prefix).

    Metadata per vector:
        owner_id    — used for tenant isolation in queries (Option B filter)
        document_id — used to link back to the documents table
        text        — the raw chunk text, returned with search results
                      so the LLM can synthesize it without a second lookup

    Why run_in_executor instead of asyncio.to_thread?
    --------------------------------------------------
    pinecone_index.upsert() is a synchronous network call (I/O-bound).
    run_in_executor releases the event loop during the network wait,
    same as asyncio.to_thread — both use the default ThreadPoolExecutor.

    Returns:
        Number of vectors successfully upserted.

    Raises:
        RuntimeError: if Pinecone is not connected.
    """
    if pinecone_index is None:
        raise RuntimeError(
            "Pinecone index is not connected. "
            "Check PINECONE_API_KEY and INDEX_NAME in environment."
        )

    # Build the upsert payload
    pinecone_vectors = [
        {
            "id": f"{document_id}_{i}",
            "values": vectors[i],
            "metadata": {
                "owner_id": owner_id,
                "document_id": document_id,
                "text": chunks[i],           # stored for retrieval — never logged
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        }
        for i in range(len(chunks))
    ]

    # Pinecone .upsert() is synchronous — run it in a thread
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: pinecone_index.upsert(vectors=pinecone_vectors),
    )

    return len(pinecone_vectors)


# ── Worker entry point ────────────────────────────────────────────────────────

async def process_document_worker(
    pool: asyncpg.Pool,
    pinecone_index: Any,
    embed_model: Any,
    document_id: str,
    file_path: str,
    owner_id: str,
) -> None:
    """
    Background worker: PDF on disk → searchable chunks in Pinecone.

    Called by the upload route via FastAPI BackgroundTasks.
    Never raises — all failures are caught, logged, and written to DB.
    """
    t_start = time.time()

    logger.info(json.dumps({
        "event": "worker_started",
        "document_id": document_id,
        "owner_id": owner_id,
        "file_path": file_path,
    }))

    await _set_status(pool, document_id, "processing")

    try:

        # ── Step 2: Extract text (CPU → thread) ──────────────────────────────
        raw_text: str = await asyncio.to_thread(_extract_text, file_path)

        if not raw_text.strip():
            raise ValueError(
                "No extractable text found. The PDF may be a scanned image. "
                "OCR support is not yet implemented."
            )

        logger.info(json.dumps({
            "event": "text_extracted",
            "document_id": document_id,
            "char_count": len(raw_text),
        }))

        # ── Save extracted text to disk for Source Viewer ──
        try:
            text_path = f"{file_path}.txt"
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
        except Exception as e:
            logger.warning(f"Failed to save extracted text for {document_id}: {e}")

        # ── Step 3: Chunk (CPU → thread) ─────────────────────────────────────
        chunks: list[str] = await asyncio.to_thread(chunk_text, raw_text)

        logger.info(json.dumps({
            "event": "text_chunked",
            "document_id": document_id,
            "chunk_count": len(chunks),
        }))

        # ── Step 4: Embed (CPU → thread) ─────────────────────────────────────
        t_embed = time.time()
        vectors: list[list[float]] = await asyncio.to_thread(_embed_chunks, embed_model, chunks)

        logger.info(json.dumps({
            "event": "chunks_embedded",
            "document_id": document_id,
            "vector_count": len(vectors),
            "vector_dim": len(vectors[0]) if vectors else 0,
            "embed_latency_s": round(time.time() - t_embed, 2),
        }))

        # ── Step 5: Upsert to Pinecone (I/O → executor) ──────────────────────
        t_upsert = time.time()
        upserted = await _upsert_vectors(pinecone_index, document_id, owner_id, chunks, vectors)

        logger.info(json.dumps({
            "event": "vectors_upserted",
            "document_id": document_id,
            "upserted_count": upserted,
            "upsert_latency_s": round(time.time() - t_upsert, 2),
        }))

        # ── Mark completed ────────────────────────────────────────────────────
        await _set_status(pool, document_id, "completed")

        elapsed = round(time.time() - t_start, 2)
        logger.info(json.dumps({
            "event": "worker_completed",
            "document_id": document_id,
            "chunk_count": len(chunks),
            "elapsed_s": elapsed,
        }))

    except Exception as exc:
        await _set_status(pool, document_id, "failed")

        logger.error(json.dumps({
            "event": "worker_failed",
            "document_id": document_id,
            "error": str(exc),
            "elapsed_s": round(time.time() - t_start, 2),
        }))
