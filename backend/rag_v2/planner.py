from __future__ import annotations

import re
from typing import Dict, Optional

from rag_v2.schemas import NormalizedQuestion, QueryPlanV2


_CURRENCY_ALIASES: Dict[str, str] = {
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "דולר": "USD",
    "הדולר": "USD",
    "ils": "ILS",
    "nis": "ILS",
    "shekel": "ILS",
    "shekels": "ILS",
    "שקל": "ILS",
    "השקל": "ILS",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "אירו": "EUR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "jpy": "JPY",
    "yen": "JPY",
    "cad": "CAD",
    "aud": "AUD",
    "chf": "CHF",
    "franc": "CHF",
}

_MACRO_KEYWORDS: Dict[str, str] = {
    "inflation": "CPIAUCNS",
    "cpi": "CPIAUCNS",
    "אינפלציה": "CPIAUCNS",
    "interest rate": "FEDFUNDS",
    "fed rate": "FEDFUNDS",
    "federal funds": "FEDFUNDS",
    "ריבית": "FEDFUNDS",
    "gdp": "GDP",
    "תוצר": "GDP",
    "unemployment": "UNRATE",
    "jobless": "UNRATE",
    "אבטלה": "UNRATE",
}

_HOLDINGS_KEYWORDS = ("holding", "holdings", "composition", "אחזקות", "החזקות")
_PRICE_KEYWORDS = ("price", "close", "trading at", "stock price", "מחיר", "שער")
_FX_KEYWORDS = ("fx", "exchange rate", "rate", "currency", "מטבע", "שער", "מול")
_STOPWORDS = {
    "what",
    "are",
    "the",
    "top",
    "of",
    "for",
    "latest",
    "current",
    "is",
    "show",
    "me",
    "a",
    "an",
    "and",
    "to",
    "at",
    "price",
    "stock",
    "holding",
    "holdings",
    "composition",
    "rate",
    "exchange",
    "fx",
    "inflation",
    "gdp",
    "interest",
    "unemployment",
    "series",
    "macro",
    "fund",
    "etf",
    "what's",
    "whats",
    "מה",
    "של",
    "את",
    "על",
    "מול",
    "עם",
    "מחיר",
    "שער",
    "מניה",
    "אחזקות",
    "החזקות",
    "בדוק",
    "רשום",
}


def build_plans(normalized: NormalizedQuestion) -> list[QueryPlanV2]:
    """Return all matching plans for a question (may be more than one for multi-intent queries)."""
    text = normalized.canonical_question
    original = normalized.original_question
    currencies = _extract_currencies(text)
    plans: list[QueryPlanV2] = []

    if _matches_holdings(text):
        ticker = _extract_symbol(original)
        if ticker:
            sql = (
                "SELECT etf_symbol, holding_symbol, weight, date "
                f"FROM etf_holdings WHERE etf_symbol='{ticker}' "
                "ORDER BY weight DESC LIMIT 5"
            )
            plans.append(QueryPlanV2(
                intent="etf_holdings",
                source="sql",
                supported=True,
                query_template="top_etf_holdings",
                sql=sql,
                params={"symbol": ticker},
            ))

    if _matches_fx(text):
        if len(currencies) == 2:
            base_currency, quote_currency = currencies
            sql = (
                "SELECT base_currency, quote_currency, rate, date "
                f"FROM fx_rates WHERE base_currency='{base_currency}' "
                f"AND quote_currency='{quote_currency}' "
                "ORDER BY date DESC LIMIT 5"
            )
            plans.append(QueryPlanV2(
                intent="fx_rate",
                source="sql",
                supported=True,
                query_template="latest_fx_rate",
                sql=sql,
                params={
                    "base_currency": base_currency,
                    "quote_currency": quote_currency,
                },
            ))

    if _matches_price(text):
        ticker = _extract_symbol(original)
        if ticker:
            sql = (
                "SELECT symbol, close, date "
                f"FROM prices WHERE symbol='{ticker}' "
                "ORDER BY date DESC LIMIT 5"
            )
            plans.append(QueryPlanV2(
                intent="price_lookup",
                source="sql",
                supported=True,
                query_template="latest_price_history",
                sql=sql,
                params={"symbol": ticker},
            ))

    macro_series = _extract_macro_series(text)
    if macro_series:
        sql = (
            "SELECT series_id, value, date "
            f"FROM macro_series WHERE series_id='{macro_series}' "
            "ORDER BY date DESC LIMIT 5"
        )
        plans.append(QueryPlanV2(
            intent="macro_series",
            source="sql",
            supported=True,
            query_template="macro_series_recent",
            sql=sql,
            params={"series_id": macro_series},
        ))

    return plans


def _matches_holdings(text: str) -> bool:
    return any(keyword in text for keyword in _HOLDINGS_KEYWORDS)


def _matches_price(text: str) -> bool:
    return any(keyword in text for keyword in _PRICE_KEYWORDS)


def _matches_fx(text: str) -> bool:
    currencies = _extract_currencies(text)
    if len(currencies) != 2:
        return False
    return (
        any(keyword in text for keyword in _FX_KEYWORDS)
        or "/" in text
        or " to " in text
    )


def _extract_symbol(original_question: str) -> Optional[str]:
    """Extract a single ticker symbol from the original (pre-normalization) question.

    Looks for 1–5 character uppercase tokens (letters and digits) that are not
    all-digit. Accepts alphanumeric tickers like XYZ123 as well as pure-letter
    ones like AAPL. Falls back to None when zero or multiple candidates remain
    after filtering known stopwords.
    """
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{0,4}\b", original_question)
    stopwords_upper = {w.upper() for w in _STOPWORDS}
    filtered = [t for t in candidates if t not in stopwords_upper and not t.isdigit()]
    if len(filtered) != 1:
        return None
    return filtered[0]


def _extract_currencies(text: str) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[a-z\u0590-\u05FF]+", text):
        currency = _CURRENCY_ALIASES.get(token)
        if currency and currency not in found:
            found.append(currency)
    return found


def _extract_macro_series(text: str) -> Optional[str]:
    for keyword, series_id in _MACRO_KEYWORDS.items():
        if keyword in text:
            return series_id
    return None


def _unsupported(reason: str) -> QueryPlanV2:
    return QueryPlanV2(
        intent="unsupported",
        source="none",
        supported=False,
        reason=reason,
    )
