"""
observability/store.py — Dual-store: Redis (hot/TTL) + PostgreSQL (durable).

Failure modes:
  - Redis down: Postgres still writes. Trace timeline unavailable, summaries persist.
  - Postgres down: Redis still writes. Timeline available for 24h, no durable record.
  - Both down: stdout logs remain. System continues operating.

All methods swallow exceptions — observability never disrupts the pipeline.
"""

from __future__ import annotations

import json
from typing import Optional

from core.logger import get_logger

logger = get_logger("observability.store")

# Redis key schema:
#   trace:{req_id}      — LIST of serialized TraceEvent/ErrorEvent JSON, TTL 24h
#   llm_trace:{req_id}  — STRING of serialized LLMTrace JSON, TTL 24h
REDIS_TTL        = 86_400   # 24 hours
TRACE_KEY_PREFIX = "trace:"
LLM_KEY_PREFIX   = "llm_trace:"
MAX_EVENTS_PER_REQUEST = 200   # safety cap — prevent runaway appends


def _redis():
    """Return the shared aioredis client. Never raises."""
    try:
        from core.connections import redis_client
        return redis_client
    except Exception:
        return None


async def _pool():
    """Return the asyncpg pool. Never raises."""
    try:
        import core.db as db
        return await db.get_pool()
    except Exception:
        return None


# ── Write operations ─────────────────────────────────────────────────────────


# Throttled warning cache — prevent log flooding when DB/Redis is down
_last_warning_time = {}
WARNING_THROTTLE_S = 300  # 5 minutes


def _should_warn(key: str) -> bool:
    now = time.time()
    if key not in _last_warning_time or (now - _last_warning_time[key]) > WARNING_THROTTLE_S:
        _last_warning_time[key] = now
        return True
    return False


async def append_trace_event(event) -> None:
    """Append a TraceEvent or ErrorEvent to the Redis trace list for its request."""
    r = _redis()
    if not r:
        if _should_warn("redis_append"):
            logger.warning("obs.store: Redis unavailable — trace timeline will not be captured")
        return
    try:
        key = f"{TRACE_KEY_PREFIX}{event.req_id}"
        payload = event.model_dump_json()
        pipe = r.pipeline()
        pipe.rpush(key, payload)
        pipe.ltrim(key, -MAX_EVENTS_PER_REQUEST, -1)  # keep last N events
        pipe.expire(key, REDIS_TTL)
        await pipe.execute()
    except Exception as exc:
        if _should_warn("redis_append_err"):
            logger.warning(f"obs.store: Redis trace append failed: {exc}")


async def persist_error(event) -> None:
    """Write an ErrorEvent to Postgres for durable error tracking."""
    pool = await _pool()
    if not pool:
        if _should_warn("pg_persist"):
            logger.warning("obs.store: Postgres unavailable — durable error tracking disabled")
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO observability_errors
                    (req_id, stage, error_category, error_code, message, traceback, data, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, to_timestamp($8))
                """,
                event.req_id,
                event.stage.value,
                event.error_category.value,
                event.error_code,
                event.message,
                event.traceback,
                json.dumps(event.data),
                event.timestamp,
            )
    except Exception as exc:
        if _should_warn("pg_persist_err"):
            logger.warning(f"obs.store: Postgres error persist failed: {exc}")


async def persist_llm_trace(trace) -> None:
    """Write a LLMTrace to both Redis (fast lookup) and Postgres (durable)."""
    logger.info(f"obs.store: persist_llm_trace for req_id={trace.req_id}")
    r = _redis()
    if r:
        try:
            key = f"{LLM_KEY_PREFIX}{trace.req_id}"
            await r.set(key, trace.model_dump_json(), ex=REDIS_TTL)
        except Exception as exc:
            if _should_warn("redis_llm_err"):
                logger.warning(f"obs.store: Redis LLM trace write failed: {exc}")

    pool = await _pool()
    if not pool:
        if _should_warn("pg_llm_persist"):
            logger.warning("obs.store: Postgres unavailable — durable LLM tracing disabled")
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO observability_llm_traces
                    (req_id, input_blocks, constraints, output_structure, behavior, latency_ms, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, to_timestamp($7))
                ON CONFLICT (req_id) DO UPDATE SET
                    output_structure = EXCLUDED.output_structure,
                    behavior         = EXCLUDED.behavior,
                    latency_ms       = EXCLUDED.latency_ms
                """,
                trace.req_id,
                json.dumps(trace.input_blocks.model_dump()),
                json.dumps(trace.constraints.model_dump()),
                json.dumps(trace.output_structure.model_dump()),
                json.dumps(trace.behavior.model_dump()),
                trace.latency_ms,
                trace.timestamp,
            )
            logger.info(f"obs.store: LLM trace persisted to Postgres for req_id={trace.req_id}")
    except Exception as exc:
        if _should_warn("pg_llm_persist_err"):
            logger.warning(f"obs.store: Postgres LLM trace persist failed: {exc}")


