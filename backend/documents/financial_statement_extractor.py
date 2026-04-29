"""
documents/financial_statement_extractor.py — Deterministic financial statement extraction (Step 5C).

Extracts structured fields from savings / pension / gemel / hishtalmut statements.

Rules:
- No LLM. No OCR. Regex + line scanning only.
- All field extractors return None on no-match or exception — never raise.
- No results (all fields None) returns None from the top-level function.
- Partial extraction (some fields None) is a valid success — stored as-is.
- source text is never logged.
"""

import re
from dataclasses import dataclass
from datetime import date

_ELIGIBLE_DOC_TYPES = frozenset({"savings_statement"})

# Scan first 2000 chars for identity fields (provider, account_type, account_number).
_IDENTITY_SCAN_CHARS = 2000

# Known Israeli provider names with aliases.
_PROVIDER_PATTERNS: list[tuple[str, str]] = [
    (r"אלטשולר\s*שחם", "אלטשולר שחם"),
    (r"altschuler\s*shaham", "אלטשולר שחם"),
    (r"מגדל", "מגדל"),
    (r"magal|migdal", "מגדל"),
    (r"הפניקס", "הפניקס"),
    (r"phoenix", "הפניקס"),
    (r"כלל", "כלל"),
    (r"clal", "כלל"),
    (r"מנורה", "מנורה"),
    (r"menora", "מנורה"),
    (r"הראל", "הראל"),
    (r"harel", "הראל"),
    (r"מיטב\s*דש", "מיטב דש"),
    (r"meitav\s*dash", "מיטב דש"),
    (r"מיטב", "מיטב"),
    (r"meitav", "מיטב"),
]

# Account type keyword → canonical value
_ACCOUNT_TYPE_MAP: list[tuple[str, str]] = [
    (r"קופת\s*גמל\s*להשקעה", "gemel_lehashkaa"),
    (r"קופת\s*גמל", "gemel"),
    (r"גמל\s*להשקעה", "gemel_lehashkaa"),
    (r"גמל", "gemel"),
    (r"קרן\s*השתלמות", "hishtalmut"),
    (r"השתלמות", "hishtalmut"),
    (r"קרן\s*פנסיה", "pension"),
    (r"פנסיה", "pension"),
]

# Account number: support Hebrew and English labels
_ACCOUNT_NUMBER_RE = re.compile(
    r"(?:מספר\s+חשבון(?:\s+העמית)?|account\s+(?:no\.?|number|#))[:\s]*(\d[\d\-]{4,17})",
    re.IGNORECASE,
)

# Date patterns: DD/MM/YYYY or DD.MM.YYYY
_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

# Period range: two dates separated by a dash/en-dash
_PERIOD_RE = re.compile(
    r"(\d{1,2}[./]\d{1,2}[./]\d{4})\s*[-–—]\s*(\d{1,2}[./]\d{1,2}[./]\d{4})"
)

# Amount value: digits with optional commas, optional ₪/NIS prefix/suffix
_AMOUNT_VALUE_RE = re.compile(r"[\u20aa$]?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:₪|NIS)?")

# Report date anchors (Hebrew + English)
_REPORT_DATE_ANCHORS = re.compile(
    r"(?:תאריך\s+(?:הדוח|דוח)|report\s+date|as\s+of)[:\s]*(\d{1,2}[./]\d{1,2}[./]\d{4})",
    re.IGNORECASE,
)

# Ending balance anchors
_ENDING_BALANCE_ANCHORS = re.compile(
    r"(?:יתרה\s+לסוף|יתרה\s+סופית|סך\s+יתרה|ending\s+balance|יתרה\s+לתאריך)[:\s]*",
    re.IGNORECASE,
)

# Annual deposits anchors
_DEPOSITS_ANCHORS = re.compile(
    r"(?:הפקדות\s+במהלך\s+השנה|סך\s+הפקדות|annual\s+deposits?|הפקדות)[:\s]*",
    re.IGNORECASE,
)

# Investment gains anchors — intentionally excludes תשואה (percentage, not amount)
_INVESTMENT_GAINS_ANCHORS = re.compile(
    r"(?:רווחים\s+בניכוי\s+הוצאות\s+ניהול\s+השקעות|רווחי\s+השקעה|investment\s+gains?)[:\s]*",
    re.IGNORECASE,
)

# Management fees anchors
_MGMT_FEES_ANCHORS = re.compile(
    r"(?:דמי\s+ניהול|management\s+fees?)[:\s]*",
    re.IGNORECASE,
)

# Track name anchors
_TRACK_NAME_RE = re.compile(
    r"(?:מסלול(?:\s+ההשקעה)?|investment\s+track)[:\s]+(.{3,60}?)(?:\n|$)",
    re.IGNORECASE,
)

# Percentage pattern
_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)%")

# Equity exposure: lines containing מניות / equity
_EQUITY_LINE_KW = re.compile(r"מניות|equity", re.IGNORECASE)

# FX exposure: lines containing מט"ח / מטח / foreign currency / fx
_FX_LINE_KW = re.compile(r'מט["\u05f4]?ח|מטח|foreign\s+currency|\bfx\b', re.IGNORECASE)


