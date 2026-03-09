"""
core/logger.py — Structured JSON logging for all modules.
Usage: from core.logger import get_logger
       logger = get_logger(__name__)
"""

import json
import logging
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
