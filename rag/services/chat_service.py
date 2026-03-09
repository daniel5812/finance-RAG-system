import time
import json
import asyncio
from typing import AsyncGenerator
from fastapi import HTTPException

from core.config import *
from core.logger import get_logger
from core.llm_client import ChatAgentClient
from core.cache import redis_get, redis_set, generate_cache_key, cached_embed, semantic_cache_lookup, semantic_cache_store
from core.security import content_filter
from rag.processing import dynamic_filter
from rag import vector_store
import core.state as state
from core.state import LLM_SEMAPHORE
from documents.routing import route_and_search
from rag.schemas import ChatQuery
from core.prompts import CHAT_SYSTEM_PROMPT, CHAT_STREAM_PROMPT
import asycpg
logger = get_logger(__name__)

async def regenerate_response(question: str, cache_key: str, user_role: str = "employee"):
    # 🛡️ Backpressure: background task — skip if LLM is busy (user already got stale response)
    if LLM_SEMAPHORE.locked():
        logger.info(json.dumps({"event": "bg_regeneration_skipped", "reason": "llm_busy"}))
        return

    try:
        logger.info(json.dumps({"event": "bg_regeneration_start"}))

        loop = asyncio.get_running_loop()
        query_vector = await cached_embed(question, loop)
        matches = await vector_store.search(query_vector, user_role, DYNAMIC_TOP_K)

        good_matches = dynamic_filter(matches)
        relevant_contexts = [m["metadata"]["text"] for m in good_matches]

        if not relevant_contexts:
            return

        context_block = "\n---\n".join(relevant_contexts)

        # 🛡️ Backpressure: acquire semaphore for LLM call
        await LLM_SEMAPHORE.acquire()
        try:
            answer = await ChatAgentClient.generate(
                messages=[
                    {"role": "system", "content": "Answer strictly based on context."},
                    {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion:\n{question}"}
                ]
            )
        finally:
            LLM_SEMAPHORE.release()

        result = {
            "answer": answer,
            "sources": relevant_contexts,
            "source_type": "generated"
        }

        await redis_set(cache_key, {
            "data": result,
            "timestamp": time.time()
        })

        logger.info(json.dumps({"event": "bg_regeneration_done"}))

    except Exception as e:
        logger.error(f"Background regeneration failed: {e}")


async def generate_chat_response(pool: asyncpg.Pool, query: ChatQuery) -> dict:
    t0 = time.time()
    await state.incr_metric(state.METRIC_TOTAL)

    # 🔹 1. CACHE CHECK (LRU + TTL + Soft TTL)
    cache_key_input = f"{query.user_role}:{query.owner_id or ''}:{query.question}"
    cache_key = generate_cache_key(cache_key_input)
    current_time = time.time()

    cache_entry = await redis_get(cache_key)

    if cache_entry is not None:
        age = current_time - cache_entry["timestamp"]

        # 🟡 SOFT EXPIRED → Return stale + background refresh
        if age > CACHE_SOFT_TTL:
            logger.info(json.dumps({"event": "cache_stale", "action": "return_stale_and_refresh"}))
            asyncio.create_task(
                regenerate_response(query.question, cache_key, query.user_role)
            )
            cached = cache_entry["data"]
            cached["source_type"] = "stale"
            return cached

        # 🟢 VALID
        else:
            logger.info(json.dumps({"event": "cache_hit"}))
            await state.incr_metric(state.METRIC_HIT)
            cached = cache_entry["data"]
            cached["source_type"] = "cache"
            return cached

    await state.incr_metric(state.METRIC_MISS)

    if not vector_store.pinecone_index:
        raise HTTPException(500, "Vector store not connected")

    loop = asyncio.get_running_loop()

    # 🔹 2. Embedding (with Redis cache)
    t1 = time.time()
    query_vector = await cached_embed(query.question, loop)
    embed_time = time.time() - t1

    # 🔹 2b. Semantic cache check
    sem_result = await semantic_cache_lookup(query_vector, query.user_role, owner_id=query.owner_id)
    if sem_result is not None:
        logger.info(json.dumps({"event": "semantic_cache_hit"}))
        await state.incr_metric(state.METRIC_HIT)
        sem_result["source_type"] = "semantic_cache"
        return sem_result

    # 🔹 3. Retrieval
    t2 = time.time()
    routing_time = 0.0
    relevant_contexts: list[str] = []

    if query.owner_id:
        try:
            t_route = time.time()
            route_result = await route_and_search(
                pool=pool,
                question=query.question,
                user_id=query.owner_id,
                top_k=DYNAMIC_TOP_K,
            )
            routing_time = time.time() - t_route
        except RuntimeError as e:
            raise HTTPException(503, f"Routing agent failed: {e}")

        chunks = route_result["chunks"]
        relevant_contexts = [
            m["metadata"]["text"]
            for m in chunks
            if m.get("metadata", {}).get("text")
        ]

        logger.info(json.dumps({
            "event": "document_retrieval",
            "owner_id": query.owner_id,
            "doc_ids": route_result["doc_ids"],
            "queries_used": len(route_result["queries"]),
            "chunks_retrieved": len(chunks),
            "routing_s": round(routing_time, 3),
        }))
    else:
        try:
            matches = await vector_store.search(query_vector, query.user_role, top_k=3)
        except asyncio.TimeoutError:
            raise HTTPException(504, "Pinecone query timed out. Try again later.")

        q_hash = generate_cache_key(query.question)[:8]
        logger.info(json.dumps({
            "event": "query_similarity",
            "question_hash": q_hash,
            "matches": [
                {"doc_id": m["id"], "score": round(m["score"], 4)}
                for m in matches
            ]
        }))

        good_matches = dynamic_filter(matches)
        
        for match in matches:
            await state.record_value(state.LIST_SIMILARITY, match["score"])
            
    retrieval_time = time.time() - t2
    
    # 🔹 3.5 Reranking (Stage 5)
    t3 = time.time()
    rerank_time = 0.0
    if locals().get('good_matches') or locals().get('chunks'):
        from rag.reranker import rerank_chunks
        target_chunks = locals().get('good_matches') or chunks
        reranked_matches = await rerank_chunks(query.question, target_chunks, top_n=5)
        relevant_contexts = [m["metadata"]["text"] for m in reranked_matches]
        sources = [
            {
                "document_id": m["metadata"].get("document_id", "unknown"),
                "filename": m["metadata"].get("filename"),
                "chunk_text": m["metadata"]["text"],
                "vector_score": round(m["score"], 4),
                "rerank_score": round(m.get("rerank_score", 0.0), 4)
            }
            for m in reranked_matches
        ]
    else:
        relevant_contexts = []
        sources = []
    
    rerank_time = time.time() - t3

    if not relevant_contexts:
        await state.incr_metric(state.METRIC_LOW_SIM)

    if not relevant_contexts:
        return {
            "answer": "I don't have enough information in your documents to answer this question.",
            "sources": sources,
            "source_type": "generated",
            "latency_breakdown": {
                "embedding": round(embed_time, 3),
                "routing":   round(routing_time, 3),
                "retrieval": round(retrieval_time, 3),
                "rerank":    round(rerank_time, 3),
                "generation": 0,
                "total": round(time.time() - t0, 3)
            }
        }

    # 🔹 5. Generation
    context_block = "\n---\n".join(relevant_contexts)
    system_prompt = CHAT_SYSTEM_PROMPT

    try:
        await asyncio.wait_for(LLM_SEMAPHORE.acquire(), timeout=LLM_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Server busy — too many concurrent LLM requests. Try again in a few seconds.")

    t3 = time.time()
    try:
        answer = await ChatAgentClient.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion:\n{query.question}"}
            ]
        )
    finally:
        LLM_SEMAPHORE.release()
    gen_time = time.time() - t3
    total_time = time.time() - t0

    result = {
        "answer": answer,
        "sources": sources,
        "source_type": "generated",
        "latency_breakdown": {
            "embedding": round(embed_time, 3),
            "routing":   round(routing_time, 3),
            "retrieval": round(retrieval_time, 3),
            "rerank":    round(rerank_time, 3),
            "generation": round(gen_time, 3),
            "total": round(total_time, 3)
        }
    }

    # 🔹 6. Store in Redis Cache + Semantic Cache
    await redis_set(cache_key, {
        "data": result,
        "timestamp": time.time()
    })
    await semantic_cache_store(query_vector, query.user_role, cache_key, owner_id=query.owner_id)

    logger.info(json.dumps({
        "event": "query_processed",
        "mode": "sync",
        "question_hash": generate_cache_key(query.question)[:8],
        "total_s": round(total_time, 3),
        "embed_s": round(embed_time, 3),
        "retrieval_s": round(retrieval_time, 3),
        "rerank_s": round(rerank_time, 3),
        "generation_s": round(gen_time, 3)
    }))

    await state.record_value(state.LIST_LATENCY, total_time)

    return result


