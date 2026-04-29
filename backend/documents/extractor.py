"""
documents/extractor.py — Deterministic holdings extraction (Step 5B).

Extracts (ticker, quantity) candidates from broker_statement and
portfolio_statement documents only.

Rules:
- No LLM. No OCR. Regex + line scanning only.
- Invalid lines → skipped silently.
- No results is not an error.
- source_line stored for internal audit — never logged.
"""

import re
from dataclasses import dataclass

_ELIGIBLE_DOC_TYPES = frozenset({"broker_statement", "portfolio_statement"})

_NOISE_TICKERS = frozenset({
    "CASH", "TOTAL", "DATE", "PAGE", "FUND", "NULL", "ETF",
    "NET", "YTD", "QTD", "MTD", "NA", "TBD", "USD", "GBP",
})

_NOISE_LINE_PREFIXES = frozenset({
    "total", "subtotal", "page", "date", "balance", "net",
    "cash", "grand", "summary", "account", "as", "period",
})

# Matches: plain AAPL, parenthesized (AAPL), class shares BRK.B or BRK-B
_TICKER_PATTERN = re.compile(r'\(?([A-Z]{1,5}(?:[.\-][A-Z])?)\)?')

# Minimum line length after strip to be worth parsing
_MIN_LINE_LEN = 8


@dataclass
class CandidateHolding:
    ticker: str
    quantity: float | None
    source_line: str          # raw line — for audit only, never logged, not exposed via API
    confidence: str           # 'high' | 'low'


def _extract_ticker_from_tokens(tokens: list[str]) -> str | None:
    """
    Find the first valid ticker in a list of tokens.

    Handles:
    - Plain form: AAPL
    - Parenthesized: (AAPL)
    - Class shares: BRK.B, BRK-B (normalized to BRK.B)

    Returns normalized ticker or None if no valid ticker found.
    """
    for token in tokens:
        match = _TICKER_PATTERN.fullmatch(token)
        if match:
            ticker = match.group(1)
            # Normalize class share delimiter: BRK-B → BRK.B
            ticker = ticker.replace("-", ".")
            # Validate base ticker (before any class suffix)
            base = ticker.split(".")[0]
            if base not in _NOISE_TICKERS and len(base) <= 5:
                return ticker
    return None


def _is_numeric_like(token: str) -> bool:
    """
    Check if a token looks like a number (for early stopping in quantity scan).
    Returns True even if the number is invalid (zero, negative, too large).
    """
    cleaned = token.replace(",", "").replace("$", "").lstrip("+")
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _parse_quantity(token: str) -> float | None:
    """
    Try to parse a whitespace-stripped token as a share quantity.
    Returns None if the token is not a valid positive quantity < 1,000,000.
    """
    # Reject percentage values
    if token.endswith("%"):
        return None
    cleaned = token.replace(",", "").replace("$", "").lstrip("+")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if val <= 0 or val >= 1_000_000:
        return None
    return val


def _is_noisy_line(line: str) -> bool:
    if len(line) < _MIN_LINE_LEN:
        return True
    first_word = line.split()[0].lower()
    return first_word in _NOISE_LINE_PREFIXES


def extract_holdings(text: str, doc_type: str) -> list[CandidateHolding]:
    """
    Extract (ticker, quantity) candidates from extracted document text.

    Args:
        text:     Full extracted document text.
        doc_type: Classified document type from Step 5A.

    Returns:
        List of CandidateHolding. Empty list when doc_type is ineligible,
        no candidates are found, or text is empty. Never raises.

    Decision per line:
        - Skip if line too short or starts with noise prefix.
        - Find the first valid ticker token (plain, parenthesized, or class-share form).
        - After ticker, find the first parseable positive numeric token → quantity.
        - confidence = 'high' if quantity found, else 'low'.
        - Duplicates are allowed (same ticker may appear on multiple lines).
    """
    if doc_type not in _ELIGIBLE_DOC_TYPES:
        return []

    if not text or not text.strip():
        return []

    results: list[CandidateHolding] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if _is_noisy_line(line):
            continue

        tokens = line.split()

        # Find the first valid ticker (handles plain, parenthesized, class shares)
        ticker = _extract_ticker_from_tokens(tokens)
        if ticker is None:
            continue

        # Find the index of the ticker token in the original list
        # (needed to search for quantity after the ticker position)
        ticker_idx = -1
        for i, token in enumerate(tokens):
            if _TICKER_PATTERN.fullmatch(token):
                normalized = _TICKER_PATTERN.fullmatch(token).group(1).replace("-", ".")
                if normalized == ticker:
                    ticker_idx = i
                    break

        # Find the first valid quantity after the ticker.
        # Rule: skip percentages (continue scanning), but stop on any other numeric-like token
        # (even if invalid: zero, negative, too large).
        quantity: float | None = None
        if ticker_idx >= 0:
            for token in tokens[ticker_idx + 1:]:
                # Percentages are explicitly rejected; continue scanning for next numeric
                if token.endswith("%"):
                    continue
                # If this token looks numeric, try to parse it. Stop here regardless of validity.
                if _is_numeric_like(token):
                    quantity = _parse_quantity(token)
                    break
                # Non-numeric token; continue scanning

        confidence = "high" if quantity is not None else "low"
        results.append(CandidateHolding(
            ticker=ticker,
            quantity=quantity,
            source_line=line,
            confidence=confidence,
        ))

    return results
