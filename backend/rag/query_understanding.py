"""
Phase 4A — General Query Understanding Foundation.

Deterministic, no LLM, no external deps.
Translates raw user text into a structured QueryUnderstandingResult
that the Planner can use to improve intent detection and slot filling.

TODO (Phase 4B): add semantic example matching, query rewriting for
vector retrieval, and optional LLM JSON classifier fallback.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class IntentCandidate:
    intent_type: str
    confidence: float
    matched_signals: list[str]
    source: str  # "rule" | "phrase" | "entity" | "fallback"


@dataclass
class DetectedEntity:
    surface: str
    canonical: str
    entity_type: str  # ticker | company | currency | macro_topic | portfolio | document | benchmark | unknown
    resolved_value: Optional[str]
    confidence: float
    note: Optional[str] = None


@dataclass
class QueryUnderstandingResult:
    original_query: str
    normalized_query: str
    language_hint: str          # "he" | "en" | "mixed" | "unknown"
    intent_candidates: list[IntentCandidate]
    primary_intent: Optional[str]
    entities: list[DetectedEntity]
    slots: dict
    confidence: float
    ambiguity_flags: list[str]
    notes: list[str]


# ── Text normalization ────────────────────────────────────────────────────────

_HEBREW_QUOTE_RE = re.compile(r'[״״׳\'"]')
_DASH_VARIANTS_RE = re.compile(r'[\u2013\u2014\u2012\u2011\u00ad]')  # en-dash, em-dash, etc.
_MULTI_SPACE_RE = re.compile(r'[ \t]+')
_PUNCT_STRIP_RE = re.compile(r'[?!.,;:()\[\]{}]')
_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')


def _normalize(text: str) -> str:
    """
    Normalize whitespace, punctuation, and Hebrew special chars.
    Lowercase for matching; uppercase ticker tokens are preserved
    by operating on the original before lowercasing where needed.
    """
    # Normalize unicode composed forms
    text = unicodedata.normalize("NFC", text)
    # Replace Hebrew quote chars and dash variants with space
    text = _HEBREW_QUOTE_RE.sub(" ", text)
    text = _DASH_VARIANTS_RE.sub(" ", text)
    # Strip common punctuation
    text = _PUNCT_STRIP_RE.sub(" ", text)
    # Collapse multiple spaces
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


# ── Language detection ────────────────────────────────────────────────────────

_HEBREW_RE = re.compile(r'[\u05d0-\u05ea\ufb1d-\ufb4e]')
_LATIN_RE = re.compile(r'[A-Za-z]')


def _detect_language(text: str) -> str:
    has_hebrew = bool(_HEBREW_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_hebrew and has_latin:
        return "mixed"
    if has_hebrew:
        return "he"
    if has_latin:
        return "en"
    return "unknown"


# ── Entity maps ───────────────────────────────────────────────────────────────

# Uppercase words that are NOT tickers
_NON_TICKERS = {
    "USD", "ILS", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
    "CEO", "CFO", "CTO", "COO", "SEC", "ETF", "IPO",
    "GDP", "CPI", "FED", "IMF", "US", "AI", "IT", "UK",
    "EU", "FX", "OR", "IN", "AT", "BY", "DO", "IS", "AN",
    "TO", "BE", "ON", "OF", "AM", "PM",
    "SPDR", "ISHARES", "VANGUARD", "STATE", "STREET",
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
}

# Company/instrument alias → ticker (small, testable)
_COMPANY_ALIASES: dict[str, str] = {
    "apple": "AAPL", "אפל": "AAPL",
    "microsoft": "MSFT", "מייקרוסופט": "MSFT", "מיקרוסופט": "MSFT",
    "nvidia": "NVDA", "אנבידיה": "NVDA", "נבידיה": "NVDA",
    "tesla": "TSLA", "טסלה": "TSLA",
    "meta": "META", "מטא": "META",
    "google": "GOOGL", "גוגל": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "אמזון": "AMZN",
}

# Currency aliases → ISO
_CURRENCY_ALIASES: dict[str, str] = {
    "dollar": "USD", "dollars": "USD", "usd": "USD",
    "shekel": "ILS", "shekels": "ILS", "nis": "ILS", "ils": "ILS",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "pound": "GBP", "gbp": "GBP",
    "yen": "JPY", "jpy": "JPY",
    # Hebrew
    "דולר": "USD", "דולרים": "USD",
    'ש"ח': "ILS", "שח": "ILS", "שקל": "ILS", "שקלים": "ILS",
    "אירו": "EUR", "יורו": "EUR",
}

# Macro topic aliases → FRED series
_MACRO_ALIASES: dict[str, str] = {
    "inflation": "CPIAUCNS", "cpi": "CPIAUCNS",
    "consumer price": "CPIAUCNS", "מדד המחירים": "CPIAUCNS", "אינפלציה": "CPIAUCNS",
    "interest rate": "FEDFUNDS", "fed rate": "FEDFUNDS",
    "federal funds": "FEDFUNDS", "fedfunds": "FEDFUNDS",
    "ריבית": "FEDFUNDS",
    "gdp": "GDP", "gross domestic product": "GDP",
    "תוצר": "GDP", 'תמ"ג': "GDP",
    "unemployment": "UNRATE", "unrate": "UNRATE",
    "אבטלה": "UNRATE",
}

# Benchmark/ETF proxy aliases
_BENCHMARK_ALIASES: dict[str, tuple[str, str]] = {
    # surface → (canonical_name, proxy_ticker)
    "s&p 500": ("S&P 500", "SPY"),
    "s&p": ("S&P 500", "SPY"),
    "sp500": ("S&P 500", "SPY"),
    "s p 500": ("S&P 500", "SPY"),
    "אסאנפי": ("S&P 500", "SPY"),
    "אס אנ פי": ("S&P 500", "SPY"),
    "nasdaq 100": ("NASDAQ 100", "QQQ"),
    "nasdaq": ("NASDAQ 100", "QQQ"),
    "נאסדק": ("NASDAQ 100", "QQQ"),
    "qqq": ("NASDAQ 100", "QQQ"),
    "dow jones": ("Dow Jones", "DIA"),
    "dow": ("Dow Jones", "DIA"),
    "russell 2000": ("Russell 2000", "IWM"),
}

# Document signals
_DOCUMENT_SIGNALS = [
    "document", "report", "pdf", "file", "uploaded", "upload",
    "דוח", "מסמך", "קובץ",
]


# ── Intent signal groups ──────────────────────────────────────────────────────

_INTENT_SIGNALS: dict[str, list[str]] = {
    "fx_rate": [
        "dollar rate", "usd ils", "exchange rate", "dollar shekel",
        "eur ils", "currency rate", "fx rate", "convert",
        "שער הדולר", "כמה הדולר", "דולר שקל", "שער האירו", "יורו", "שקל",
        "המרה", "שער",
    ],
    "price_lookup": [
        "stock price", "price of", "how much is", "current price", "quote",
        "כמה עולה", "מחיר המניה", "כמה שווה", "שער מניה", "מחיר",
        "המנייה של", "המניה של", "המנייה", "המניה",
    ],
    "etf_holdings": [
        "holdings", "top holdings", "composition", "what does it hold",
        "what is inside", "exposure inside",
        "companies inside", "companies are inside", "which companies are inside",
        "מה יש בתוך", "מה ההרכב", "איזה מניות", "החזקות", "ממה מורכב", "מה בפנים",
        "הרכב",
        # Phase 4C.1: condensed/rewritten Hebrew ETF composition phrases.
        # "מרכיבים" = components/constituents, "קרן" = fund.
        # Kept as compound phrases (not bare "מרכיבים") to avoid false positives
        # on non-financial "components" questions.
        "מהם המרכיבים", "מרכיבי קרן", "הרכב קרן", "מרכיבים של",
        "ממה מורכבת", "מרכיבי ה", "הרכב הקרן",
        "מה כוללים הנכסים", "מה כוללות המניות",
        "אילו מניות יש בקרן", "אילו נכסים יש בקרן",
    ],
    "portfolio": [
        "portfolio risk", "analyze my portfolio", "should i diversify",
        "am i exposed", "concentration", "allocation",
        "my portfolio", "my holdings", "my positions",
        "התיק שלי", "סיכון בתיק", "חשוף מדי", "כבד מדי",
        "פיזור", "ריכוזיות", "אלוקציה", "תיק השקעות",
    ],
    "document_lookup": [
        "summarize the document", "what does the report say",
        "uploaded file", "pdf", "statement", "report",
        "summarize", "the report", "the document", "uploaded report",
        "תסכם את הדוח", "מה כתוב במסמך", "בדוח", "בקובץ",
        "במסמך", "דמי ניהול", "יתרה בדוח",
        "תסכם", "סכם", "הדוח שהעליתי", "דוח רבעוני", "דוח ריבעוני",
        "הדוח", "המסמך", "את הדוח", "את המסמך",
    ],
    "macro_series": [
        "inflation", "interest rate", "fed rate", "gdp", "unemployment", "vix",
        "yield curve",
        "אינפלציה", "ריבית", "תוצר", "אבטלה", "מדד המחירים", "עקום תשואות",
    ],
    "market_advisory": [
        "what do you think about the market", "explain what is happening",
        "outlook", "trend",
        "מה קורה בשוק", "מה אתה חושב על השוק", "מה המגמה",
        "תסביר לי מה קורה",
    ],
    # Phase 4C: deterministic data availability / coverage questions.
    # Long, specific phrases — must combine an availability cue with a
    # data-class word so we don't collide with price_lookup.
    "data_availability_lookup": [
        # Hebrew
        "של איזה מניות כן יש לך",
        "איזה מניות יש לך",
        "אילו מניות יש לך",
        "איזה מחירי מניות יש לך",
        "אילו מחירי מניות יש לך",
        "איזה סימבולים יש לך",
        "אילו סימבולים יש לך",
        "איזה סימבולים זמינים",
        "אילו סימבולים זמינים",
        "מחירי מניות זמינים",
        "מניות זמינות",
        # English
        "which stock prices are available",
        "what stock prices are available",
        "what symbols do you have prices for",
        "which symbols do you have prices for",
        "what market prices do you have",
        "which market prices do you have",
        "what tickers do you have",
        "which tickers do you have",
        "available stock prices",
        "available symbols",
        "list of available symbols",
        "list of available stocks",
    ],
}

# Intents that require a valid slot to be routed to SQL
_REQUIRES_SLOT: dict[str, str] = {
    "price_lookup": "ticker",
    "etf_holdings": "ticker",
    "fx_rate": "base_currency",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_explicit_tickers(text: str) -> list[str]:
    """Uppercase 2–5 char tokens that are not in _NON_TICKERS."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _TICKER_RE.finditer(text):
        c = m.group(1)
        if c not in _NON_TICKERS and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _match_phrases(q_lower: str, signals: list[str]) -> list[str]:
    return [s for s in signals if s in q_lower]


