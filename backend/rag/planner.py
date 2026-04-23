"""
Deterministic Hybrid Retrieval Planner.

Builds a HybridQueryPlan from user_query + context.
No LLM. Pure keyword + alias matching.

Input:  query, owner_id, user_profile (optional), system_context (optional)
Output: HybridQueryPlan
"""
from __future__ import annotations

import re
from typing import Optional

from core.logger import get_logger
from rag.router import (
    _CURRENCY_ALIASES,
    _MACRO_MAP,
    _VALID_SERIES_IDS,
    _KNOWN_ISO,
    _extract_currencies,
    _apply_fx_direction,
)
from rag.schemas import HybridQueryPlan, PlanStep, VectorFilter, PlanMeta

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_STEPS = 3

_FILING_KEYWORDS = [
    "10-k", "10-q", "10k", "10q", "annual report", "quarterly report",
    "sec filing", "filing", "prospectus", "8-k", "8k",
]
_DOCUMENT_KEYWORDS = [
    "summarize", "summary", "document", "uploaded", "pdf",
    "סכם", "מסמך",
]
_CONTEXTUAL_KEYWORDS = [
    "impact", "affect", "affects", "effect", "risk", "risks",
    "analysis", "analyze", "analyse", "advice", "advise",
    "recommend", "should i", "should we", "why", "how does",
    "how do", "explain", "interpret", "implication", "implications",
    "strategy",
    "השפעה", "ניתוח", "סיכון", "המלצה",
]
_ETF_KEYWORDS = ["etf", "etfs", "composition", "holdings", "positions", "largest", "top holdings", "החזקות", "הרכב"]
_PRICE_KEYWORDS = ["price", "stock", "close", "open", "מניה", "מחיר", "performance"]

# Uppercase words that must not be treated as tickers
_NON_TICKERS = {
    "USD", "ILS", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
    "CEO", "CFO", "CTO", "COO", "SEC", "ETF", "IPO",
    "GDP", "CPI", "FED", "IMF", "US", "AI", "IT", "UK",
    "EU", "FX", "OR", "IN", "AT", "BY", "DO", "IS", "AN",
    "TO", "BE", "ON", "OF", "AM", "PM",
    # Exclude single letters (junk from SPDR, S&P, etc.)
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
}

_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')

# SQL template IDs referenced by the Executor
_SQL_TEMPLATE_IDS = {
    "fx_rate": "fx_rate_latest",
    "price_lookup": "price_lookup_30d",
    "macro_series": "macro_series_12",
    "etf_holdings": "etf_holdings_top20",
}

# vector doc_type per intent
_DOC_TYPE_MAP: dict[str, str | None] = {
    "filing_lookup": "filing",
    "document_lookup": "upload",
    "knowledge_query": "knowledge",
    "no_match": None,
}

