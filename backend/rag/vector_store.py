"""
vector_store.py — Vector database operations.
Wraps Pinecone behind clean async functions.
Swap the implementation here if you ever change vector DBs.
"""

import asyncio
from typing import Any
from core.logger import get_logger
from core.config import PINECONE_TIMEOUT, ROLE_ACCESS
from core.connections import pinecone_index

logger = get_logger(__name__)


async def search(pinecone_index: Any, query_vector, role: str, top_k: int, filter_metadata: dict = None) -> list:
    """
    Search vector store for similar documents.
    Returns list of matches with metadata.
    Applies role-based access control filtering and combines it with optional metadata filters.
    """
    if not pinecone_index:
        return []

    allowed_roles = ROLE_ACCESS.get(role, ["public"])
    
    # Merge filters: always include role-based access
    combined_filter = {"role": {"$in": allowed_roles}}
    if filter_metadata:
        combined_filter.update(filter_metadata)

    loop = asyncio.get_running_loop()

    results = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: pinecone_index.query(
                vector=query_vector.tolist(),
                top_k=top_k,
                include_metadata=True,
                filter=combined_filter
            )
        ),
        timeout=PINECONE_TIMEOUT
    )
    return results["matches"]


async def upsert(pinecone_index: Any, chunk_id: str, vector, text: str, role: str,
                 chunk_index: int, total_chunks: int, doc_id: str):
    """Upsert a single chunk to the vector store."""
    if not pinecone_index:
        raise RuntimeError("Vector store not connected")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: pinecone_index.upsert(
            vectors=[
                {
                    "id": chunk_id,
                    "values": vector.tolist(),
                    "metadata": {
                        "text": text,
                        "role": role,
                        "chunk_index": chunk_index,
                        "total_chunks": total_chunks,
                        "doc_id": doc_id,
                    }
                }
            ]
        )
    )


async def delete_by_doc_id(pinecone_index: Any, doc_id: str):
    """Delete all vectors matching a specific document ID."""
    if not pinecone_index:
        logger.warning(f"delete_by_doc_id skipped: Pinecone not connected (doc_id={doc_id})")
        return

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: pinecone_index.delete(filter={"doc_id": {"$eq": doc_id}})
        )
        logger.info(f"Deleted Pinecone vectors for doc_id={doc_id}")
    except Exception as e:
        logger.error(f"Failed to delete Pinecone vectors for doc {doc_id}: {e}")


async def get_stats(pinecone_index: Any) -> dict | None:
    """Get vector store stats (for health checks). Returns None on failure."""
    if not pinecone_index:
        return None
    try:
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(
            None, pinecone_index.describe_index_stats
        )
        return {
            "connected": True,
            "total_vectors": stats.total_vector_count,
        }
    except Exception as e:
        logger.warning(f"Vector store health check failed: {e}")
        return None
