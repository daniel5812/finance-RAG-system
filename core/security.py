"""
core/security.py — Input validation + output filtering.
Prompt injection detection and PII content filter.
"""

import re
import json
from core.config import BUFFER_LIMIT, OVERLAP_SIZE
from core.logger import get_logger

logger = get_logger(__name__)

# ── Prompt Injection Detection ──

INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)', re.I),
    re.compile(r'you\s+are\s+now\s+', re.I),
    re.compile(r'system\s*:\s*', re.I),
    re.compile(r'\bforget\s+(everything|all|your)\b', re.I),
    re.compile(r'act\s+as\s+(if|a|an)\s+', re.I),
    re.compile(r'disregard\s+(all|any|your)\s+', re.I),
    re.compile(r'new\s+instructions?\s*:', re.I),
    re.compile(r'\bdo\s+not\s+follow\b', re.I),
]


def detect_prompt_injection(text: str) -> bool:
    """Return True if text contains prompt injection patterns."""
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ── Content Filter (PII / Sensitive Data) ──

BLOCKED_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b', re.I),   # Email
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),                                     # SSN
    re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),                   # Credit card
]


def content_filter(text: str) -> tuple[str, bool]:
    """Scan text for dangerous patterns. Returns (safe_text, was_filtered)."""
    filtered = False
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(text):
            text = pattern.sub("[FILTERED]", text)
            filtered = True
            if filtered:
                logger.warning(json.dumps({"event": "content_filtered", "pattern_type": pattern.pattern[:20]}))
    return text, filtered
