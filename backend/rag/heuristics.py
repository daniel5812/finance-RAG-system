import re
from typing import Optional
from rag.schemas import QueryPlan, MultiQueryPlan

# ── Entity Mapping & Normalization ──

TICKER_MAP = {
    "S&P 500": "SPY",
    "S&P": "SPY",
    "SP500": "SPY",
    "NASDAQ 100": "QQQ",
    "NASDAQ": "QQQ",
    "QQQ": "QQQ",
    "SPY": "SPY",
    "VTI": "VTI",
}

CURRENCY_MAP = {
    "DOLLAR": "USD",
    "USD": "USD",
    "SHEKEL": "ILS",
    "ILS": "ILS",
    "NIS": "ILS",
    "EURO": "EUR",
    "EUR": "EUR",
}

MACRO_MAP = {
    "INFLATION": "CPIAUCNS",
    "CPI": "CPIAUCNS",
    "GDP": "GDP",
    "UNEMPLOYMENT": "UNRATE",
}

class FinancialHeuristics:
    """
    Lightweight rule-based classifier to bypass LLM Router for common queries.
    Target latency: < 5ms.
    """

    @staticmethod
    def extract_entities(text: str) -> dict:
        text_upper = text.upper()
        
        entities = {
            "tickers": [],
            "currencies": [],
            "macro": []
        }

        # 1. Tickers (mapping + regex)
        for key, val in TICKER_MAP.items():
            if key in text_upper:
                entities["tickers"].append(val)
        
        # Regex for potential tickers in quotes or $ prefix
        regex_tickers = re.findall(r"\$?([A-Z]{3,4})", text_upper)
        for t in regex_tickers:
            if t not in entities["tickers"]:
                entities["tickers"].append(t)

        # 2. Currencies
        for key, val in CURRENCY_MAP.items():
            if key in text_upper:
                entities["currencies"].append(val)

        # 3. Macro
        for key, val in MACRO_MAP.items():
            if key in text_upper:
                entities["macro"].append(val)

        # Deduplicate
        for k in entities:
            entities[k] = list(set(entities[k]))
            
        return entities

    @staticmethod
    def classify_intent(text: str, entities: dict) -> Optional[MultiQueryPlan]:
        text_lower = text.lower()
        
        # ── NotebookLM Guard ──
        # If the user asks for analysis, risks, reasons, or Hebrew "למה", "משמעות", "סיכון"
        # we ALWAYS go to the LLM Router for deep synthesis.
        analytical_keywords = [
            # English
            "why", "how", "reason", "risk", "insight", "impact", "analyze", "opinion",
            "exposure", "diversification", "performance", "comparison", "portfolio",
            "concentrated", "allocation", "suggest", "recommend", "strategy",
            # Hebrew
            "למה", "איך", "סיכון", "משמעות", "ניתוח", "השפעה", "כדאי", "חוות דעת",
            "חשיפה", "פיזור", "ביצועים", "השוואה", "תיק", "ריכוזיות", "הקצאה",
            "מציע", "אסטרטגיה", "המלצה",
        ]
        if any(kw in text_lower for kw in analytical_keywords):
            return None # Force LLM Router
            
        plans = []

        # Intent: ETF Holdings
        if ("holdings" in text_lower or "what is in" in text_lower) and entities["tickers"]:
            for ticker in entities["tickers"]:
                plans.append(QueryPlan(
                    source="sql",
                    query=f"SELECT * FROM etf_holdings WHERE etf_symbol='{ticker}' ORDER BY weight DESC LIMIT 10"
                ))

        # Intent: FX Rates
        if ("rate" in text_lower or "exchange" in text_lower or "price of" in text_lower) and entities["currencies"]:
            # If two currencies found, assume base/quote
            if len(entities["currencies"]) >= 2:
                base, quote = entities["currencies"][:2]
                plans.append(QueryPlan(
                    source="sql",
                    query=f"SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1"
                ))
            # If one currency found, assume USD to that currency if not USD, or USD to ILS if it is USD
            elif len(entities["currencies"]) == 1:
                cur = entities["currencies"][0]
                base, quote = ("USD", cur) if cur != "USD" else ("USD", "ILS")
                plans.append(QueryPlan(
                    source="sql",
                    query=f"SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1"
                ))

        # Intent: Macro Data
        if entities["macro"]:
            for series_id in entities["macro"]:
                plans.append(QueryPlan(
                    source="sql",
                    query=f"SELECT value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 1"
                ))

        if plans:
            return MultiQueryPlan(plans=plans)
        return None
