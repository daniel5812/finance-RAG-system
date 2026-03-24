"""
core/state.py — Shared runtime state (Redis-backed).
Ensures metrics and counters are accurate across scaled instances.
"""

import time
import asyncio
import json
from core.connections import redis_client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

# ── Server start time (local to instance, but metrics will be global) ──
SERVER_START_TIME = time.time()

# ── Redis Keys ──
METRIC_TOTAL = "metrics:total_queries"
METRIC_HIT = "metrics:cache_hits"
METRIC_MISS = "metrics:cache_misses"
METRIC_LOW_SIM = "metrics:low_similarity_count"
METRIC_ACTIVE_STREAMS = "metrics:active_streams"
LIST_SIMILARITY = "metrics:list:similarity"
LIST_LATENCY = "metrics:list:latency"

# ── Concurrency Control (Local Semaphore for LLM slots) ──
# We keep the semaphore local to prevent one instance from hogging all LLM capacity.
LLM_SEMAPHORE = asyncio.Semaphore(5)

# ── Metrics Helpers (Async) ──

async def incr_metric(key: str, amount: int = 1):
    """Increment a counter in Redis."""
    await redis_client.incrby(key, amount)

async def record_value(key: str, value: float, max_len: int = 200):
    """Push a value to a Redis list and trim to maintain window size."""
    await redis_client.lpush(key, value)
    await redis_client.ltrim(key, 0, max_len - 1)

async def get_state_metrics() -> dict:
    """Fetch all metrics from Redis and format them for the dashboard."""
    # Pipeline for batch fetching
    pipe = redis_client.pipeline()
    pipe.get(METRIC_TOTAL)
    pipe.get(METRIC_HIT)
    pipe.get(METRIC_MISS)
    pipe.get(METRIC_LOW_SIM)
    pipe.get(METRIC_ACTIVE_STREAMS)
    pipe.lrange(LIST_SIMILARITY, 0, -1)
    pipe.lrange(LIST_LATENCY, 0, -1)
    
    res = await pipe.execute()
    
    raw_total = int(res[0]) if res[0] else 0
    raw_hits = int(res[1]) if res[1] else 0
    raw_miss = int(res[2]) if res[2] else 0
    raw_low = int(res[3]) if res[3] else 0
    raw_active = int(res[4]) if res[4] else 0
    
    sim_scores = [float(x) for x in res[5]] if res[5] else []
    latencies = [float(x) for x in res[6]] if res[6] else []
    
    return {
        "total_queries": raw_total,
        "cache_hits": raw_hits,
        "cache_misses": raw_miss,
        "low_similarity_count": raw_low,
        "active_streams": raw_active,
        "similarity_scores": sim_scores,
        "latencies": latencies
    }

# ── Active Streams Management ──

async def get_active_streams() -> int:
    val = await redis_client.get(METRIC_ACTIVE_STREAMS)
    return int(val) if val else 0

async def incr_active_streams():
    await redis_client.incr(METRIC_ACTIVE_STREAMS)

async def decr_active_streams():
    val = await redis_client.decr(METRIC_ACTIVE_STREAMS)
    if val < 0:
        await redis_client.set(METRIC_ACTIVE_STREAMS, 0)