def _build_currency_entities(q_lower: str, original: str) -> list[DetectedEntity]:
    entities: list[DetectedEntity] = []
    seen: set[str] = set()
    for alias in sorted(_CURRENCY_ALIASES, key=len, reverse=True):
        if alias in q_lower:
            iso = _CURRENCY_ALIASES[alias]
            if iso not in seen:
                seen.add(iso)
                entities.append(DetectedEntity(
                    surface=alias,
                    canonical=iso,
                    entity_type="currency",
                    resolved_value=iso,
                    confidence=0.95,
                ))
    return entities


_MACRO_SEMANTIC_TYPE: dict[str, str] = {
    "CPIAUCNS": "index_level",
    "GDP": "index_level",
    "FEDFUNDS": "percent",
    "UNRATE": "percent",
}

_MACRO_SEMANTIC_NOTE: dict[str, str] = {
    "CPIAUCNS": "CPIAUCNS is an index level, not an inflation percentage.",
    "GDP": "GDP series is reported as a level, not a growth rate.",
}


def _build_macro_entities(q_lower: str) -> list[DetectedEntity]:
    entities: list[DetectedEntity] = []
    seen: set[str] = set()
    for alias in sorted(_MACRO_ALIASES, key=len, reverse=True):
        if alias in q_lower:
            series = _MACRO_ALIASES[alias]
            if series not in seen:
                seen.add(series)
                entities.append(DetectedEntity(
                    surface=alias,
                    canonical=series,
                    entity_type="macro_topic",
                    resolved_value=series,
                    confidence=0.9,
                    note=_MACRO_SEMANTIC_NOTE.get(series),
                ))
    return entities


