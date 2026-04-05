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


def generate_cache_key(text: str, user_id: str | None = None) -> str:
    """Generate a hash-based cache key, optionally scoped by user_id."""
    h = hashlib.md5(text.encode()).hexdigest()
    return f"cache:{user_id or 'global'}:{h}"


# ── Embedding Cache ──

async def cached_embed(text: str, loop, user_id: str | None = None) -> np.ndarray:
    """Return embedding from Redis cache, or compute + cache it (User-Scoped)."""
    h = hashlib.md5(text.encode()).hexdigest()
    cache_key = f"embed:{user_id or 'global'}:{h}"
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

# ── Plan Cache (Router Decision Caching) ──

async def plan_cache_lookup(vector: np.ndarray, role: str, owner_id: str | None = None) -> dict | None:
    """
    Look up a previously generated MultiQueryPlan using semantic similarity.
    Scoped by owner_id to prevent leakages.
    """
    pc_key = f"plancache:{role}:{owner_id or 'global'}"
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

async def plan_cache_store(vector: np.ndarray, role: str, plan: dict, owner_id: str | None = None):
    """Store a router plan in the semantic cache (User-Scoped)."""
    pc_key = f"plancache:{role}:{owner_id or 'global'}"
    raw = await connections.redis_client.get(pc_key)
    entries = json.loads(raw) if raw else []
    entries.append({"vector": vector.tolist(), "plan": plan})
    if len(entries) > SEMANTIC_CACHE_MAX:
        entries = entries[-SEMANTIC_CACHE_MAX:]
    await connections.redis_client.set(pc_key, json.dumps(entries), ex=CACHE_TTL)