async def persist_request_run(run) -> None:
    """Upsert a RequestRun summary into Postgres."""
    pool = await _pool()
    if not pool:
        if _should_warn("pg_run_persist"):
            logger.warning("obs.store: Postgres unavailable — request history will not be saved")
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO observability_request_runs
                    (req_id, user_id, path, method, status_code, total_latency_ms,
                     stage_count, error_count, cache_hit, cache_type, intent,
                     intelligence_confidence, llm_behavior_classification,
                     sources_retrieved, request_type, timestamp)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, to_timestamp($16))
                ON CONFLICT (req_id) DO UPDATE SET
                    status_code                  = EXCLUDED.status_code,
                    total_latency_ms             = EXCLUDED.total_latency_ms,
                    stage_count                  = EXCLUDED.stage_count,
                    error_count                  = EXCLUDED.error_count,
                    intelligence_confidence      = EXCLUDED.intelligence_confidence,
                    llm_behavior_classification  = EXCLUDED.llm_behavior_classification,
                    sources_retrieved            = EXCLUDED.sources_retrieved,
                    request_type                 = EXCLUDED.request_type
                """,
                run.req_id,
                run.user_id,
                run.path,
                run.method,
                run.status_code,
                run.total_latency_ms,
                run.stage_count,
                run.error_count,
                run.cache_hit,
                run.cache_type,
                run.intent,
                run.intelligence_confidence,
                run.llm_behavior_classification,
                run.sources_retrieved,
                getattr(run, "request_type", "user"),
                run.timestamp,
            )
    except Exception as exc:
        if _should_warn("pg_run_persist_err"):
            logger.warning(f"obs.store: Postgres request run persist failed: {exc}")


# ── Read operations (used by Debug API) ─────────────────────────────────────


async def get_trace_events(req_id: str) -> list[dict]:
    """Fetch all events for a request from Redis. Returns [] on miss/error."""
    r = _redis()
    if not r:
        return []
    try:
        key = f"{TRACE_KEY_PREFIX}{req_id}"
        raw_list = await r.lrange(key, 0, -1)
        return [json.loads(raw) for raw in raw_list]
    except Exception as exc:
        logger.warning(f"obs.store: Redis trace fetch failed: {exc}")
    return []


async def get_llm_trace(req_id: str) -> Optional[dict]:
    """Fetch LLM trace for a request. Tries Redis first, falls back to Postgres."""
    r = _redis()
    if r:
        try:
            key = f"{LLM_KEY_PREFIX}{req_id}"
            raw = await r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning(f"obs.store: Redis LLM trace fetch failed: {exc}")

    pool = await _pool()
    if not pool:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM observability_llm_traces WHERE req_id = $1", req_id
            )
            if row:
                return dict(row)
    except Exception as exc:
        logger.warning(f"obs.store: Postgres LLM trace fetch failed: {exc}")
    return None


async def get_request_runs(
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    cache_hit: Optional[bool] = None,
    request_type: Optional[str] = None,
    errors_only: bool = False,
) -> list[dict]:
    """Paginated list of request runs from Postgres."""
    pool = await _pool()
    if not pool:
        return []
    try:
        filters = []
        params: list = []

        if user_id:
            params.append(user_id)
            filters.append(f"user_id = ${len(params)}")
        if cache_hit is not None:
            params.append(cache_hit)
            filters.append(f"cache_hit = ${len(params)}")
        if request_type and request_type != "all":
            params.append(request_type)
            filters.append(f"COALESCE(request_type, 'user') = ${len(params)}")
        if errors_only:
            filters.append("error_count > 0")

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM observability_request_runs
                {where}
                ORDER BY timestamp DESC
                LIMIT ${len(params) - 1} OFFSET ${len(params)}
                """,
                *params,
            )
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"obs.store: request runs fetch failed: {exc}")
    return []