def _build_benchmark_entities(q_lower: str) -> list[DetectedEntity]:
    entities: list[DetectedEntity] = []
    seen: set[str] = set()
    for alias in sorted(_BENCHMARK_ALIASES, key=len, reverse=True):
        if alias in q_lower:
            canonical, proxy = _BENCHMARK_ALIASES[alias]
            if canonical not in seen:
                seen.add(canonical)
                entities.append(DetectedEntity(
                    surface=alias,
                    canonical=canonical,
                    entity_type="benchmark",
                    resolved_value=proxy,
                    confidence=0.9,
                    note=f"Using {proxy} as ETF proxy for {canonical}.",
                ))
    return entities


def _build_company_entities(q_lower: str) -> list[DetectedEntity]:
    entities: list[DetectedEntity] = []
    seen: set[str] = set()
    for alias in sorted(_COMPANY_ALIASES, key=len, reverse=True):
        if alias in q_lower:
            ticker = _COMPANY_ALIASES[alias]
            if ticker not in seen:
                seen.add(ticker)
                entities.append(DetectedEntity(
                    surface=alias,
                    canonical=ticker,
                    entity_type="company",
                    resolved_value=ticker,
                    confidence=0.85,
                ))
    return entities


def _build_ticker_entities(original: str, already_resolved: set[str]) -> list[DetectedEntity]:
    entities: list[DetectedEntity] = []
    for ticker in _extract_explicit_tickers(original):
        if ticker not in already_resolved:
            entities.append(DetectedEntity(
                surface=ticker,
                canonical=ticker,
                entity_type="ticker",
                resolved_value=ticker,
                confidence=0.9,
            ))
    return entities


