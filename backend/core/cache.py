"""
core/cache.py — All caching strategies in one place.
Exact-match (Redis), embedding cache, and semantic cache.
"""

import json
import hashlib
import re
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


# ── Semantic Cache — Ticker Fingerprint ──
# These tokens are common English words, currency ISO codes, and FRED series IDs
# that should NOT be treated as ticker discriminators.
_FINGERPRINT_EXCLUSIONS: frozenset[str] = frozenset({
    # Currency ISO codes
    "USD", "ILS", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
    # FRED series IDs
    "CPI", "GDP", "FED",
    # Common English 2-5 letter words that appear uppercased
    "THE", "AND", "FOR", "NOT", "YOU", "ALL", "CAN", "WAS", "ONE",
    "NEW", "NOW", "SEE", "WHO", "DID", "LET", "PUT", "SAY", "SHE",
    "TOO", "USE", "WAY", "HAVE", "BEEN", "WERE", "THEY", "THEM",
    "THAN", "THEN", "SOME", "MORE", "ALSO", "INTO", "OVER", "SUCH",
    "WHAT", "THAT", "THIS", "WHEN", "WITH", "WILL", "JUST", "FROM",
    # Financial domain words that are NOT ticker symbols
    "RATE", "SHOW", "TELL", "GIVE", "DOES", "MAKE", "TAKE", "COME",
    "STOCK", "PRICE", "TRADE", "FUND", "BOND", "HOLD", "SELL", "ETF",
    "COST", "GAIN", "LOSS", "RISK", "HIGH", "OPEN", "CLOSE", "MUCH",
})


def _extract_ticker_fingerprint(question: str) -> list[str]:
    """
    Extract likely stock ticker symbols from a question for semantic-cache discrimination.

    Returns a sorted list of uppercase 2–5 letter tokens that are NOT in the
    exclusion set (currencies, common words, domain keywords).  This list is
    stored alongside each semantic-cache entry and compared at lookup time so
    that a cached answer for TSLA is never returned for XYZ123 (or vice-versa),
    even though the two questions have near-identical embeddings.

    Returns [] for questions that contain no discriminating ticker tokens, e.g.
    pure FX / macro queries — in that case the normal similarity threshold applies.
    """
    tokens = re.findall(r'\b([A-Z]{2,5})\b', question.upper())
    return sorted({t for t in tokens if t not in _FINGERPRINT_EXCLUSIONS})


# ── Semantic Cache ──

async def semantic_cache_lookup(
    vector: np.ndarray,
    role: str,
    owner_id: str | None = None,
    question: str | None = None,
) -> dict | None:
    """
    Search semantic cache for a similar question. Returns cached answer or None.

    The cache key includes owner_id to prevent cross-tenant cache hits:
    a user-b question must never return a user-a cached answer, even if
    the questions are semantically identical.

    Ticker fingerprint guard: if the current question contains specific ticker
    symbols (e.g. TSLA) and a matching entry was stored for a *different* ticker
    (e.g. AAPL), the hit is skipped even if cosine similarity is above threshold.
    This prevents cross-ticker answer contamination for price-lookup queries.
    """
    sc_key = f"semcache:{role}:{owner_id or ''}"
    raw = await connections.redis_client.get(sc_key)
    if raw is None:
        return None
    entries = json.loads(raw)
    query_norm = vector / (np.linalg.norm(vector) + 1e-10)
    current_fp = _extract_ticker_fingerprint(question) if question else []
    for entry in entries:
        stored_vec = np.array(entry["vector"], dtype=np.float32)
        stored_norm = stored_vec / (np.linalg.norm(stored_vec) + 1e-10)
        similarity = float(np.dot(query_norm, stored_norm))
        if similarity >= SEMANTIC_CACHE_THRESHOLD:
            stored_fp = entry.get("ticker_fp", [])
            # Symmetric fingerprint guard: skip whenever the fingerprints differ AND
            # at least one side is non-empty.  The original one-sided check
            # (`if stored_fp and ...`) missed the case where the stored entry has no
            # tickers (e.g. a macro/FX answer, stored_fp=[]) but the current query
            # does (e.g. "AAPL price", current_fp=["AAPL"]) — allowing a Fed-rate
            # cached answer to be returned for a stock-price query.
            if stored_fp != current_fp and (stored_fp or current_fp):
                logger.debug(f"semantic_cache: fingerprint mismatch — stored={stored_fp}, current={current_fp}")
                continue
            cached = await redis_get(entry["cache_key"])
            if cached is not None:
                return cached["data"]
    return None


async def semantic_cache_store(
    vector: np.ndarray,
    role: str,
    cache_key: str,
    owner_id: str | None = None,
    question: str | None = None,
):
    """
    Add an embedding+cache_key to the semantic cache for this role+owner.
    Keyed by owner_id so different users never share semantic cache entries.

    If `question` is provided the ticker fingerprint is stored alongside the
    entry so lookup can skip cross-ticker hits (see semantic_cache_lookup).
    """
    sc_key = f"semcache:{role}:{owner_id or ''}"
    raw = await connections.redis_client.get(sc_key)
    entries = json.loads(raw) if raw else []
    entry: dict = {"vector": vector.tolist(), "cache_key": cache_key}
    if question:
        fp = _extract_ticker_fingerprint(question)
        if fp:
            entry["ticker_fp"] = fp
    entries.append(entry)
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
