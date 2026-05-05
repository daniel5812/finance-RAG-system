"""
Phase 4A — QueryUnderstanding unit tests.
No LLM, no external deps, pure deterministic.

Run: docker compose exec api pytest tests/test_query_understanding.py -v
"""
import pytest
from rag.query_understanding import understand_query


# ── Normalization ─────────────────────────────────────────────────────────────

def test_normalization_whitespace():
    r = understand_query("  כמה   הדולר   היום  ")
    assert "  " not in r.normalized_query
    assert r.normalized_query == r.normalized_query.strip()


def test_normalization_punctuation():
    r = understand_query("what is AAPL?!")
    assert "?" not in r.normalized_query
    assert "!" not in r.normalized_query


def test_normalization_preserves_ticker():
    r = understand_query("כמה עולה AAPL עכשיו?")
    tickers = [e for e in r.entities if e.entity_type == "ticker"]
    assert any(e.resolved_value == "AAPL" for e in tickers)


def test_normalization_mixed_hebrew_english():
    r = understand_query("SPY   מה   ההרכב")
    assert "  " not in r.normalized_query


# ── Language detection ────────────────────────────────────────────────────────

def test_language_hebrew():
    r = understand_query("כמה הדולר היום?")
    assert r.language_hint == "he"


def test_language_english():
    r = understand_query("What is the dollar rate today?")
    assert r.language_hint == "en"


def test_language_mixed():
    r = understand_query("כמה עולה AAPL עכשיו?")
    assert r.language_hint == "mixed"


def test_language_unknown():
    r = understand_query("1234 5678")
    assert r.language_hint == "unknown"


# ── FX / currency ─────────────────────────────────────────────────────────────

def test_fx_hebrew_dollar():
    r = understand_query("כמה הדולר היום?")
    assert any(c.intent_type == "fx_rate" for c in r.intent_candidates)
    currency_isos = [e.resolved_value for e in r.entities if e.entity_type == "currency"]
    assert "USD" in currency_isos


def test_fx_english_euro():
    r = understand_query("what is the euro exchange rate?")
    assert any(c.intent_type == "fx_rate" for c in r.intent_candidates)
    currency_isos = [e.resolved_value for e in r.entities if e.entity_type == "currency"]
    assert "EUR" in currency_isos


def test_fx_usd_ils():
    r = understand_query("usd ils rate")
    assert any(c.intent_type == "fx_rate" for c in r.intent_candidates)
    currency_isos = {e.resolved_value for e in r.entities if e.entity_type == "currency"}
    assert "USD" in currency_isos
    assert "ILS" in currency_isos
    assert r.slots.get("base_currency") == "USD"


def test_fx_shekel_slot():
    r = understand_query("דולר שקל כמה שווה")
    assert any(c.intent_type == "fx_rate" for c in r.intent_candidates)
    isos = {e.resolved_value for e in r.entities if e.entity_type == "currency"}
    assert "USD" in isos
    assert "ILS" in isos


# ── Price / company ───────────────────────────────────────────────────────────

def test_price_lookup_hebrew_ticker():
    r = understand_query("כמה עולה AAPL עכשיו?")
    assert any(c.intent_type == "price_lookup" for c in r.intent_candidates)
    assert r.slots.get("ticker") == "AAPL"


def test_price_lookup_english_company_alias():
    r = understand_query("what is Apple stock price?")
    assert r.slots.get("ticker") == "AAPL"
    intents = [c.intent_type for c in r.intent_candidates]
    assert "price_lookup" in intents


def test_price_lookup_vague_entity_not_forced():
    """'מה הסיפור עם אפל?' → entity AAPL detected but not forced to price_lookup."""
    r = understand_query("מה הסיפור עם אפל?")
    # advisory_tone_with_entity flag should be set — primary should NOT be price_lookup
    assert "advisory_tone_with_entity" in r.ambiguity_flags
    assert r.primary_intent != "price_lookup"


# ── ETF holdings / composition ────────────────────────────────────────────────

def test_etf_holdings_hebrew_spy():
    r = understand_query("מה יש בתוך SPY?")
    assert any(c.intent_type == "etf_holdings" for c in r.intent_candidates)
    assert r.slots.get("ticker") == "SPY"


