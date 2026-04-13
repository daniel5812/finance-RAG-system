"""
observability/routes.py — Admin debug API for the observability system.

All endpoints require admin:read scope (same as existing /admin/* routes).

Endpoints:
  GET /admin/observability/requests            — paginated request run history
  GET /admin/observability/requests/{req_id}   — full trace timeline for one request
  GET /admin/observability/errors              — recent errors, filterable by category
  GET /admin/observability/metrics             — last-1h aggregate health dashboard

Developer workflow:
  1. Something goes wrong in production.
  2. Copy the X-Request-ID from the response header (or browser Network tab).
  3. GET /admin/observability/requests/{req_id}
     → See every stage, latency, status, and LLM behavior for that exact request.
  4. If LLM misbehaved: check `llm_trace.behavior.flags` and `arithmetic_markers`.
  5. If a stage failed: check `events` where status="failed" for error_code + traceback.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from core.dependencies import require_scope
from observability import store

router = APIRouter(prefix="/admin/observability", tags=["observability"])

_READ = Depends(require_scope("admin:read"))


# ── Request Explorer ─────────────────────────────────────────────────────────


@router.get("/requests", dependencies=[_READ])
async def list_requests(
    limit:        int            = Query(50, le=200, ge=1),
    offset:       int            = Query(0,  ge=0),
    user_id:      Optional[str]  = Query(None),
    cache_hit:    Optional[bool] = Query(None),
    request_type: Optional[str]  = Query(None, description="user | admin | all"),
    errors_only:  bool           = Query(False),
):
    """
    Paginated list of recent request runs.

    Use `cache_hit=false` to find only full pipeline executions.
    Use `user_id=...` to filter by a specific user.

    Sample response item:
    {
      "req_id": "a1b2c3d4-...",
      "user_id": "user@example.com",
      "path": "/chat",
      "total_latency_ms": 1823.5,
      "cache_hit": false,
      "intent": "investment_recommendation",
      "intelligence_confidence": "high",
      "llm_behavior_classification": "followed_system",
      "error_count": 0
    }
    """
    return await store.get_request_runs(
        limit=limit, offset=offset, user_id=user_id, cache_hit=cache_hit,
        request_type=request_type, errors_only=errors_only,
    )


@router.get("/requests/{req_id}", dependencies=[_READ])
async def get_request_trace(req_id: str):
    """
    Full trace timeline for a single request, plus LLM introspection.

    Returns:
    {
      "req_id": "...",
      "timeline": [               ← ordered list of TraceEvent/ErrorEvent dicts
        {"stage": "cache", "event_name": "cache_miss", "latency_ms": 2.1, ...},
        {"stage": "router", "event_name": "router_plan_built", ...},
        ...
        {"stage": "llm_execution", "event_name": "llm_call_done", "latency_ms": 1240, ...},
      ],
      "llm_trace": {              ← LLM introspection (null if intelligence layer didn't run)
        "input_blocks": {...},    ← what blocks reached the LLM
        "constraints": {...},     ← which rules were applied
        "output_structure": {...},← what came back
        "behavior": {             ← did it follow the rules?
          "classification": "followed_system",
          "flags": ["followed_system"],
          "arithmetic_markers": [],
          "notes": "No anomalies detected"
        }
      },
      "errors": [...]             ← subset of timeline where status="failed"
    }

    If req_id is older than 24h, timeline will be empty (Redis TTL expired).
    The llm_trace and request run summary remain in Postgres indefinitely.
    """
    timeline  = await store.get_trace_events(req_id)
    llm_trace = await store.get_llm_trace(req_id)
    errors    = [e for e in timeline if e.get("status") == "failed"]

    return {
        "req_id":    req_id,
        "timeline":  timeline,
        "llm_trace": llm_trace,
        "errors":    errors,
        "stage_count": len(timeline),
        "error_count": len(errors),
    }


# ── Error Center ─────────────────────────────────────────────────────────────


@router.get("/errors", dependencies=[_READ])
async def list_errors(
    limit:    int           = Query(50, le=200, ge=1),
    category: Optional[str] = Query(None, description="INFRA | PIPELINE | DATA | BUSINESS | SECURITY"),
    req_id:   Optional[str] = Query(None),
):
    """
    Recent errors, optionally filtered by category or request.

    Use `category=INFRA` to find DB/Redis connectivity issues.
    Use `category=PIPELINE` to find agent failures.
    Use `category=SECURITY` to investigate injection attempts.

    Each error includes:
      - error_code: machine-readable (e.g. "VECTOR_RETRIEVAL_TIMEOUT")
      - message: human-readable explanation
      - traceback: full Python traceback (only when exception was caught)
      - data: structured context at the time of failure
    """
    return await store.get_errors(limit=limit, category=category, req_id=req_id)


# ── System Health Dashboard ──────────────────────────────────────────────────


@router.get("/metrics", dependencies=[_READ])
async def get_observability_metrics():
    """
    Aggregate health metrics for the last 1 hour.
    """
    return await store.get_metrics_summary()


@router.get("/status", dependencies=[_READ])
async def get_observability_status():
    """
    Check connectivity to Redis and Postgres.
    """
    return await store.get_store_status()


# ── LLM Behavior Details ─────────────────────────────────────────────────────


@router.get("/llm/{req_id}", dependencies=[_READ])
async def get_llm_trace(req_id: str):
    """
    LLM introspection record for a single request.

    Useful when you want just the LLM view without the full timeline.
    Returns null if no intelligence layer ran (e.g., cache hit or factual query
    that bypassed the investment intelligence pipeline).
    """
    trace = await store.get_llm_trace(req_id)
    if trace is None:
        return {"req_id": req_id, "llm_trace": None, "reason": "No LLM trace found (cache hit or non-intelligence query)"}
    return {"req_id": req_id, "llm_trace": trace}
