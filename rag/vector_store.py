"""
vector_store.py — Vector database operations.
Wraps Pinecone behind clean async functions.
Swap the implementation here if you ever change vector DBs.
"""

import asyncio
from core.config import PINECONE_TIMEOUT, ROLE_ACCESS
from core.connections import pinecone_index
from core.logger import get_logger

logger = get_logger(__name__)


async def search(query_vector, role: str, top_k: int) -> list:
    """
    Search vector store for similar documents.
    Returns list of matches with metadata.
    Applies role-based access control filtering.
    """
    if not pinecone_index:
        return []

    allowed_roles = ROLE_ACCESS.get(role, ["public"])
    loop = asyncio.get_running_loop()

    results = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: pinecone_index.query(
                vector=query_vector.tolist(),
                top_k=top_k,
                include_metadata=True,
                filter={"role": {"$in": allowed_roles}}
            )
        ),
        timeout=PINECONE_TIMEOUT
    )
    return results["matches"]


async def upsert(chunk_id: str, vector, text: str, role: str,
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


async def get_stats() -> dict | None:
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