def _build_document_entities(q_lower: str) -> list[DetectedEntity]:
    for sig in _DOCUMENT_SIGNALS:
        if sig in q_lower:
            return [DetectedEntity(
                surface=sig,
                canonical="document",
                entity_type="document",
                resolved_value=None,
                confidence=0.8,
            )]
    return []


# ── Slot filling ──────────────────────────────────────────────────────────────

def _fill_slots(
    entities: list[DetectedEntity],
    intent_candidates: list[IntentCandidate],
) -> dict:
    slots: dict = {}
    primary = intent_candidates[0].intent_type if intent_candidates else None

    # Currency slots
    currencies = [e for e in entities if e.entity_type == "currency"]
    if currencies:
        slots["base_currency"] = currencies[0].resolved_value
        if len(currencies) >= 2:
            slots["quote_currency"] = currencies[1].resolved_value

    # Ticker / benchmark → ticker slot
    ticker_ents = [e for e in entities if e.entity_type in ("ticker", "company", "benchmark")]
    if ticker_ents:
        slots["ticker"] = ticker_ents[0].resolved_value

    # Macro series slot
    macro_ents = [e for e in entities if e.entity_type == "macro_topic"]
    if macro_ents:
        sid = macro_ents[0].resolved_value
        slots["series_id"] = sid
        if sid and sid in _MACRO_SEMANTIC_TYPE:
            slots["series_semantic_type"] = _MACRO_SEMANTIC_TYPE[sid]

    return slots


# ── Intent scoring ────────────────────────────────────────────────────────────