def test_etf_holdings_english_qqq():
    r = understand_query("which companies are inside QQQ?")
    assert any(c.intent_type == "etf_holdings" for c in r.intent_candidates)
    assert r.slots.get("ticker") == "QQQ"


def test_etf_holdings_benchmark_alias_hebrew():
    r = understand_query("מה ההרכב של אסאנפי?")
    assert any(c.intent_type == "etf_holdings" for c in r.intent_candidates)
    bench = [e for e in r.entities if e.entity_type == "benchmark"]
    assert any(e.resolved_value == "SPY" for e in bench)
    # Note about proxy should exist
    assert any("SPY" in n for n in r.notes)


def test_etf_holdings_opinion_not_forced():
    """'מה אתה חושב על אסאנפי?' → advisory tone, not forced to etf_holdings."""
    r = understand_query("מה אתה חושב על אסאנפי?")
    assert "advisory_tone_with_entity" in r.ambiguity_flags
    assert r.primary_intent != "etf_holdings"


# ── Portfolio / advisory ──────────────────────────────────────────────────────

def test_portfolio_risk_hebrew():
    r = understand_query("התיק שלי מסוכן מדי?")
    assert any(c.intent_type == "portfolio" for c in r.intent_candidates)
    # Must NOT produce factual SQL
    assert r.primary_intent not in ("price_lookup", "etf_holdings", "fx_rate", "macro_series")


def test_portfolio_diversify_english():
    r = understand_query("Should I diversify my portfolio?")
    assert any(c.intent_type == "portfolio" for c in r.intent_candidates)


def test_portfolio_hebrew_tech_heavy():
    r = understand_query("אני כבד מדי על טכנולוגיה?")
    assert any(c.intent_type == "portfolio" for c in r.intent_candidates)


# ── Document lookup ───────────────────────────────────────────────────────────

def test_document_lookup_hebrew():
    r = understand_query("תסכם לי את הדוח שהעליתי")
    assert any(c.intent_type == "document_lookup" for c in r.intent_candidates)
    doc_ents = [e for e in r.entities if e.entity_type == "document"]
    assert doc_ents


def test_document_lookup_english():
    r = understand_query("what does the uploaded report say about fees?")
    assert any(c.intent_type == "document_lookup" for c in r.intent_candidates)


# ── Macro series ──────────────────────────────────────────────────────────────

def test_macro_interest_rate_hebrew():
    r = understand_query("מה הריבית בארהב?")
    assert any(c.intent_type == "macro_series" for c in r.intent_candidates)
    macro = [e for e in r.entities if e.entity_type == "macro_topic"]
    assert any(e.resolved_value == "FEDFUNDS" for e in macro)


def test_macro_inflation_english():
    r = understand_query("what is inflation doing?")
    assert any(c.intent_type == "macro_series" for c in r.intent_candidates)
    macro = [e for e in r.entities if e.entity_type == "macro_topic"]
    assert any(e.resolved_value == "CPIAUCNS" for e in macro)


# ── Ambiguous / no_match ──────────────────────────────────────────────────────

def test_ambiguous_vague_reference_hebrew():
    r = understand_query("תראה לי את זה")
    assert r.confidence < 0.5
    assert not r.intent_candidates or r.primary_intent is None or r.confidence < 0.5


def test_ambiguous_vague_hebrew_short():
    r = understand_query("מה הולך?")
    # No entities, no strong signals → low confidence
    assert r.confidence < 0.65


def test_ambiguous_english_vague():
    r = understand_query("tell me about it")
    assert r.confidence < 0.65


# ── Confidence rules ──────────────────────────────────────────────────────────

def test_high_confidence_clear_intent_with_slot():
    r = understand_query("כמה עולה AAPL עכשיו?")
    assert r.confidence >= 0.7


def test_low_confidence_missing_slot():
    """price_lookup signal but no ticker → missing slot → lower confidence."""
    r = understand_query("כמה עולה המניה הזאת?")
    # If price_lookup is top candidate, missing_slot flag should reduce confidence
    if r.primary_intent == "price_lookup":
        assert "missing_slot:ticker" in r.ambiguity_flags
        assert r.confidence < 0.75


def test_entity_with_advisory_no_factual_sql():
    r = understand_query("what do you think about NVDA?")
    assert "advisory_tone_with_entity" in r.ambiguity_flags
    assert r.primary_intent != "price_lookup"


