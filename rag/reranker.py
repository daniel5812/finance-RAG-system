"""
rag/reranker.py — Retrieval Quality Re-ranking

Reorders Pinecone vector search results using a cross-encoder model.
Semantic similarity (bi-encoder) gets the top 20 candidates, and then
this cross-encoder scores the exact (question, chunk) pairs to find the true top 5.
"""

import json
import asyncio
from typing import List, Dict

from core.connections import rerank_model
from core.logger import get_logger

logger = get_logger(__name__)

async def rerank_chunks(question: str, chunks: List[Dict], top_n: int = 5) -> List[Dict]:
    """
    Score each (question, chunk) pair and return the top N chunks.
    If the reranker model is missing, gracefully falls back to vector scores.

    Args:
        question: The user's question.
        chunks: List of match dicts from Pinecone (must contain a "metadata" dict with "text").
        top_n: How many chunks to return after reranking.

    Returns:
        Sorted list of chunks with an updated "rerank_score" attached.
    """
    if not chunks:
        return []

    # Fast fallback if model is unavailable
    if rerank_model is None:
        logger.warning("Reranking model unavailable — falling back to Pinecone scores")
        return chunks[:top_n]

    # Prepare input pairs
    # Extract text from metadata (handling slightly different chunk formats)
    pairs = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        text = metadata.get("text", "")
        pairs.append((question, text))

    # CPU-bound model inference, must run in a thread to keep async fast
    try:
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            None,
            lambda p=pairs: rerank_model.predict(p)
        )
    except Exception as e:
        logger.error(f"Reranker model failed: {e}")
        return chunks[:top_n]  # graceful fallback

    # Attach scores back to chunks
    for i, chunk in enumerate(chunks):
        chunk["rerank_score"] = float(scores[i])

    # Sort descending by reranker score
    reranked = sorted(chunks, key=lambda c: c.get("rerank_score", -999.0), reverse=True)

    # Log the top N scores so we can inspect them
    score_preview = [
        {"score": round(c["rerank_score"], 4), "text": c["metadata"]["text"][:60] + "..."}
        for c in reranked[:top_n]
    ]

    logger.info(json.dumps({
        "event": "chunks_reranked",
        "input_count": len(chunks),
        "output_count": min(len(reranked), top_n),
        "scores": score_preview
    }))

    return reranked[:top_n]
