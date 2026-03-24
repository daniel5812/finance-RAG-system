import asyncio
import time
import json
from typing import Any
from fastapi import APIRouter, HTTPException, Depends
import redis.asyncio as aioredis
from sentence_transformers import SentenceTransformer
from openai import AsyncOpenAI

from core.logger import get_logger
from rag import vector_store
from core.state import get_state_metrics, SERVER_START_TIME
from core.dependencies import get_redis, get_embed_model, get_pinecone, get_openai_client

logger = get_logger(__name__)
router = APIRouter()

@router.get("/health")
async def health_check(
    redis_client: aioredis.Redis = Depends(get_redis),
    embed_model: SentenceTransformer = Depends(get_embed_model),
    openai_client: AsyncOpenAI = Depends(get_openai_client),
    pinecone_index: Any = Depends(get_pinecone),
):
    """Liveness/readiness probe — zero OpenAI tokens."""
    loop = asyncio.get_running_loop()

    checks = {
        "model_loaded": embed_model is not None,
        "pinecone_connected": False,
        "openai_configured": openai_client is not None,
        "redis_connected": False,
    }

    # Redis — ping
    try:
        await redis_client.ping()
        checks["redis_connected"] = True
    except Exception as e:
        logger.warning(json.dumps({"event": "redis_health_fail", "error": str(e)}))

    # Pinecone — via vector_store
    vs_stats = await vector_store.get_stats(pinecone_index)
    if vs_stats:
        checks["pinecone_connected"] = vs_stats["connected"]
        checks["pinecone_vectors"] = vs_stats["total_vectors"]

    core_services = [checks["model_loaded"], checks["pinecone_connected"], checks["openai_configured"], checks["redis_connected"]]
    all_ok = all(core_services)
    any_ok = any(core_services)

    if all_ok:
        status = "healthy"
    elif any_ok:
        status = "degraded"
    else:
        status = "unhealthy"

    cache_size = 0
    try:
        cache_size = await redis_client.dbsize()
    except Exception:
        pass

    body = {
        "status": status,
        "services": checks,
        "uptime_seconds": round(time.time() - SERVER_START_TIME),
        "cache_size": cache_size,
    }

    if status == "unhealthy":
        raise HTTPException(status_code=503, detail=body)

    return body

@router.get("/metrics")
async def get_metrics():
    """Observability dashboard — rolling window stats + drift detection."""
    metrics = await get_state_metrics()
    
    scores = metrics["similarity_scores"]
    lats = metrics["latencies"]

    avg_sim = round(sum(scores) / len(scores), 4) if scores else 0
    min_sim = round(min(scores), 4) if scores else 0

    sorted_lats = sorted(lats) if lats else [0]
    p50 = round(sorted_lats[len(sorted_lats) // 2], 3)
    p95 = round(sorted_lats[int(len(sorted_lats) * 0.95)], 3)
    p99 = round(sorted_lats[min(int(len(sorted_lats) * 0.99), len(sorted_lats) - 1)], 3)

    total = metrics["total_queries"]
    hits = metrics["cache_hits"]
    hit_rate = round(hits / total, 3) if total > 0 else 0

    return {
        "total_queries": total,
        "cache_hit_rate": hit_rate,
        "cache_hits": hits,
        "cache_misses": metrics["cache_misses"],
        "similarity": {
            "avg": avg_sim,
            "min": min_sim,
            "window_size": len(scores),
        },
        "latency": {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "window_size": len(lats),
        },
        "low_similarity_count": metrics["low_similarity_count"],
        "drift_alert": avg_sim < 0.35 and len(scores) >= 10,
        "uptime_seconds": round(time.time() - SERVER_START_TIME),
        "active_streams_global": metrics["active_streams"]
    }
