import json
import logging
import time
import functools
import asyncio
from contextvars import ContextVar

# ── Request ID & User Context — propagated across threads/tasks ──
request_id_var: ContextVar[str] = ContextVar("request_id", default="none")
user_id_var: ContextVar[str] = ContextVar("user_id", default="none")

class StructuredFormatter(logging.Formatter):
    """Outputs logs as single-line JSON for machine parsing."""
    def format(self, record):
        message = record.getMessage()
        
        # Try to parse message as JSON if it looks like it, to avoid double-encoding
        event_data = message
        if isinstance(message, str) and message.startswith("{") and message.endswith("}"):
            try:
                event_data = json.loads(message)
            except Exception:
                pass

        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "event": event_data,
        }
        return json.dumps(log_entry, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that outputs structured JSON."""
    return logging.getLogger(name)


def setup_logging():
    """
    Unified logging setup. 
    1. Configures the root logger with the StructuredFormatter.
    2. Hijacks uvicorn loggers to use the same formatter.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)

    # Hijack uvicorn loggers
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uj_logger = logging.getLogger(logger_name)
        uj_logger.handlers = [handler]
        uj_logger.propagate = False  # prevent double logs if root also has handler

    root_logger.info("Structured logging system initialized and connected to uvicorn")


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