def _score_intents(
    q_lower: str,
    entities: list[DetectedEntity],
    slots: dict,
) -> list[IntentCandidate]:
    candidates: list[IntentCandidate] = []

    for intent_type, signals in _INTENT_SIGNALS.items():
        matched = _match_phrases(q_lower, signals)
        if not matched:
            continue

        # Base confidence from signal match density
        conf = min(0.55 + 0.1 * len(matched), 0.85)

        # Boost if required slot is present
        required_slot = _REQUIRES_SLOT.get(intent_type)
        if required_slot and required_slot in slots:
            conf = min(conf + 0.1, 0.95)

        # Entity-type boosts
        if intent_type == "price_lookup":
            has_ticker = any(e.entity_type in ("ticker", "company") for e in entities)
            if has_ticker:
                conf = min(conf + 0.1, 0.95)

        if intent_type == "etf_holdings":
            has_benchmark = any(e.entity_type == "benchmark" for e in entities)
            has_ticker = any(e.entity_type in ("ticker",) for e in entities)
            if has_benchmark or has_ticker:
                conf = min(conf + 0.1, 0.95)

        if intent_type == "fx_rate":
            currency_count = sum(1 for e in entities if e.entity_type == "currency")
            if currency_count >= 2:
                conf = min(conf + 0.1, 0.95)
            elif currency_count == 1:
                conf = min(conf + 0.05, 0.9)

        if intent_type == "macro_series":
            has_macro = any(e.entity_type == "macro_topic" for e in entities)
            if has_macro:
                conf = min(conf + 0.1, 0.95)

        if intent_type == "document_lookup":
            has_doc = any(e.entity_type == "document" for e in entities)
            if has_doc:
                conf = min(conf + 0.05, 0.9)

        # Data availability phrases are long and specific; promote so they
        # dominate price_lookup on overlapping tokens like "מחיר"/"מניה".
        if intent_type == "data_availability_lookup":
            conf = min(conf + 0.3, 0.95)

        candidates.append(IntentCandidate(
            intent_type=intent_type,
            confidence=round(conf, 3),
            matched_signals=matched,
            source="phrase",
        ))

    # Entity-driven candidates (no phrase match needed)
    has_macro = any(e.entity_type == "macro_topic" for e in entities)
    if has_macro and not any(c.intent_type == "macro_series" for c in candidates):
        candidates.append(IntentCandidate(
            intent_type="macro_series",
            confidence=0.7,
            matched_signals=[],
            source="entity",
        ))

    has_doc = any(e.entity_type == "document" for e in entities)
    if has_doc and not any(c.intent_type == "document_lookup" for c in candidates):
        candidates.append(IntentCandidate(
            intent_type="document_lookup",
            confidence=0.7,
            matched_signals=[],
            source="entity",
        ))

    # If data_availability_lookup was matched with high confidence, demote
    # price_lookup / etf_holdings — the user is asking what we *have*, not
    # the value of a specific instrument.
    avail = next(
        (c for c in candidates if c.intent_type == "data_availability_lookup"),
        None,
    )
    if avail and avail.confidence >= 0.8:
        for c in candidates:
            if c.intent_type in ("price_lookup", "etf_holdings"):
                c.confidence = round(max(c.confidence - 0.4, 0.1), 3)

    # Sort by confidence descending
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


# ── Ambiguity / confidence rules ──────────────────────────────────────────────

def _compute_overall_confidence(
    candidates: list[IntentCandidate],
    slots: dict,
    entities: list[DetectedEntity],
    ambiguity_flags: list[str],
) -> float:
    if not candidates:
        return 0.1

    top = candidates[0]

    # Penalize if top two candidates are very close (ambiguous)
    if len(candidates) >= 2:
        gap = top.confidence - candidates[1].confidence
        if gap < 0.1:
            ambiguity_flags.append("multiple_close_intents")

    # Required slot missing for SQL intents → reduce confidence
    required = _REQUIRES_SLOT.get(top.intent_type)
    if required and required not in slots:
        ambiguity_flags.append(f"missing_slot:{required}")
        return max(top.confidence - 0.25, 0.3)

    return top.confidence