async def generate_stream_response(pool: asyncpg.Pool, query: ChatQuery) -> AsyncGenerator[str, None]:
    t0 = time.time()
    await state.incr_metric(state.METRIC_TOTAL)

    cache_key_input = f"{query.user_role}:{query.owner_id or ''}:{query.question}"
    cache_key = generate_cache_key(cache_key_input)
    current_time = time.time()

    cache_entry = await redis_get(cache_key)
    if cache_entry is not None:
        age = current_time - cache_entry["timestamp"]
        if age > CACHE_SOFT_TTL:
            asyncio.create_task(regenerate_response(query.question, cache_key, query.user_role))
            cached = cache_entry["data"]
            yield f"data: {json.dumps({'type': 'meta', 'sources': cached.get('sources', []), 'source_type': 'stale'})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': cached['answer']})}\n\n"
        else:
            await state.incr_metric(state.METRIC_HIT)
            cached = cache_entry["data"]
            yield f"data: {json.dumps({'type': 'meta', 'sources': cached.get('sources', []), 'source_type': 'cache'})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': cached['answer']})}\n\n"
        
        yield f"data: {json.dumps({'type': 'done', 'total_time': round(time.time() - t0, 3)})}\n\n"
        await state.decr_active_streams()
        return

    await state.incr_metric(state.METRIC_MISS)

    if not vector_store.pinecone_index:
        yield f"data: {json.dumps({'type': 'error', 'msg': 'Vector store not connected'})}\n\n"
        await state.decr_active_streams()
        return

    loop = asyncio.get_running_loop()
    t1 = time.time()
    query_vector = await cached_embed(query.question, loop)
    embed_time = time.time() - t1

    sem_result = await semantic_cache_lookup(query_vector, query.user_role, owner_id=query.owner_id)
    if sem_result is not None:
        await state.incr_metric(state.METRIC_HIT)
        yield f"data: {json.dumps({'type': 'meta', 'sources': sem_result.get('sources', []), 'source_type': 'semantic_cache'})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': sem_result['answer']})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total_time': round(time.time() - t0, 3)})}\n\n"
        await state.decr_active_streams()
        return

    t2 = time.time()
    routing_time = 0.0
    relevant_contexts: list[str] = []

    if query.owner_id:
        try:
            t_route = time.time()
            route_result = await route_and_search(pool=pool, question=query.question, user_id=query.owner_id, top_k=DYNAMIC_TOP_K)
            routing_time = time.time() - t_route
            chunks = route_result["chunks"]
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': f'Routing agent failed: {str(e)}'})}\n\n"
            await state.decr_active_streams()
            return
    else:
        try:
            matches = await vector_store.search(query_vector, query.user_role, top_k=3)
            good_matches = dynamic_filter(matches)
            for match in matches:
                await state.record_value(state.LIST_SIMILARITY, match["score"])
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': 'Pinecone query timed out'})}\n\n"
            await state.decr_active_streams()
            return

    retrieval_time = time.time() - t2

    # Reranking
    t3 = time.time()
    rerank_time = 0.0
    if locals().get('good_matches') or locals().get('chunks'):
        from rag.reranker import rerank_chunks
        target_chunks = locals().get('good_matches') or chunks
        reranked_matches = await rerank_chunks(query.question, target_chunks, top_n=5)
        relevant_contexts = [m["metadata"]["text"] for m in reranked_matches]
        sources = [
            {
                "document_id": m["metadata"].get("document_id", "unknown"),
                "filename": m["metadata"].get("filename"),
                "chunk_text": m["metadata"]["text"],
                "vector_score": round(m["score"], 4),
                "rerank_score": round(m.get("rerank_score", 0.0), 4)
            }
            for m in reranked_matches
        ]
    else:
        relevant_contexts = []
        sources = []
    
    rerank_time = time.time() - t3

    if not relevant_contexts:
        await state.incr_metric(state.METRIC_LOW_SIM)
        yield f"data: {json.dumps({'type': 'meta', 'sources': [], 'source_type': 'generated'})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': 'I cannot answer based on provided info.'})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total_time': round(time.time() - t0, 3)})}\n\n"
        await state.decr_active_streams()
        return

    context_block = "\n---\n".join(relevant_contexts)
    system_prompt = CHAT_STREAM_PROMPT

    deadline = time.time() + MAX_STREAM_DURATION

    yield f"data: {json.dumps({'type': 'meta', 'sources': sources, 'source_type': 'generated', 'latency': {'embedding': round(embed_time, 3), 'retrieval': round(retrieval_time, 3)}})}\n\n"

    t3 = time.time()
    collected_tokens = []
    window_buffer = ""

    try:
        await asyncio.wait_for(LLM_SEMAPHORE.acquire(), timeout=LLM_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        yield f"data: {json.dumps({'type': 'error', 'msg': 'Server busy — too many concurrent LLM requests. Try again in a few seconds.'})}\n\n"
        await state.decr_active_streams()
        return

    try:
        stream = ChatAgentClient.generate_stream(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion:\n{query.question}"}
            ]
        )

        async for token in stream:
            if time.time() > deadline:
                logger.warning(f"Stream timeout after {MAX_STREAM_DURATION}s")
                yield f"data: {json.dumps({'type': 'error', 'msg': 'Stream timeout exceeded'})}\n\n"
                break

            collected_tokens.append(token)
            window_buffer += token

            if len(window_buffer) >= BUFFER_LIMIT:
                safe_text, _ = content_filter(window_buffer)
                emit = safe_text[:-OVERLAP_SIZE]
                if emit:
                    yield f"data: {json.dumps({'type': 'token', 'content': emit})}\n\n"
                window_buffer = window_buffer[-OVERLAP_SIZE:]

        if window_buffer:
            safe_text, _ = content_filter(window_buffer)
            yield f"data: {json.dumps({'type': 'token', 'content': safe_text})}\n\n"

        gen_time = time.time() - t3
        total_time = time.time() - t0

        full_answer = "".join(collected_tokens)
        safe_answer, _ = content_filter(full_answer)

        result = {
            "answer": safe_answer,
            "sources": sources,
            "source_type": "generated",
            "latency_breakdown": {
                "embedding": round(embed_time, 3),
                "routing": round(routing_time, 3),
                "retrieval": round(retrieval_time, 3),
                "rerank": round(rerank_time, 3),
                "generation": round(gen_time, 3),
                "total": round(total_time, 3)
            }
        }

        await redis_set(cache_key, {
            "data": result,
            "timestamp": time.time()
        })

        await state.record_value(state.LIST_LATENCY, total_time)

        logger.info(json.dumps({
            "event": "query_processed",
            "mode": "stream",
            "question_hash": generate_cache_key(query.question)[:8],
            "total_s": round(total_time, 3),
            "embed_s": round(embed_time, 3),
            "retrieval_s": round(retrieval_time, 3),
            "rerank_s": round(rerank_time, 3),
            "generation_s": round(gen_time, 3)
        }))

        yield f"data: {json.dumps({'type': 'done', 'total_time': round(total_time, 3), 'generation_time': round(gen_time, 3), 'answer_length': len(full_answer)})}\n\n"
    finally:
        LLM_SEMAPHORE.release()
        await state.decr_active_streams()
