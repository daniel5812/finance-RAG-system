import json
import re
from core.llm_client import RoutingAgentClient
from core.logger import get_logger, trace_latency
from rag.schemas import QueryPlan, MultiQueryPlan

logger = get_logger(__name__)

ROUTER_PROMPT = """You are a financial query planner. Your ONLY job is to classify user intent and extract parameters.

LANGUAGE: The user may write in Hebrew or English. You must understand both.
IMPORTANT: Always output parameters in English regardless of input language.
DO NOT translate the user's question. Only normalize parameter values to English codes.

DO NOT write SQL. DO NOT write code. Output ONLY valid JSON.

OUTPUT FORMAT (strict):
{
  "plans": [
    {
      "source": "<sql|vector>",
      "type": "<intent_type>",
      "params": { ... }
    }
  ]
}

INTENT TYPES AND REQUIRED PARAMS:

1. fx_rate (source: sql)
   Use when: user asks about exchange rates, currency conversion, FX
   Required params:
     - base: the base currency (string, e.g. "USD")
     - quote: the quote/target currency (string, e.g. "ILS")
   FX DIRECTION RULES (mandatory):
     - If both USD and ILS appear in any form → ALWAYS output base="USD", quote="ILS". Ignore word order.
     - If only one currency is mentioned:
         - If USD is present → base="USD", use the other currency as quote
         - If USD is absent → base="USD", quote=detected currency
     - Do NOT rely on sentence order to determine base vs quote.
   CURRENCY NORMALIZATION — you MUST output these exact codes:
     dollar, usd, us dollar, דולר, דולרים → "USD"
     shekel, nis, ils, israeli, שקל, שקלים → "ILS"
     euro, eur, אירו → "EUR"
     pound, gbp → "GBP"
     yen, jpy → "JPY"

2. price_lookup (source: sql)
   Use when: user asks about stock/ETF price, performance, historical price
   Required params:
     - ticker: the stock or ETF symbol (string, e.g. "AAPL", "SPY")
   VALIDATION: Only output tickers explicitly named in the question. DO NOT invent symbols.
   If ticker cannot be identified → DO NOT produce this plan, fallback to document_analysis.

3. macro_series (source: sql)
   Use when: user asks about macroeconomic indicators (inflation, CPI, interest rates, GDP, unemployment)
   Required params:
     - series_id: the FRED series identifier
   SERIES MAPPING — you MUST output these exact IDs:
     inflation, cpi, אינפלציה → "CPIAUCNS"
     interest rate, fed rate, federal funds, ריבית → "FEDFUNDS"
     gdp, gross domestic product, תוצר, תמ"ג → "GDP"
     unemployment, אבטלה → "UNRATE"
   If series cannot be mapped → DO NOT produce this plan, fallback to document_analysis.

4. etf_holdings (source: sql)
   Use when: user asks about ETF composition, what stocks are in an ETF
   Required params:
     - symbol: the ETF ticker (string, e.g. "SPY", "QQQ")

5. portfolio_analysis (source: sql)
   Use when: user asks about their portfolio, positions, holdings
   Required params: (none — owner_id is injected server-side)

6. document_analysis (source: vector)
   Use when: user asks for analysis, advice, interpretation, risks, insights, or any qualitative question
   Required params:
     - query: a concise, semantically optimized rewrite of the user's question
   QUERY REWRITE RULES:
     - Remove filler words ("what is", "can you tell me", "show me", "I want to know")
     - Preserve all financial terms and entities
     - Optimize for semantic similarity search
     - Example: "What are the risks of high inflation for bond investors?" → "inflation risk impact on bond investors"

7. investment_recommendation (source: vector)
   Use when: user asks for investment recommendations, buy/sell/hold advice, portfolio optimization,
             asset allocation, "should I buy/sell", "is X a good investment", "what should I invest in"
   Required params:
     - query: a concise rewrite optimized for retrieving investment research documents
     - tickers: list of ticker symbols explicitly mentioned (may be empty list [])
   Examples:
     "Should I buy Apple stock?" → query: "AAPL investment analysis risk reward", tickers: ["AAPL"]
     "What ETFs should I add to my portfolio?" → query: "ETF diversification portfolio allocation", tickers: []
     "Is now a good time to invest in tech?" → query: "technology sector investment outlook macro", tickers: []
   Hebrew examples:
     "האם כדאי לקנות מניות טכנולוגיה?" → query: "technology stocks investment outlook", tickers: []
     "מה לגבי AAPL?" → query: "AAPL investment analysis", tickers: ["AAPL"]

MISSING PARAMETERS:
- If required parameters for a plan type cannot be extracted → DO NOT produce that plan → output document_analysis instead.

VALIDATION:
- DO NOT invent ticker symbols. Only output tickers explicitly named in the question.
- DO NOT invent macro series IDs. Only use the FRED IDs listed above.
- If unsure → fallback to document_analysis.

MIXED QUERIES:
- If the question contains BOTH a structured data request (fx, price, macro, portfolio, etf)
  AND any of: analysis / impact / risk / advice / interpretation / why / how
  → return BOTH a sql plan AND a document_analysis plan.
- Do not collapse them into one.

HEBREW EXAMPLE:
Input: מה שער הדולר לשקל?
Output: {"plans": [{"source": "sql", "type": "fx_rate", "params": {"base": "USD", "quote": "ILS"}}]}

Output ONLY the JSON object. No explanation, no markdown, no code blocks."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KNOWN_ISO = {"USD", "ILS", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"}

_CURRENCY_ALIASES: dict[str, str] = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "us dollar": "USD",
    "shekel": "ILS", "shekels": "ILS", "nis": "ILS", "ils": "ILS", "israeli": "ILS",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP",
    "yen": "JPY", "jpy": "JPY",
    "franc": "CHF", "chf": "CHF",
    "cad": "CAD", "canadian dollar": "CAD",
    "aud": "AUD", "australian dollar": "AUD",
    # Hebrew
    "דולר": "USD", "דולרים": "USD",
    "שקל": "ILS", "שקלים": "ILS",
    "אירו": "EUR",
}

_MACRO_MAP: dict[str, str] = {
    "inflation": "CPIAUCNS",
    "cpi": "CPIAUCNS",
    "consumer price": "CPIAUCNS",
    "interest rate": "FEDFUNDS",
    "fed rate": "FEDFUNDS",
    "federal funds": "FEDFUNDS",
    "fedfunds": "FEDFUNDS",
    "gdp": "GDP",
    "gross domestic product": "GDP",
    "unemployment": "UNRATE",
    "unrate": "UNRATE",
    # Hebrew
    "אינפלציה": "CPIAUCNS",
    "מדד המחירים": "CPIAUCNS",
    "ריבית": "FEDFUNDS",
    "אבטלה": "UNRATE",
    "תוצר": "GDP",
    'תמ"ג': "GDP",
}

_VALID_SERIES_IDS = {"CPIAUCNS", "FEDFUNDS", "GDP", "UNRATE"}

_STRUCTURED_KEYWORDS: dict[str, list[str]] = {
    "fx_rate": ["rate", "exchange", "currency", "forex", "fx", "usd", "ils",
                "dollar", "shekel", "eur", "euro", "convert",
                # Hebrew
                "שער", "המרה", "מטבע", "דולר", "שקל", "אירו"],
    "macro_series": ["inflation", "cpi", "gdp", "interest rate", "federal funds",
                     "unemployment", "macro",
                     # Hebrew
                     "אינפלציה", "ריבית", "תוצר", "אבטלה", 'תמ"ג'],
    "price_lookup": ["price", "stock", "ticker", "share", "close", "open", "equity",
                     # Hebrew
                     "מניה", "מחיר", "מניות"],
    "portfolio_analysis": ["portfolio", "position", "holdings", "my stock", "my portfolio",
                           # Hebrew
                           "תיק", "החזקות", "פוזיציות"],
    "investment_recommendation": [
        "should i buy", "should i sell", "should i invest", "good investment",
        "recommend", "worth buying", "worth investing", "buy or sell",
        "add to portfolio", "is it a good time",
        # Hebrew
        "כדאי לקנות", "כדאי למכור", "כדאי להשקיע", "המלצה",
    ],
}

_FILLER_RE = re.compile(
    r"\b(what is|what are|can you tell me|show me|i want to know(?: about)?|"
    r"please|tell me|give me|explain|describe|how does|how do|why is|why are)\b",
    re.IGNORECASE,
)

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "and", "or", "but", "if",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "about",
    "into", "through", "before", "after", "between", "out", "over", "under",
    "its", "it", "this", "that", "these", "those", "my", "your", "his",
    "her", "our", "their", "me", "him", "us", "them", "i", "we", "you",
    "s", "re", "ve", "ll", "d",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_param(val: str) -> str:
    """Strips non-alphanumeric/underscore chars, uppercases, caps at 20 chars."""
    return re.sub(r"[^A-Z0-9_]", "", val.upper())[:20]


def _extract_currencies(question: str) -> list[str]:
    """Returns normalized ISO codes found in the question (longest alias match first)."""
    q = question.lower()
    found: list[str] = []
    for alias in sorted(_CURRENCY_ALIASES, key=len, reverse=True):
        iso = _CURRENCY_ALIASES[alias]
        if alias in q and iso not in found:
            found.append(iso)
    return found


def _rewrite_for_semantic_search(question: str, context_hint: str) -> str:
    """
    Produces a concise 8–10 token semantic search query from raw user question.
    Removes filler phrases and stop words; preserves financial entities.
    """
    cleaned = _FILLER_RE.sub("", question).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    tokens = [t for t in cleaned.split() if t.lower() not in _STOP_WORDS]
    suffix_map = {
        "price_lookup": ["price", "performance"],
        "fx_rate": ["exchange", "rate"],
        "macro_series": ["trend", "analysis"],
        "etf_holdings": ["composition", "holdings"],
    }
    suffix_tokens = suffix_map.get(context_hint, [])
    combined = tokens + [s for s in suffix_tokens if s not in tokens]
    return " ".join(combined[:10])


def _normalize_params(plan_type: str, params: dict) -> tuple[dict, str | None]:
    """
    Normalizes plan params. Returns (normalized_params, error).
    If normalization fails, error is set and normalized_params is {}.
    """
    try:
        if plan_type == "fx_rate":
            base_raw = str(params.get("base", "")).strip()
            quote_raw = str(params.get("quote", "")).strip()
            base = _CURRENCY_ALIASES.get(base_raw.lower(), base_raw.upper())
            quote = _CURRENCY_ALIASES.get(quote_raw.lower(), quote_raw.upper())
            if not base or not quote:
                return {}, "fx_rate: could not normalize base or quote"
            return {"base": base, "quote": quote}, None

        elif plan_type == "price_lookup":
            ticker_raw = str(params.get("ticker", "")).strip()
            ticker = _sanitize_param(ticker_raw)
            if not ticker:
                return {}, "price_lookup: ticker is empty after normalization"
            return {"ticker": ticker}, None

        elif plan_type == "macro_series":
            series_raw = str(params.get("series_id", "")).strip()
            series_id = _MACRO_MAP.get(series_raw.lower(), series_raw.upper())
            if not series_id:
                return {}, "macro_series: series_id is empty after normalization"
            return {"series_id": series_id}, None

        elif plan_type == "etf_holdings":
            symbol_raw = str(params.get("symbol", "")).strip()
            symbol = _sanitize_param(symbol_raw)
            if not symbol:
                return {}, "etf_holdings: symbol is empty after normalization"
            return {"symbol": symbol}, None

        elif plan_type == "portfolio_analysis":
            return {}, None

        elif plan_type == "document_analysis":
            query = str(params.get("query", "")).strip()[:200]
            if not query:
                return {}, "document_analysis: query is empty"
            return {"query": query}, None

        elif plan_type == "investment_recommendation":
            query = str(params.get("query", "")).strip()[:200]
            if not query:
                return {}, "investment_recommendation: query is empty"
            raw_tickers = params.get("tickers", [])
            if isinstance(raw_tickers, str):
                raw_tickers = [raw_tickers]
            tickers = [_sanitize_param(t) for t in raw_tickers if t]
            return {"query": query, "tickers": tickers}, None

        else:
            return {}, f"unknown type: {plan_type}"

    except Exception as e:
        return {}, f"normalization exception: {e}"


def _apply_fx_direction(params: dict, question: str) -> tuple[dict, str | None]:
    """
    Enforces FX direction rules using set-based currency detection from the raw question.
    LLM ordering is never trusted — direction is derived from the detected ISO set.
    """
    detected_set = set(_extract_currencies(question))

    if not detected_set:
        return {}, "fx_rate: no currencies detected in question"

    # USD + ILS → always USD/ILS regardless of order
    if "USD" in detected_set and "ILS" in detected_set:
        return {"base": "USD", "quote": "ILS"}, None

    # USD + any other → USD is base
    if "USD" in detected_set:
        others = detected_set - {"USD"}
        return {"base": "USD", "quote": others.pop()}, None

    # No USD → assume USD as base, detected currency as quote
    return {"base": "USD", "quote": detected_set.pop()}, None


def _validate_params(plan_type: str, params: dict) -> str | None:
    """
    Type-aware validation after normalization.
    Returns an error string if invalid, None if valid.
    """
    if plan_type == "fx_rate":
        base = params.get("base", "")
        quote = params.get("quote", "")
        if base not in _KNOWN_ISO:
            return f"fx_rate: base '{base}' not in known ISO set"
        if quote not in _KNOWN_ISO:
            return f"fx_rate: quote '{quote}' not in known ISO set"

    elif plan_type == "price_lookup":
        ticker = params.get("ticker", "")
        if not re.match(r"^[A-Z]{1,5}$", ticker):
            return f"price_lookup: ticker '{ticker}' failed format check (1-5 uppercase letters)"

    elif plan_type == "macro_series":
        series_id = params.get("series_id", "")
        if series_id not in _VALID_SERIES_IDS:
            return f"macro_series: series_id '{series_id}' not in known FRED mapping"

    elif plan_type == "etf_holdings":
        symbol = params.get("symbol", "")
        if not re.match(r"^[A-Z]{1,5}$", symbol):
            return f"etf_holdings: symbol '{symbol}' failed format check (1-5 uppercase letters)"

    elif plan_type == "document_analysis":
        if not params.get("query"):
            return "document_analysis: query is empty"

    elif plan_type == "investment_recommendation":
        if not params.get("query"):
            return "investment_recommendation: query is empty"

    return None


def _build_query_plan(plan_type: str, params: dict) -> QueryPlan:
    """Maps validated, normalized params to a hardcoded QueryPlan. No dynamic SQL."""
    if plan_type == "fx_rate":
        base = params["base"]
        quote = params["quote"]
        return QueryPlan(
            source="sql",
            query=f"SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1",
        )
    elif plan_type == "price_lookup":
        ticker = params["ticker"]
        return QueryPlan(
            source="sql",
            query=f"SELECT symbol, close, date FROM prices WHERE symbol='{ticker}' ORDER BY date DESC LIMIT 30",
        )
    elif plan_type == "macro_series":
        series_id = params["series_id"]
        return QueryPlan(
            source="sql",
            query=f"SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12",
        )
    elif plan_type == "etf_holdings":
        symbol = params["symbol"]
        return QueryPlan(
            source="sql",
            query=f"SELECT holding_symbol, weight FROM etf_holdings WHERE etf_symbol='{symbol}' ORDER BY weight DESC LIMIT 20",
        )
    elif plan_type == "portfolio_analysis":
        # owner_id cannot be safely injected here — chat_service.py already fetches
        # portfolio context via fetch_portfolio_context(pool, query.owner_id) using a
        # parameterized query. Route to vector so no unsafe SQL literal reaches the DB.
        return QueryPlan(source="vector", query="portfolio positions holdings analysis risk exposure")
    elif plan_type == "document_analysis":
        return QueryPlan(source="vector", query=params["query"])
    elif plan_type == "investment_recommendation":
        # Routes to vector for document context; Intelligence Layer handles scoring/recommendation
        return QueryPlan(source="vector", query=params["query"])
    else:
        raise ValueError(f"Unhandled type: {plan_type}")


def _map_single_plan(raw_plan: dict, question: str) -> QueryPlan:
    """
    Maps one raw LLM plan dict → QueryPlan.
    Returns a document_analysis fallback (with rewritten query) on any failure.
    """
    plan_type = raw_plan.get("type", "")
    params = raw_plan.get("params", {})
    fallback_query = _rewrite_for_semantic_search(question, plan_type)

    normalized, norm_error = _normalize_params(plan_type, params)
    if norm_error:
        logger.warning(json.dumps({"event": "plan_normalization_failed", "type": plan_type, "error": norm_error}))
        return QueryPlan(source="vector", query=fallback_query)

    if plan_type == "fx_rate":
        normalized, fx_error = _apply_fx_direction(normalized, question)
        if fx_error:
            logger.warning(json.dumps({"event": "plan_fx_direction_failed", "type": plan_type, "error": fx_error}))
            return QueryPlan(source="vector", query=fallback_query)

    val_error = _validate_params(plan_type, normalized)
    if val_error:
        logger.warning(json.dumps({"event": "plan_validation_failed", "type": plan_type, "error": val_error}))
        return QueryPlan(source="vector", query=fallback_query)

    try:
        return _build_query_plan(plan_type, normalized)
    except Exception as e:
        logger.error(json.dumps({"event": "plan_build_failed", "type": plan_type, "error": str(e)}))
        return QueryPlan(source="vector", query=fallback_query)


# ---------------------------------------------------------------------------
# Structured intent detector — used only when LLM JSON parsing fails entirely
# ---------------------------------------------------------------------------

def _detect_structured_intent(question: str) -> QueryPlan | None:
    """
    Keyword-based fallback when LLM output cannot be parsed.
    Returns a QueryPlan if a structured intent is detected, None otherwise.
    Vector fallback is the caller's responsibility when None is returned.
    """
    q = question.lower()

    if any(kw in q for kw in _STRUCTURED_KEYWORDS["fx_rate"]):
        detected = _extract_currencies(question)
        if "USD" in detected and "ILS" in detected:
            base, quote = "USD", "ILS"
        elif len(detected) >= 2:
            base, quote = detected[0], detected[1]
        elif len(detected) == 1:
            base = "USD"
            quote = detected[0] if detected[0] != "USD" else "ILS"
        else:
            base, quote = "USD", "ILS"
        return QueryPlan(
            source="sql",
            query=f"SELECT rate, date FROM fx_rates WHERE base_currency='{base}' AND quote_currency='{quote}' ORDER BY date DESC LIMIT 1",
        )

    if any(kw in q for kw in _STRUCTURED_KEYWORDS["macro_series"]):
        for kw, series_id in _MACRO_MAP.items():
            if kw in q:
                return QueryPlan(
                    source="sql",
                    query=f"SELECT series_id, value, date FROM macro_series WHERE series_id='{series_id}' ORDER BY date DESC LIMIT 12",
                )

    if any(kw in q for kw in _STRUCTURED_KEYWORDS["portfolio_analysis"]):
        # Same as _build_query_plan: portfolio SQL requires owner_id injection which
        # cannot happen here. chat_service.py handles portfolio context separately.
        return QueryPlan(source="vector", query="portfolio positions holdings analysis risk exposure")

    # price_lookup: ticker cannot be safely inferred from keywords alone → document_analysis
    if any(kw in q for kw in _STRUCTURED_KEYWORDS["price_lookup"]):
        return QueryPlan(
            source="vector",
            query=_rewrite_for_semantic_search(question, "price_lookup"),
        )

    # investment_recommendation: route to vector; Intelligence Layer handles scoring
    if any(kw in q for kw in _STRUCTURED_KEYWORDS["investment_recommendation"]):
        return QueryPlan(
            source="vector",
            query=_rewrite_for_semantic_search(question, "investment_recommendation"),
        )

    return None


# ---------------------------------------------------------------------------
# Public planner
# ---------------------------------------------------------------------------

class QueryPlanner:
    @staticmethod
    @trace_latency("router_latency")
    async def plan(question: str) -> MultiQueryPlan:
        """Classifies the question and returns a deterministic execution plan."""
        response = None
        try:
            response = await RoutingAgentClient.generate_json(
                messages=[
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": question},
                ]
            )

            plan_dict = json.loads(response)
            raw_plans = plan_dict.get("plans", [])
            mapped = [_map_single_plan(p, question) for p in raw_plans]

            if not mapped:
                raise ValueError("All plans rejected after mapping")

            logger.info(json.dumps({"event": "router_decision", "decision": [p.dict() for p in mapped]}))
            return MultiQueryPlan(plans=mapped)

        except Exception as e:
            logger.error(json.dumps({
                "event": "router_fallback",
                "error": str(e),
                "llm_response": response if response else "N/A",
            }))
            structured = _detect_structured_intent(question)
            if structured:
                logger.info(json.dumps({"event": "router_structured_fallback", "plan": structured.dict()}))
                return MultiQueryPlan(plans=[structured])
            return MultiQueryPlan(plans=[QueryPlan(source="vector", query=question)])