def _build_ambiguity_flags(
    candidates: list[IntentCandidate],
    entities: list[DetectedEntity],
    q_lower: str,
) -> list[str]:
    flags: list[str] = []

    # Vague reference without entity
    vague = ["זה", "זו", "הדבר", "זאת", "tell me about it", "show me this"]
    if any(v in q_lower for v in vague) and not entities:
        flags.append("vague_reference_no_entity")

    # Entity present but no clear intent
    has_entity = bool(entities)
    if has_entity and not candidates:
        flags.append("entity_without_intent")

    # Advisory-sounding language around a factual entity
    advisory_words = [
        "מה אתה חושב", "what do you think", "should i", "כדאי", "האם כדאי",
        "מה הסיפור", "the story", "outlook", "opinion",
    ]
    has_advisory = any(w in q_lower for w in advisory_words)
    has_ticker_or_benchmark = any(
        e.entity_type in ("ticker", "company", "benchmark") for e in entities
    )
    if has_advisory and has_ticker_or_benchmark:
        flags.append("advisory_tone_with_entity")

    return flags


# ── Public API ────────────────────────────────────────────────────────────────

def understand_query(raw_query: str) -> QueryUnderstandingResult:
    """
    Deterministic query understanding — no LLM, no external deps.
    Returns QueryUnderstandingResult with normalized text, language hint,
    intent candidates, detected entities, slots, confidence, and flags.
    """
    normalized = _normalize(raw_query)
    q_lower = normalized.lower()
    lang = _detect_language(raw_query)

    notes: list[str] = []

    # ── Entity extraction ────────────────────────────────────────────────────
    entities: list[DetectedEntity] = []

    # 1. Currencies (longest match first)
    entities += _build_currency_entities(q_lower, raw_query)

    # 2. Macro topics
    entities += _build_macro_entities(q_lower)

    # 3. Benchmarks (before tickers so "QQQ" isn't double-counted)
    bench_ents = _build_benchmark_entities(q_lower)
    entities += bench_ents
    bench_resolved = {e.resolved_value for e in bench_ents if e.resolved_value}

    # 4. Company aliases
    company_ents = _build_company_entities(q_lower)
    entities += company_ents
    company_resolved = {e.resolved_value for e in company_ents if e.resolved_value}

    # 5. Explicit uppercase tickers (not already resolved via alias)
    already_resolved = bench_resolved | company_resolved
    entities += _build_ticker_entities(raw_query, already_resolved)

    # 6. Document signals
    entities += _build_document_entities(q_lower)

    # Notes for benchmark proxies
    for e in bench_ents:
        if e.note:
            notes.append(e.note)

    # Notes for macro semantic types (index_level vs percent)
    for e in entities:
        if e.entity_type == "macro_topic" and e.note:
            notes.append(e.note)

    # ── Slot filling ─────────────────────────────────────────────────────────
    # Preliminary slot fill (intent candidates not yet scored)
    slots = _fill_slots(entities, [])

    # ── Intent scoring ────────────────────────────────────────────────────────
    ambiguity_flags = _build_ambiguity_flags([], entities, q_lower)
    candidates = _score_intents(q_lower, entities, slots)

    # Rebuild slots with primary intent known
    slots = _fill_slots(entities, candidates)

    # ── Ambiguity & confidence ────────────────────────────────────────────────
    ambiguity_flags += _build_ambiguity_flags(candidates, entities, q_lower)
    # deduplicate
    ambiguity_flags = list(dict.fromkeys(ambiguity_flags))

    confidence = _compute_overall_confidence(candidates, slots, entities, ambiguity_flags)

    primary_intent = candidates[0].intent_type if candidates else None

    # Safety: if advisory tone detected alongside entity, don't force factual intent
    if "advisory_tone_with_entity" in ambiguity_flags:
        factual_intents = {"price_lookup", "etf_holdings", "fx_rate", "macro_series"}
        if primary_intent in factual_intents:
            # Demote to advisory
            primary_intent = "market_advisory"
            confidence = max(confidence - 0.2, 0.3)
            notes.append("Advisory tone detected — not routing to factual SQL intent.")

    return QueryUnderstandingResult(
        original_query=raw_query,
        normalized_query=normalized,
        language_hint=lang,
        intent_candidates=candidates,
        primary_intent=primary_intent,
        entities=entities,
        slots=slots,
        confidence=round(confidence, 3),
        ambiguity_flags=ambiguity_flags,
        notes=notes,
    )
