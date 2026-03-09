"""
documents/routing.py — Stage 4: Routing Agent

Translates a user question into:
    1. A validated list of relevant document_ids (from the user's completed docs)
    2. 1-3 optimized financial search queries (for better Pinecone retrieval)

Pipeline (this file — Steps A, B, C):
    A. PostgreSQL auth pre-check  → fetch user's completed document_ids
    B. LLM routing call           → structured output (RoutingResponse)
    C. Validation guardrails      → intersect + retry up to 3 times

Not implemented here (Step D, next):
    D. Pinecone vector search     → filter by owner_id + validated document_ids

Security rules:
    - Never log user question, chunk text, or PII
    - Only log latency, token usage, retry counts, document_id lists
"""

import asyncio
import json
import time
from typing import List

from pydantic import BaseModel, field_validator
import asyncpg
from core.llm_client import RoutingAgentClient, LLMAPIError

from documents.crud import get_user_completed_documents
from core.config import OPENAI_TIMEOUT
from core.logger import get_logger
from documents.schemas import RoutingResponse

logger = get_logger(__name__)


# ── Output schema (enforces LLM response structure) ───────────────────────────


# ── Step A: PostgreSQL auth pre-check ────────────────────────────────────────

async def _fetch_user_documents(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """
    Fetch all completed documents belonging to this user.

    Only documents with status='completed' are eligible for retrieval.
    A document that is still 'processing' or 'failed' must never be queried.

    Returns:
        List of dicts with keys: document_id, original_filename
        Empty list if the user has no completed documents.
    """
    return await get_user_completed_documents(pool, user_id)


# ── Step B: Routing LLM call ─────────────────────────────────────────────────

from core.prompts import ROUTING_SYSTEM_PROMPT


async def _call_routing_llm(
    question: str,
    allowed_documents: list[dict],
) -> RoutingResponse:
    """
    Ask the LLM to select relevant document_ids and rewrite the question
    into optimized search queries.

    Uses OpenAI's `parse()` method with a Pydantic schema to enforce
    structured output — the SDK handles JSON mode and schema injection.

    Args:
        question:          The user's raw question (not logged)
        allowed_documents: List of {document_id, original_filename} dicts
                           fetched from PostgreSQL (Step A)

    Returns:
        RoutingResponse with validated_ids and optimized queries.

    Raises:
        LLMAPIError: on API failure (caller retries)
        pydantic.ValidationError: if LLM output doesn't match schema
    """
    # Build the list of allowed documents for the prompt.
    # The LLM MUST only return IDs from this list.
    doc_list_text = "\n".join(
        f"  - ID: {d['document_id']} | File: {d['original_filename']}"
        for d in allowed_documents
    )

    user_message = f"""\
Allowed documents (pick ONLY from these IDs):
{doc_list_text}

User question: {question}

Respond with a JSON object using exactly these field names:
{{
  "relevant_document_ids": ["<one of the IDs above>"],
  "optimized_search_queries": ["financial query 1", "financial query 2"]
}}
"""

    raw_json = await RoutingAgentClient.generate_json(
        messages=[
            {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ]
    )

    return RoutingResponse.model_validate_json(raw_json)


# ── Step C: Validation guardrails ────────────────────────────────────────────

MAX_RETRIES = 3


async def _validate_and_retry(
    question: str,
    allowed_documents: list[dict],
) -> RoutingResponse:
    """
    Call the routing LLM and validate its output. Retry up to MAX_RETRIES times
    if the LLM hallucinates document IDs that don't exist in our allowed list.

    Hallucination check:
        The LLM might invent plausible-looking UUIDs. We intersect its response
        with the DB-fetched list. Any ID not in the DB list is rejected.
        If the intersection is empty (all IDs hallucinated), we retry.

    Args:
        question:          User's raw question
        allowed_documents: Validated list from PostgreSQL (Step A)

    Returns:
        RoutingResponse with relevant_document_ids guaranteed to be a subset
        of the allowed_documents list.

    Raises:
        RuntimeError: if all retries fail (caller returns a controlled error)
    """
    allowed_ids = {d["document_id"] for d in allowed_documents}
    t_start = time.time()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await _call_routing_llm(question, allowed_documents)

            # Intersect returned IDs with DB list — drop any hallucinated IDs
            hallucinated = set(response.relevant_document_ids) - allowed_ids
            validated_ids = [
                doc_id for doc_id in response.relevant_document_ids
                if doc_id in allowed_ids
            ]

            if hallucinated:
                logger.warning(json.dumps({
                    "event": "routing_hallucination_detected",
                    "attempt": attempt,
                    "hallucinated_count": len(hallucinated),
                    # Never log the actual IDs from the question context
                }))

            if not validated_ids and response.relevant_document_ids:
                # LLM returned IDs but ALL were hallucinated — retry
                logger.warning(json.dumps({
                    "event": "routing_all_ids_invalid",
                    "attempt": attempt,
                }))
                continue

            # ✅ Valid response
            elapsed = round(time.time() - t_start, 3)
            logger.info(json.dumps({
                "event": "routing_success",
                "attempt": attempt,
                "validated_id_count": len(validated_ids),
                "query_count": len(response.optimized_search_queries),
                "latency_s": elapsed,
            }))

            # Return with the cleaned (validated) ID list
            return RoutingResponse(
                relevant_document_ids=validated_ids,
                optimized_search_queries=response.optimized_search_queries,
            )

        except Exception as e:
            logger.warning(json.dumps({
                "event": "routing_attempt_failed",
                "attempt": attempt,
                "error": type(e).__name__,
                "detail": str(e)[:120],  # log enough to debug schema mismatches
            }))
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Routing agent failed after {MAX_RETRIES} attempts: {type(e).__name__}"
                )

    raise RuntimeError(f"Routing agent exhausted {MAX_RETRIES} retries")


# ── Step D: Vector retrieval (Pinecone, I/O-bound) ───────────────────────────

async def _search_documents(
    user_id: str,
    validated_ids: list[str],
    optimized_queries: list[str],
    top_k: int = 5,
) -> list[dict]:
    """
    Embed each optimized query and search Pinecone with strict metadata filters.

    Why query per optimized_query (not just once)?
    -----------------------------------------------
    The LLM may rewrite one question into 2-3 complementary queries.
    e.g.: "how much did I make" →
        - "cumulative investment return 2024"
        - "portfolio total gain loss Q4"
    Each query probes a slightly different part of the embedding space.
    We union and deduplicate the results, keeping the highest score per chunk.

    Pinecone filter:
        { "owner_id": user_id, "document_id": { "$in": validated_ids } }

        owner_id   — tenant isolation (Option B: filter BEFORE vector search)
        document_id — restrict to LLM-selected documents only

    Args:
        user_id:           Authenticated user (never queried without this)
        validated_ids:     Document IDs approved by LLM + DB intersection
        optimized_queries: 1-3 rewritten queries from the routing LLM
        top_k:             How many results to fetch per query

    Returns:
        Deduplicated list of match dicts, sorted by score descending.
        Each dict has: id, score, metadata (owner_id, document_id, text, chunk_index)
    """
    from core.connections import embed_model, pinecone_index

    if embed_model is None:
        raise RuntimeError("Embedding model not loaded.")
    if pinecone_index is None:
        raise RuntimeError("Pinecone index not connected.")

    # Build strict metadata filter — never search outside this user's documents
    pinecone_filter = {
        "owner_id": user_id,
        "document_id": {"$in": validated_ids},
    }

    seen: dict[str, dict] = {}   # chunk_id → best match (dedup by score)
    loop = asyncio.get_running_loop()

    for query_text in optimized_queries:
        # Embed in a thread — CPU-bound (SentenceTransformer.encode)
        vector = await asyncio.to_thread(
            lambda q=query_text: embed_model.encode(q).tolist()
        )

        # Query Pinecone in executor — I/O-bound (synchronous SDK call)
        results = await loop.run_in_executor(
            None,
            lambda v=vector: pinecone_index.query(
                vector=v,
                top_k=top_k,
                include_metadata=True,
                filter=pinecone_filter,
            )
        )

        # matches is a Pinecone QueryResponse object — access via .matches attribute
        for match in (results.matches or []):
            chunk_id = match.id
            score    = match.score
            metadata = dict(match.metadata) if match.metadata else {}
            if chunk_id not in seen or score > seen[chunk_id]["score"]:
                seen[chunk_id] = {
                    "id":       chunk_id,
                    "score":    score,
                    "metadata": metadata,
                }

    # Sort by score descending and return as a flat list
    ranked = sorted(seen.values(), key=lambda m: m["score"], reverse=True)
    return ranked


# ── Public entry point (full pipeline A → B → C → D) ─────────────────────────

async def route_question(
    pool: asyncpg.Pool,
    question: str,
    user_id: str,
) -> RoutingResponse | None:
    """
    Steps A + B + C only (routing skeleton).
    Returns the validated RoutingResponse, or None if no docs found.
    Used when you want routing without retrieval (e.g., for testing).
    """
    t_total = time.time()

    allowed_documents = await _fetch_user_documents(pool, user_id)

    logger.info(json.dumps({
        "event": "routing_started",
        "user_id": user_id,
        "eligible_document_count": len(allowed_documents),
    }))

    if not allowed_documents:
        logger.info(json.dumps({"event": "routing_no_documents", "user_id": user_id}))
        return None

    result = await _validate_and_retry(question, allowed_documents)

    logger.info(json.dumps({
        "event": "routing_completed",
        "user_id": user_id,
        "total_latency_s": round(time.time() - t_total, 3),
        "validated_id_count": len(result.relevant_document_ids),
        "query_count": len(result.optimized_search_queries),
    }))

    return result


async def route_and_search(
    pool: asyncpg.Pool,
    question: str,
    user_id: str,
    top_k: int = 5,
) -> dict:
    """
    Full pipeline: Steps A + B + C + D.

    This is the single entry point for the document RAG path.
    Call this from the /chat endpoint instead of the old generic search.

    Returns:
        {
            "chunks":   list of retrieved chunk dicts (id, score, metadata)
            "queries":  list of optimized search queries used
            "doc_ids":  list of validated document IDs that were searched
        }

        Empty chunks list if:
        - User has no completed documents (return a helpful message to user)
        - LLM found no relevant documents for this question

    Raises:
        RuntimeError: if routing or Pinecone fails after all retries
    """
    t_total = time.time()

    # ── Steps A + B + C: route ───────────────────────────────────────────────
    routing = await route_question(pool, question, user_id)

    if routing is None:
        # No completed documents for this user
        return {"chunks": [], "queries": [], "doc_ids": []}

    if not routing.relevant_document_ids:
        # LLM opted out — fall back to searching ALL completed documents.
        # This handles cases where the LLM under-selects (returns []) even though
        # the question is clearly answerable from the user's documents.
        logger.info(json.dumps({
            "event": "routing_fallback_all_docs",
            "user_id": user_id,
            "reason": "LLM returned empty relevant_document_ids",
        }))
        all_doc_ids = [d["document_id"] for d in await _fetch_user_documents(pool, user_id)]
        if not all_doc_ids:
            return {"chunks": [], "queries": [], "doc_ids": []}

        t_search = time.time()
        chunks = await _search_documents(
            user_id=user_id,
            validated_ids=all_doc_ids,
            optimized_queries=[question],  # use raw question as fallback query
            top_k=top_k * 2,               # over-fetch for reranker
        )
        
        from rag.reranker import rerank_chunks
        chunks = await rerank_chunks(question, chunks, top_n=top_k)
        
        logger.info(json.dumps({
            "event": "retrieval_completed",
            "user_id": user_id,
            "mode": "fallback",
            "chunks_retrieved_final": len(chunks),
            "search_latency_s": round(time.time() - t_search, 3),
        }))
        # ── Map filenames into chunk metadata ────────────────────────────────
        doc_map = {d["document_id"]: d["original_filename"] for d in await _fetch_user_documents(pool, user_id)}
        for chunk in chunks:
            doc_id = chunk["metadata"].get("document_id")
            if doc_id:
                chunk["metadata"]["filename"] = doc_map.get(doc_id)

        return {
            "chunks":  chunks,
            "queries": [question],
            "doc_ids": all_doc_ids,
        }

    # ── Step D: vector retrieval ─────────────────────────────────────────────
    t_search = time.time()
    chunks = await _search_documents(
        user_id=user_id,
        validated_ids=routing.relevant_document_ids,
        optimized_queries=routing.optimized_search_queries,
        top_k=top_k * 2,  # over-fetch for reranker
    )
    
    from rag.reranker import rerank_chunks
    chunks = await rerank_chunks(question, chunks, top_n=top_k)

    logger.info(json.dumps({
        "event": "retrieval_completed",
        "user_id": user_id,
        "chunks_retrieved_final": len(chunks),
        "search_latency_s": round(time.time() - t_search, 3),
        "total_latency_s":  round(time.time() - t_total, 3),
    }))

    # ── Map filenames into chunk metadata ────────────────────────────────────
    all_docs = await _fetch_user_documents(pool, user_id)
    doc_map = {d["document_id"]: d["original_filename"] for d in all_docs}
    for chunk in chunks:
        doc_id = chunk["metadata"].get("document_id")
        if doc_id:
            chunk["metadata"]["filename"] = doc_map.get(doc_id)

    return {
        "chunks":  chunks,
        "queries": routing.optimized_search_queries,
        "doc_ids": routing.relevant_document_ids,
    }
