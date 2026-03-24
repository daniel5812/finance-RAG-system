import json
import logging
import time
import functools
import asyncio
from contextvars import ContextVar

# ── Request ID Context — propagated across threads/tasks ──
request_id_var: ContextVar[str] = ContextVar("request_id", default="none")

class StructuredFormatter(logging.Formatter):
    """Outputs logs as single-line JSON for machine parsing."""
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "request_id": request_id_var.get(),
            "event": record.getMessage(),
        }
        return json.dumps(log_entry, ensure_ascii=False)


# Configure root logger once on import
_handler = logging.StreamHandler()
_handler.setFormatter(StructuredFormatter())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that outputs structured JSON."""
    return logging.getLogger(name)


def trace_latency(event_name: str | None = None):
    """
    Decorator to measure and log the latency of a function.
    Logs as an 'event' in structured JSON and records to Redis metrics.
    """
    def decorator(func):
        # We import here to avoid circular imports (logger -> state -> connections -> logger)
        from core import state

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.time() - t0
                name = event_name or f"{func.__name__}_latency"
                logger = get_logger(func.__module__)
                logger.info(json.dumps({
                    "event": name,
                    "duration_s": round(duration, 3)
                }))
                # Record to global Redis metrics
                asyncio.create_task(state.record_value(state.LIST_LATENCY, duration))

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - t0
                name = event_name or f"{func.__name__}_latency"
                logger = get_logger(func.__module__)
                logger.info(json.dumps({
                    "event": name,
                    "duration_s": round(duration, 3)
                }))
                # Note: Sync recording to Redis is not trivial without a loop
                # In this project, most traced things are async.

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