async def get_errors(
    limit: int = 50,
    category: Optional[str] = None,
    req_id: Optional[str] = None,
) -> list[dict]:
    """Paginated list of errors from Postgres."""
    pool = await _pool()
    if not pool:
        return []
    try:
        filters = []
        params: list = []

        if category:
            params.append(category)
            filters.append(f"error_category = ${len(params)}")
        if req_id:
            params.append(req_id)
            filters.append(f"req_id = ${len(params)}")

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM observability_errors
                {where}
                ORDER BY timestamp DESC LIMIT ${len(params)}
                """,
                *params,
            )
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"obs.store: errors fetch failed: {exc}")
    return []


async def get_metrics_summary() -> dict:
    """Aggregate metrics from Postgres for the health dashboard."""
    pool = await _pool()
    if not pool:
        return {}
    try:
        async with pool.acquire() as conn:
            runs = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                        AS total_requests,
                    COUNT(*) FILTER (WHERE cache_hit = TRUE)       AS cache_hits,
                    ROUND(AVG(total_latency_ms)::numeric, 2)       AS avg_latency_ms,
                    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP
                          (ORDER BY total_latency_ms)::numeric, 2) AS p95_latency_ms,
                    COUNT(*) FILTER (WHERE error_count > 0)        AS requests_with_errors
                FROM observability_request_runs
                WHERE timestamp > NOW() - INTERVAL '1 hour'
                """
            )
            errors = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                                  AS total,
                    COUNT(*) FILTER (WHERE error_category = 'INFRA')         AS infra,
                    COUNT(*) FILTER (WHERE error_category = 'PIPELINE')      AS pipeline,
                    COUNT(*) FILTER (WHERE error_category = 'SECURITY')      AS security
                FROM observability_errors
                WHERE timestamp > NOW() - INTERVAL '1 hour'
                """
            )
            llm = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                                              AS total,
                    COUNT(*) FILTER (WHERE behavior->>'classification' = 'followed_system') AS followed,
                    COUNT(*) FILTER (WHERE behavior->>'classification' = 'deviated')        AS deviated,
                    COUNT(*) FILTER (WHERE behavior->>'classification' = 'added_unsupported_claims') AS unsupported,
                    COUNT(*) FILTER (WHERE behavior->>'reasoning_quality' = 'high_quality_reasoning') AS high_quality,
                    COUNT(*) FILTER (WHERE behavior->>'reasoning_quality' = 'surface_level') AS surface_level,
                    COUNT(*) FILTER (WHERE behavior->>'reasoning_quality' = 'incomplete_use_of_context') AS incomplete
                FROM observability_llm_traces
                WHERE timestamp > NOW() - INTERVAL '1 hour'
                """
            )
            return {
                "window": "last_1h",
                "requests": dict(runs) if runs else {},
                "errors":   dict(errors) if errors else {},
                "llm":      dict(llm) if llm else {},
            }
    except Exception as exc:
        logger.warning(f"obs.store: metrics summary failed: {exc}")
    return {}


async def get_store_status() -> dict:
    """Check connectivity to Redis and Postgres."""
    status = {
        "redis": {"connected": False, "error": None},
        "postgres": {"connected": False, "error": None}
    }

    # Check Redis
    r = _redis()
    if r:
        try:
            await r.ping()
            status["redis"]["connected"] = True
        except Exception as exc:
            status["redis"]["error"] = str(exc)
    else:
        status["redis"]["error"] = "Redis client not initialized"

    # Check Postgres
    pool = await _pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            status["postgres"]["connected"] = True
        except Exception as exc:
            status["postgres"]["error"] = str(exc)
    else:
        status["postgres"]["error"] = "Postgres pool not initialized"

    return status
