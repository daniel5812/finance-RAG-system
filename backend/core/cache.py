"""
core/cache.py — All caching strategies in one place.
Exact-match (Redis), embedding cache, and semantic cache.
"""

import json
import hashlib
import numpy as np

from core.config import CACHE_TTL, CACHE_SOFT_TTL, EMBED_CACHE_TTL, SEMANTIC_CACHE_THRESHOLD, SEMANTIC_CACHE_MAX
from core import connections
from core.logger import get_logger

logger = get_logger(__name__)


# ── Exact-Match Cache (Redis) ──

async def redis_get(key: str) -> dict | None:
    """Read cache entry from Redis. Returns parsed dict or None."""
    raw = await connections.redis_client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def redis_set(key: str, value: dict, ttl: int = CACHE_TTL):
    """Write cache entry to Redis with TTL."""
    await connections.redis_client.set(key, json.dumps(value), ex=ttl)


def generate_cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ── Embedding Cache ──

async def cached_embed(text: str, loop) -> np.ndarray:
    """Return embedding from Redis cache, or compute + cache it."""
    cache_key = f"embed:{hashlib.md5(text.encode()).hexdigest()}"
    raw = await connections.redis_client.get(cache_key)
    if raw is not None:
        return np.array(json.loads(raw), dtype=np.float32)
    vector = await loop.run_in_executor(None, connections.embed_model.encode, text)
    # Store as JSON list in Redis
    await connections.redis_client.set(cache_key, json.dumps(vector.tolist()), ex=EMBED_CACHE_TTL)
    return vector


# ── Semantic Cache ──

async def semantic_cache_lookup(
    vector: np.ndarray,
    role: str,
    owner_id: str | None = None,
) -> dict | None:
    """
    Search semantic cache for a similar question. Returns cached answer or None.

    The cache key includes owner_id to prevent cross-tenant cache hits:
    a user-b question must never return a user-a cached answer, even if
    the questions are semantically identical.
    """
    sc_key = f"semcache:{role}:{owner_id or ''}"
    raw = await connections.redis_client.get(sc_key)
    if raw is None:
        return None
    entries = json.loads(raw)
    query_norm = vector / (np.linalg.norm(vector) + 1e-10)
    for entry in entries:
        stored_vec = np.array(entry["vector"], dtype=np.float32)
        stored_norm = stored_vec / (np.linalg.norm(stored_vec) + 1e-10)
        similarity = float(np.dot(query_norm, stored_norm))
        if similarity >= SEMANTIC_CACHE_THRESHOLD:
            cached = await redis_get(entry["cache_key"])
            if cached is not None:
                return cached["data"]
    return None


async def semantic_cache_store(
    vector: np.ndarray,
    role: str,
    cache_key: str,
    owner_id: str | None = None,
):
    """
    Add an embedding+cache_key to the semantic cache for this role+owner.
    Keyed by owner_id so different users never share semantic cache entries.
    """
    sc_key = f"semcache:{role}:{owner_id or ''}"
    raw = await connections.redis_client.get(sc_key)
    entries = json.loads(raw) if raw else []
    entries.append({"vector": vector.tolist(), "cache_key": cache_key})
    # Keep only the most recent N entries
    if len(entries) > SEMANTIC_CACHE_MAX:
        entries = entries[-SEMANTIC_CACHE_MAX:]
    await connections.redis_client.set(sc_key, json.dumps(entries), ex=CACHE_TTL)


# ── Plan Cache (Router Decision Caching) ──

async def plan_cache_lookup(vector: np.ndarray, role: str) -> dict | None:
    """
    Look up a previously generated MultiQueryPlan using semantic similarity.
    Target: Bypassing the 4s LLM Router.
    """
    pc_key = f"plancache:{role}"
    raw = await connections.redis_client.get(pc_key)
    if raw is None:
        return None
    entries = json.loads(raw)
    query_norm = vector / (np.linalg.norm(vector) + 1e-10)
    for entry in entries:
        stored_vec = np.array(entry["vector"], dtype=np.float32)
        stored_norm = stored_vec / (np.linalg.norm(stored_vec) + 1e-10)
        similarity = float(np.dot(query_norm, stored_norm))
        if similarity >= SEMANTIC_CACHE_THRESHOLD:
            return entry["plan"]
    return None

async def plan_cache_store(vector: np.ndarray, role: str, plan: dict):
    """Store a router plan in the semantic cache."""
    pc_key = f"plancache:{role}"
    raw = await connections.redis_client.get(pc_key)
    entries = json.loads(raw) if raw else []
    entries.append({"vector": vector.tolist(), "plan": plan})
    if len(entries) > SEMANTIC_CACHE_MAX:
        entries = entries[-SEMANTIC_CACHE_MAX:]
    await connections.redis_client.set(pc_key, json.dumps(entries), ex=CACHE_TTL)