# ── Entity extraction details ─────────────────────────────────────────────────

def test_company_alias_apple_english():
    r = understand_query("Apple stock price")
    company_ents = [e for e in r.entities if e.entity_type == "company"]
    assert any(e.resolved_value == "AAPL" for e in company_ents)


def test_company_alias_nvidia_hebrew():
    r = understand_query("כמה עולה אנבידיה?")
    company_ents = [e for e in r.entities if e.entity_type == "company"]
    assert any(e.resolved_value == "NVDA" for e in company_ents)


def test_benchmark_spy_note():
    r = understand_query("מה ההרכב של אסאנפי?")
    bench = [e for e in r.entities if e.entity_type == "benchmark"]
    assert bench
    assert bench[0].resolved_value == "SPY"
    assert bench[0].note is not None


# ── Phase 4A spec scenarios (observed runtime failures) ──────────────────────

def test_fx_hebrew_dollar_shekel_short():
    """'דולר שקל כמה?' — short Hebrew FX query must produce USD/ILS."""
    r = understand_query("דולר שקל כמה?")
    assert r.primary_intent == "fx_rate"
    isos = {e.resolved_value for e in r.entities if e.entity_type == "currency"}
    assert isos == {"USD", "ILS"}


def test_fx_hebrew_euro_vs_shekel():
    """'מה שער החליפין של היורו מול השקל' — must detect EUR + ILS, not USD."""
    r = understand_query("מה שער החליפין של היורו מול השקל")
    assert any(c.intent_type == "fx_rate" for c in r.intent_candidates)
    isos = {e.resolved_value for e in r.entities if e.entity_type == "currency"}
    assert "EUR" in isos
    assert "ILS" in isos
    assert "USD" not in isos


def test_price_lookup_hebrew_apple_via_hamniya():
    """'כמה המנייה של אפל שווה' — must trigger price_lookup with AAPL."""
    r = understand_query("כמה המנייה של אפל שווה")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "price_lookup" in intents
    assert r.slots.get("ticker") == "AAPL"


def test_price_lookup_hebrew_apple_with_explicit_ticker():
    """'תבדוק כמה עולה המנייה של אפל? AAPL' — price_lookup with AAPL."""
    r = understand_query("תבדוק כמה עולה המנייה של אפל? AAPL")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "price_lookup" in intents
    assert r.slots.get("ticker") == "AAPL"


def test_price_lookup_tesla_english():
    """'what is Tesla stock price?' — price_lookup with TSLA."""
    r = understand_query("what is Tesla stock price?")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "price_lookup" in intents
    assert r.slots.get("ticker") == "TSLA"


def test_macro_unemployment_hebrew():
    """'מה קורה עם האבטלה?' — macro_series UNRATE."""
    r = understand_query("מה קורה עם האבטלה?")
    assert any(c.intent_type == "macro_series" for c in r.intent_candidates)
    macro = [e for e in r.entities if e.entity_type == "macro_topic"]
    assert any(e.resolved_value == "UNRATE" for e in macro)


def test_macro_cpi_index_level_note():
    """CPIAUCNS must carry a semantic note that it is an index level."""
    r = understand_query("what is inflation doing?")
    macro = [e for e in r.entities if e.entity_type == "macro_topic"]
    cpi = next((e for e in macro if e.resolved_value == "CPIAUCNS"), None)
    assert cpi is not None
    assert cpi.note and "index level" in cpi.note.lower()
    assert any("index level" in n.lower() for n in r.notes)
    assert r.slots.get("series_semantic_type") == "index_level"


def test_macro_unemployment_semantic_percent():
    r = understand_query("מה קורה עם האבטלה?")
    assert r.slots.get("series_id") == "UNRATE"
    assert r.slots.get("series_semantic_type") == "percent"


def test_document_lookup_uploaded_quarterly_hebrew():
    """'יש לך גישה לדוח ריבעוני שהעליתי?' — must route document_lookup."""
    r = understand_query("יש לך גישה לדוח ריבעוני שהעליתי?")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "document_lookup" in intents
    docs = [e for e in r.entities if e.entity_type == "document"]
    assert docs


