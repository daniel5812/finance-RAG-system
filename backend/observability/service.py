"""
observability/service.py — Single entry point for all pipeline instrumentation.

Usage in any pipeline module:
    from observability.service import obs

    obs.emit(
        stage=PipelineStage.ROUTER,
        event_name="router_plan_built",
        summary="2 plans: sql(fx_rates) + vector(document_analysis)",
        data={"plan_count": 2, "intents": ["fx_rate", "document_analysis"]},
        latency_ms=45.2,
    )

    obs.emit_error(
        stage=PipelineStage.SQL_RETRIEVAL,
        error_category=ErrorCategory.INFRA,
        error_code="SQL_RETRIEVAL_TIMEOUT",
        message="asyncpg query timed out after 5s",
        exc=e,
    )

Design principles:
  - Never raises. All exceptions swallowed internally.
  - Non-blocking: storage writes are fire-and-forget (asyncio.create_task).
  - Logs to stdout immediately (structured JSON) — storage is best-effort.
  - Reads req_id/user_id from ContextVars — no need to pass them manually.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback as tb_module
from typing import Any, Optional

from core.logger import get_logger, request_id_var, user_id_var
from observability.schemas import (
    ErrorCategory,
    ErrorEvent,
    EventSeverity,
    EventStatus,
    LLMTrace,
    PipelineStage,
    RequestRun,
    TraceEvent,
)

logger = get_logger("observability")


class ObservabilityService:
    """
    Context-var-aware observability service.

    Thread-safe: req_id and user_id are read from ContextVars set per-request
    by the ASGI middleware, so concurrent requests never mix their traces.
    """

    # ── Internal helpers ────────────────────────────────────────────────────

    def _req_id(self) -> str:
        return request_id_var.get("none")

    def _user_id(self) -> str:
        return user_id_var.get("none")

    def _fire(self, coro) -> None:
        """Schedule a coroutine as a background task. Safe in async context."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass  # no running loop (e.g. test startup) — silently skip

    # ── Public API ───────────────────────────────────────────────────────────

    def emit(
        self,
        stage: PipelineStage,
        event_name: str,
        status: EventStatus = EventStatus.SUCCESS,
        severity: EventSeverity = EventSeverity.INFO,
        latency_ms: Optional[float] = None,
        summary: str = "",
        data: Optional[dict[str, Any]] = None,
        debug: Optional[dict[str, Any]] = None,
    ) -> TraceEvent:
        """
        Emit a structured trace event.

        Logs to stdout immediately.
        Appends to Redis trace list as a background task.

        Returns the event (useful for testing / chaining).
        """
        event = TraceEvent(
            req_id=self._req_id(),
            stage=stage,
            event_name=event_name,
            status=status,
            severity=severity,
            latency_ms=latency_ms,
            summary=summary,
            data=data or {},
            debug=debug,
        )

        # Structured stdout — visible in docker logs immediately
        log_payload = {
            "obs":        event_name,
            "stage":      stage.value,
            "status":     status.value,
            "summary":    summary,
        }
        if latency_ms is not None:
            log_payload["latency_ms"] = round(latency_ms, 2)
        if data:
            log_payload["data"] = data

        if severity == EventSeverity.ERROR:
            logger.error(json.dumps(log_payload))
        elif severity == EventSeverity.WARNING:
            logger.warning(json.dumps(log_payload))
        else:
            logger.info(json.dumps(log_payload))

        from observability import store
        self._fire(store.append_trace_event(event))

        return event

    def emit_error(
        self,
        stage: PipelineStage,
        error_category: ErrorCategory,
        error_code: str,
        message: str,
        exc: Optional[Exception] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> ErrorEvent:
        """
        Emit a categorized error event.

        Logs to stdout AND persists to Postgres.
        Also appended to the Redis trace so the timeline shows failures.
        """
        traceback_str = tb_module.format_exc() if exc else None

        event = ErrorEvent(
            req_id=self._req_id(),
            stage=stage,
            error_category=error_category,
            error_code=error_code,
            message=message,
            traceback=traceback_str,
            data=data or {},
        )

        logger.error(json.dumps({
            "obs_error":  error_code,
            "category":   error_category.value,
            "stage":      stage.value,
            "message":    message,
        }))

        from observability import store
        self._fire(store.append_trace_event(event))
        self._fire(store.persist_error(event))

        return event

    def emit_llm_trace(
        self,
        trace: LLMTrace,
    ) -> None:
        """
        Record the full LLM introspection for this request.

        Persists to both Redis (fast 24h lookup) and Postgres (durable).
        """
        logger.info(json.dumps({
            "obs_llm":          "llm_trace_complete",
            "behavior":         trace.behavior.classification,
            "flags":            [f.value for f in trace.behavior.flags],
            "confidence_source": trace.output_structure.confidence_source,
            "latency_ms":       round(trace.latency_ms, 2),
            "prompt_tokens_est": trace.input_blocks.estimated_prompt_tokens,
            "blocks": {
                "portfolio":   trace.input_blocks.has_normalized_portfolio,
                "market":      trace.input_blocks.has_market_context,
                "validation":  trace.input_blocks.has_validation_block,
                "vector":      trace.input_blocks.has_vector_context,
                "sql":         trace.input_blocks.has_sql_context,
            },
        }))

        from observability import store
        self._fire(store.persist_llm_trace(trace))

    def finalize_request(self, run: RequestRun) -> None:
        """
        Persist the final request summary to Postgres.

        Called by middleware at the end of every request.
        """
        from observability import store
        self._fire(store.persist_request_run(run))

    # ── Convenience timing context manager ──────────────────────────────────

    def stage_timer(self, stage: PipelineStage, event_name: str, summary: str = "", data: Optional[dict] = None):
        """
        Context manager that emits a timed trace event.

        Usage:
            async with obs.stage_timer(PipelineStage.ROUTER, "router_plan"):
                plan = await planner.plan(question)
        """
        return _StageTimer(self, stage, event_name, summary, data)


class _StageTimer:
    """Async context manager for timing a pipeline stage."""

    def __init__(self, service: ObservabilityService, stage, event_name, summary, data):
        self._svc = service
        self._stage = stage
        self._event_name = event_name
        self._summary = summary
        self._data = data or {}
        self._t0 = 0.0

    async def __aenter__(self):
        self._t0 = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.time() - self._t0) * 1000
        if exc_type:
            self._svc.emit(
                stage=self._stage,
                event_name=f"{self._event_name}_failed",
                status=EventStatus.FAILED,
                severity=EventSeverity.ERROR,
                latency_ms=latency_ms,
                summary=f"{self._summary} — FAILED: {exc_val}",
                data=self._data,
            )
        else:
            self._svc.emit(
                stage=self._stage,
                event_name=f"{self._event_name}_done",
                status=EventStatus.SUCCESS,
                latency_ms=latency_ms,
                summary=self._summary,
                data=self._data,
            )
        return False  # don't suppress exceptions


# ── Module-level singleton ───────────────────────────────────────────────────

obs = ObservabilityService()