@dataclass
class FinancialStatementData:
    provider:            str | None
    account_type:        str | None
    account_number:      str | None
    report_date:         str | None   # "YYYY-MM-DD"
    period_start:        str | None   # "YYYY-MM-DD"
    period_end:          str | None   # "YYYY-MM-DD"
    ending_balance:      float | None
    annual_deposits:     float | None
    investment_gains:    float | None
    management_fees:     float | None
    track_name:          str | None
    equity_exposure_pct: float | None
    fx_exposure_pct:     float | None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_date(raw: str) -> str | None:
    """
    Parse DD/MM/YYYY or DD.MM.YYYY → "YYYY-MM-DD".
    Returns None for invalid or impossible dates.
    """
    m = _DATE_RE.search(raw)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(year, month, day)
        return d.isoformat()
    except ValueError:
        return None


def _parse_amount(raw: str) -> float | None:
    """
    Parse a monetary amount string.
    Strips ₪, NIS, commas. Rejects <= 0 or > 100_000_000.
    Returns None on any failure.
    """
    # Remove currency symbols and whitespace noise
    cleaned = raw.replace("₪", "").replace("NIS", "").replace(",", "").strip()
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if val <= 0 or val > 100_000_000:
        return None
    return val


def _extract_amount_after_anchor(text: str, anchor_re: re.Pattern) -> float | None:
    """
    Find the anchor in text, then extract the first numeric amount on the same line
    within 120 characters after the anchor match.
    """
    m = anchor_re.search(text)
    if not m:
        return None
    tail = text[m.end():m.end() + 120]
    # Take only up to the first newline
    tail = tail.split("\n")[0]
    am = _AMOUNT_VALUE_RE.search(tail)
    if not am:
        return None
    return _parse_amount(am.group(1))


def _extract_provider(text: str) -> str | None:
    scan = text[:_IDENTITY_SCAN_CHARS].lower()
    # Also try full text as fallback for multi-page PDFs where header may appear late
    full_lower = text.lower()
    for pattern, canonical in _PROVIDER_PATTERNS:
        if re.search(pattern, scan, re.IGNORECASE) or re.search(pattern, full_lower, re.IGNORECASE):
            return canonical
    return None


def _extract_account_type(text: str) -> str | None:
    scan = text[:_IDENTITY_SCAN_CHARS]
    for pattern, canonical in _ACCOUNT_TYPE_MAP:
        if re.search(pattern, scan):
            return canonical
    return None


def _extract_account_number(text: str) -> str | None:
    scan = text[:_IDENTITY_SCAN_CHARS]
    m = _ACCOUNT_NUMBER_RE.search(scan)
    if m:
        return m.group(1).strip()
    return None


def _extract_report_date(text: str) -> str | None:
    m = _REPORT_DATE_ANCHORS.search(text)
    if m:
        return _parse_date(m.group(1))
    return None


def _extract_period(text: str) -> tuple[str | None, str | None]:
    """Return (period_start, period_end) or (None, None)."""
    m = _PERIOD_RE.search(text)
    if not m:
        return None, None
    return _parse_date(m.group(1)), _parse_date(m.group(2))


def _extract_track_name(text: str) -> str | None:
    m = _TRACK_NAME_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    return name if name else None


def _extract_exposure_pct(text: str, kw_re: re.Pattern) -> float | None:
    """
    Line-based: find the first line matching kw_re, extract the first percentage on that line.
    """
    for line in text.splitlines():
        if kw_re.search(line):
            pm = _PCT_RE.search(line)
            if pm:
                try:
                    val = float(pm.group(1))
                    if 0 <= val <= 100:
                        return val
                except ValueError:
                    pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def extract_financial_statement(text: str, doc_type: str) -> FinancialStatementData | None:
    """
    Extract structured fields from a savings / pension statement.

    Args:
        text:     Full extracted document text.
        doc_type: Classified document type (Step 5A).

    Returns:
        FinancialStatementData with any found fields populated.
        Returns None when doc_type is ineligible, text is empty, or all fields are None.
        Never raises.
    """
    if doc_type not in _ELIGIBLE_DOC_TYPES:
        return None

    if not text or not text.strip():
        return None

    try:
        provider        = _extract_provider(text)
        account_type    = _extract_account_type(text)
        account_number  = _extract_account_number(text)
        report_date     = _extract_report_date(text)
        period_start, period_end = _extract_period(text)
        ending_balance  = _extract_amount_after_anchor(text, _ENDING_BALANCE_ANCHORS)
        annual_deposits = _extract_amount_after_anchor(text, _DEPOSITS_ANCHORS)
        investment_gains = _extract_amount_after_anchor(text, _INVESTMENT_GAINS_ANCHORS)
        management_fees = _extract_amount_after_anchor(text, _MGMT_FEES_ANCHORS)
        track_name      = _extract_track_name(text)
        equity_exposure_pct = _extract_exposure_pct(text, _EQUITY_LINE_KW)
        fx_exposure_pct     = _extract_exposure_pct(text, _FX_LINE_KW)
    except Exception:
        return None

    data = FinancialStatementData(
        provider=provider,
        account_type=account_type,
        account_number=account_number,
        report_date=report_date,
        period_start=period_start,
        period_end=period_end,
        ending_balance=ending_balance,
        annual_deposits=annual_deposits,
        investment_gains=investment_gains,
        management_fees=management_fees,
        track_name=track_name,
        equity_exposure_pct=equity_exposure_pct,
        fx_exposure_pct=fx_exposure_pct,
    )

    # Return None only when every single field is None
    if all(
        getattr(data, f) is None
        for f in data.__dataclass_fields__
    ):
        return None

    return data