def test_document_lookup_summarize_hebrew_loose():
    """'תסכם לי את הדוח שהעליתי' — document_lookup with document entity."""
    r = understand_query("תסכם לי את הדוח שהעליתי")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "document_lookup" in intents
    assert r.primary_intent == "document_lookup"


def test_etf_holdings_hebrew_nasdaq_alias():
    """'מה ההחזקות של נאסדק?' — etf_holdings with QQQ proxy."""
    r = understand_query("מה ההחזקות של נאסדק?")
    intents = [c.intent_type for c in r.intent_candidates]
    assert "etf_holdings" in intents
    bench = [e for e in r.entities if e.entity_type == "benchmark"]
    assert any(e.resolved_value == "QQQ" for e in bench)


def test_advisory_what_do_you_think_nvda_not_factual():
    r = understand_query("what do you think about NVDA?")
    assert "advisory_tone_with_entity" in r.ambiguity_flags
    assert r.primary_intent != "price_lookup"
    assert r.primary_intent != "etf_holdings"


# ── Phase 4C: data_availability_lookup ───────────────────────────────────────

def test_data_availability_hebrew_which_stocks():
    r = understand_query("של איזה מניות כן יש לך?")
    assert r.primary_intent == "data_availability_lookup"


def test_data_availability_hebrew_which_prices():
    r = understand_query("איזה מחירי מניות יש לך?")
    assert r.primary_intent == "data_availability_lookup"


def test_data_availability_english_which_prices_available():
    r = understand_query("which stock prices are available?")
    assert r.primary_intent == "data_availability_lookup"


def test_data_availability_english_what_symbols():
    r = understand_query("what symbols do you have prices for?")
    assert r.primary_intent == "data_availability_lookup"


def test_price_lookup_still_wins_for_specific_ticker():
    # Sanity: a clear price question for a specific company is still
    # price_lookup, not the new data_availability intent.
    r = understand_query("מה שווי המניה של אפל?")
    assert r.primary_intent == "price_lookup"


def test_ambiguous_price_of_that():
    """'price of that' — phrase signal but no ticker → low confidence, no SQL slot."""
    r = understand_query("price of that")
    if r.primary_intent == "price_lookup":
        assert "missing_slot:ticker" in r.ambiguity_flags
        assert r.confidence < 0.75
    assert "ticker" not in r.slots


# ── Phase 4C.1: Hebrew ETF composition / condensed query phrases ──────────────

def test_etf_holdings_hebrew_spy_condensed_phrase():
    """מהם המרכיבים של קרן SPY? → etf_holdings, ticker=SPY."""
    r = understand_query("מהם המרכיבים של קרן SPY?")
    assert r.primary_intent == "etf_holdings"
    assert r.slots.get("ticker") == "SPY"


def test_etf_holdings_hebrew_mirkivei_hakeren():
    """מרכיבי הקרן SPY → etf_holdings, ticker=SPY."""
    r = understand_query("מרכיבי הקרן SPY")
    assert r.primary_intent == "etf_holdings"
    assert r.slots.get("ticker") == "SPY"


def test_etf_holdings_hebrew_harkav_keren():
    """הרכב קרן SPY → etf_holdings, ticker=SPY."""
    r = understand_query("הרכב קרן SPY")
    assert r.primary_intent == "etf_holdings"
    assert r.slots.get("ticker") == "SPY"


def test_etf_holdings_advisory_spy_not_holdings():
    """מה אתה חושב על SPY? → advisory, NOT etf_holdings."""
    r = understand_query("מה אתה חושב על SPY?")
    assert r.primary_intent != "etf_holdings"


def test_etf_holdings_hebrew_ma_kollelim():
    """מה כוללים הנכסים או המניות בתוך SPY? → etf_holdings, SPY."""
    r = understand_query("מה כוללים הנכסים או המניות בתוך SPY?")
    assert r.primary_intent == "etf_holdings"
    assert r.slots.get("ticker") == "SPY"


def test_etf_holdings_hebrew_eilu_menayot_bakeren():
    """אילו מניות יש בקרן SPY? → etf_holdings, SPY."""
    r = understand_query("אילו מניות יש בקרן SPY?")
    assert r.primary_intent == "etf_holdings"
    assert r.slots.get("ticker") == "SPY"
