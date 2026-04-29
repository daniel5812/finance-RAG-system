"""
documents/classifier.py — Deterministic document type classification.

Rules:
- Content-only classification: extracted text only. Filename is ignored (user filenames unreliable).
- Keyword signals from ~500 chars of extracted text. No LLM. No OCR.
- confidence=low always forces doc_type='unknown' — no weak inferences.
"""

from typing import Literal

DocType = Literal[
    "broker_statement",
    "portfolio_statement",
    "bank_statement",
    "financial_report",
    "generic_financial_doc",
    "unknown",
]

Confidence = Literal["high", "medium", "low"]

# Keywords that strongly indicate a specific document type
_TYPE_SIGNALS: dict[str, list[str]] = {
    "broker_statement": [
        "broker", "brokerage", "trade confirmation", "transaction history",
        "account statement", "commission", "executed trade",
    ],
    "portfolio_statement": [
        "portfolio", "holdings", "investment summary", "asset allocation",
        "portfolio value", "position summary",
    ],
    "bank_statement": [
        "bank statement", "checking account", "savings account",
        "deposits", "withdrawals", "bank of", "checking", "savings",
    ],
    "financial_report": [
        "10-k", "10-q", "annual report", "earnings", "balance sheet",
        "income statement", "quarterly report", "fiscal year",
    ],
}

# Weak financial keywords — classify as generic if no specific type matches
_GENERIC_FINANCIAL_KEYWORDS = [
    "account", "balance", "investment", "fund", "equity", "dividend",
    "interest", "return", "capital", "financial", "statement", "report",
]


def _count_type_matches(text: str) -> dict[str, int]:
    """
    Count how many keywords from each type appear in text.
    Returns dict[doc_type -> match_count].
    """
    text_lower = text.lower()
    counts = {}
    for doc_type, keywords in _TYPE_SIGNALS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            counts[doc_type] = count
    return counts


def _has_generic_financial_signal(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _GENERIC_FINANCIAL_KEYWORDS)


def classify_document(filename: str, text_snippet: str) -> tuple[DocType, Confidence]:
    """
    Classify a financial document using deterministic keyword signals from content only.

    Args:
        filename:     Original uploaded filename (INTENTIONALLY IGNORED — user filenames unreliable).
        text_snippet: First ~500 chars of extracted document text (only source of truth).

    Returns:
        (doc_type, confidence) — confidence='low' always yields doc_type='unknown'.

    Decision matrix (content-only):
        1 specific type with 2+ keyword matches          → (type, 'high')
        1 specific type with 1 keyword match             → (type, 'medium')
        2+ specific types match (conflict)               → ('unknown', 'low')
        0 specific types + 2+ financial keywords         → ('generic_financial_doc', 'medium')
        0 specific types + <2 financial keywords         → ('unknown', 'low')
    """
    snippet = text_snippet[:500]

    # Count keyword matches per document type
    type_counts = _count_type_matches(snippet)

    # Resolve document type based on match counts
    if len(type_counts) == 1:
        # Exactly one type detected
        doc_type = list(type_counts.keys())[0]
        match_count = type_counts[doc_type]
        confidence = "high" if match_count >= 2 else "medium"
        return doc_type, confidence

    if len(type_counts) > 1:
        # Conflicting signals — multiple types detected
        return "unknown", "low"

    # No specific type detected — check for generic financial content
    generic_count = sum(1 for kw in _GENERIC_FINANCIAL_KEYWORDS if kw in snippet.lower())
    if generic_count >= 2:
        return "generic_financial_doc", "medium"

    # Nothing recognisable
    return "unknown", "low"