# profile hint is useful for these intents
_PROFILE_RELEVANT = {"macro_series", "knowledge_query", "no_match"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _lc(text: str) -> str:
    return text.lower()


def _has_any(text: str, keywords: list[str]) -> bool:
    q = _lc(text)
    return any(kw in q for kw in keywords)


def _extract_explicit_ticker(text: str) -> Optional[str]:
    """Returns first 2–5 char uppercase word that is not a known non-ticker."""
    for m in _TICKER_RE.finditer(text):
        candidate = m.group(1)
        if candidate not in _NON_TICKERS:
            return candidate
    return None


def _extract_all_tickers(text: str) -> list[str]:
    """Returns all unique 2–5 char uppercase words that are not known non-tickers, in order."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _TICKER_RE.finditer(text):
        candidate = m.group(1)
        if candidate not in _NON_TICKERS and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


# ── Intent detection ──────────────────────────────────────────────────────────

def _detect_intents(query: str, system_context: dict) -> list[dict]:
    """
    Returns list of intent dicts: {intent_type, raw_params, is_sql}.
    SQL intents first, then vector intents. Capped at _MAX_STEPS.
    """
    q = _lc(query)
    intents: list[dict] = []

    # 1. fx_rate: ≥2 currencies, or 1 currency + exchange/convert keyword
    currencies = _extract_currencies(query)
    if len(currencies) >= 2 or (
        len(currencies) == 1
        and any(kw in q for kw in ["exchange", "convert", "שער", "המרה"])
    ):
        intents.append({"intent_type": "fx_rate", "raw_params": {}, "is_sql": True})

    # 2. macro_series: first matching keyword in _MACRO_MAP
    for kw, series_id in _MACRO_MAP.items():
        if kw in q:
            intents.append({
                "intent_type": "macro_series",
                "raw_params": {"series_id": series_id},
                "is_sql": True,
            })
            break

    # 3. price_lookup / etf_holdings: requires explicit uppercase ticker
    ticker = _extract_explicit_ticker(query)
    if ticker:
        if _has_any(query, _ETF_KEYWORDS):
            # One SQL step per ticker — supports "compare SPY and QQQ" multi-symbol queries
            for t in _extract_all_tickers(query)[:_MAX_STEPS]:
                intents.append({
                    "intent_type": "etf_holdings",
                    "raw_params": {"symbol": t},
                    "is_sql": True,
                })
        elif _has_any(query, _PRICE_KEYWORDS):
            intents.append({
                "intent_type": "price_lookup",
                "raw_params": {"ticker": ticker},
                "is_sql": True,
            })

    # 4. filing_lookup: SEC filing keywords
    if _has_any(query, _FILING_KEYWORDS):
        intents.append({
            "intent_type": "filing_lookup",
            "raw_params": {"ticker": ticker},  # may be None
            "is_sql": False,
        })

    # 5. document_lookup: uploaded doc keywords (only if no filing intent already)
    elif _has_any(query, _DOCUMENT_KEYWORDS) and not any(
        i["intent_type"] == "filing_lookup" for i in intents
    ):
        intents.append({"intent_type": "document_lookup", "raw_params": {}, "is_sql": False})

    # 6. no intent detected → no_match
    if not intents:
        return [{"intent_type": "no_match", "raw_params": {}, "is_sql": False}]

    # 7. Hybrid: add knowledge_query VECTOR step if SQL steps exist + contextual keywords
    #    but no vector step yet (filing/document already satisfy this if present)
    #    SKIP for pure etf_holdings comparisons (e.g., "Compare SPY and QQQ") — keep factual
    has_sql = any(i["is_sql"] for i in intents)
    has_vector = any(not i["is_sql"] for i in intents)
    all_etf_holdings = all(i["intent_type"] == "etf_holdings" for i in intents if i.get("is_sql"))
    if has_sql and not has_vector and _has_any(query, _CONTEXTUAL_KEYWORDS) and not all_etf_holdings:
        intents.append({"intent_type": "knowledge_query", "raw_params": {}, "is_sql": False})

    return intents[:_MAX_STEPS]


# ── SQL param resolution ──────────────────────────────────────────────────────

def _resolve_sql(intent: dict, query: str) -> tuple[dict, Optional[str]]:
    """Returns (validated_params, error). error=None means valid."""
    itype = intent["intent_type"]
    raw = intent["raw_params"]

    if itype == "fx_rate":
        params, error = _apply_fx_direction({}, query)
        if error:
            return {}, error
        if params.get("base") not in _KNOWN_ISO or params.get("quote") not in _KNOWN_ISO:
            return {}, f"fx_rate: invalid pair {params}"
        return params, None

    if itype == "macro_series":
        sid = raw.get("series_id", "")
        if sid not in _VALID_SERIES_IDS:
            return {}, f"macro_series: invalid series_id '{sid}'"
        return {"series_id": sid}, None

    if itype == "price_lookup":
        t = raw.get("ticker", "")
        if not re.match(r"^[A-Z]{1,5}$", t):
            return {}, f"price_lookup: invalid ticker '{t}'"
        return {"ticker": t}, None

    if itype == "etf_holdings":
        s = raw.get("symbol", "")
        if not re.match(r"^[A-Z]{1,5}$", s):
            return {}, f"etf_holdings: invalid symbol '{s}'"
        return {"symbol": s}, None

    return {}, f"unknown sql intent: {itype}"


# ── Profile annotator ─────────────────────────────────────────────────────────

def _profile_hint(intent_type: str, user_profile: Optional[dict]) -> Optional[dict]:
    if not user_profile or intent_type not in _PROFILE_RELEVANT:
        return None
    hint: dict = {}
    if rt := user_profile.get("risk_tolerance"):
        hint["risk_tolerance"] = rt
    if el := user_profile.get("experience_level"):
        hint["experience_level"] = el
    return hint or None


# ── Public entry point ────────────────────────────────────────────────────────

def build_plan(
    query: str,
    owner_id: str,
    user_profile: Optional[dict] = None,
    system_context: Optional[dict] = None,
) -> HybridQueryPlan:
    """
    Deterministic planner. No LLM. Returns HybridQueryPlan.

    Args:
        query:          Raw user query (English or Hebrew).
        owner_id:       Tenant identifier — injected into all vector filters.
        user_profile:   Optional dict with risk_tolerance, experience_level.
        system_context: Optional dict with flags (has_portfolio, has_documents).
    """
    raw_intents = _detect_intents(query, system_context or {})

    # Pre-compute whether plan will be hybrid (for execution_mode assignment)
    will_be_hybrid = any(i["is_sql"] for i in raw_intents) and any(
        not i["is_sql"] for i in raw_intents
    )

    steps: list[PlanStep] = []
    has_sql = False
    has_vector = False

    for idx, intent in enumerate(raw_intents, start=1):
        itype = intent["intent_type"]

        if intent.get("is_sql"):
            params, error = _resolve_sql(intent, query)
            if error:
                logger.warning(f"planner: {itype} → NO_MATCH ({error})")
                steps.append(PlanStep(
                    step_id=idx,
                    source_type="NO_MATCH",
                    intent_type=itype,
                    parameters={},
                    sql_template_id=None,
                    vector_filter=VectorFilter(owner_id=owner_id),
                    priority=1,
                    execution_mode="sequential",
                    profile_hint=_profile_hint(itype, user_profile),
                ))
                has_vector = True
            else:
                steps.append(PlanStep(
                    step_id=idx,
                    source_type="SQL",
                    intent_type=itype,
                    parameters=params,
                    sql_template_id=_SQL_TEMPLATE_IDS.get(itype),
                    vector_filter=None,
                    priority=1,
                    execution_mode="parallel" if will_be_hybrid else "sequential",
                    profile_hint=_profile_hint(itype, user_profile),
                ))
                has_sql = True
        else:
            raw_ticker = intent["raw_params"].get("ticker")
            ticker_val = raw_ticker if isinstance(raw_ticker, str) else None
            steps.append(PlanStep(
                step_id=idx,
                source_type="VECTOR" if itype != "no_match" else "NO_MATCH",
                intent_type=itype,
                parameters={},
                sql_template_id=None,
                vector_filter=VectorFilter(
                    owner_id=owner_id,
                    doc_type=_DOC_TYPE_MAP.get(itype),
                    ticker=ticker_val,
                ),
                priority=1,
                execution_mode="parallel" if (will_be_hybrid and itype != "no_match") else "sequential",
                profile_hint=_profile_hint(itype, user_profile),
            ))
            has_vector = True

    return HybridQueryPlan(
        steps=steps,
        plan_meta=PlanMeta(
            total_steps=len(steps),
            is_hybrid=has_sql and has_vector,
            fusion_required=has_sql and has_vector or len(steps) > 1,
        ),
    )
