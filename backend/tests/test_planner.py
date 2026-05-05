"""
Critical Planner MVP tests — minimal, pure unit, no external deps.
Run: cd backend && pytest tests/test_planner.py -v
"""
from rag.planner import build_plan

OWNER = "user_test_123"


# ── SQL path ──────────────────────────────────────────────────────────────────

def test_sql_fx_rate():
    plan = build_plan("What is USD to ILS rate?", OWNER)
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "fx_rate"
    assert s.parameters["base"] == "USD"
    assert s.parameters["quote"] == "ILS"
    assert s.sql_template_id == "fx_rate_latest"
    assert s.vector_filter is None


# ── VECTOR path ───────────────────────────────────────────────────────────────

def test_vector_filing():
    plan = build_plan("Summarize AAPL 10-K filing", OWNER)
    s = plan.steps[0]
    assert s.source_type == "VECTOR"
    assert s.intent_type == "filing_lookup"
    assert s.vector_filter.owner_id == OWNER
    assert s.vector_filter.doc_type == "filing"


# ── NO_MATCH path ─────────────────────────────────────────────────────────────

def test_no_match():
    plan = build_plan("Hello world", OWNER)
    s = plan.steps[0]
    assert s.source_type == "NO_MATCH"
    assert s.vector_filter is not None
    assert s.vector_filter.owner_id == OWNER


# ── HYBRID path ───────────────────────────────────────────────────────────────

def test_hybrid_sql_plus_vector():
    plan = build_plan("How does inflation affect bond investors?", OWNER)
    sources = {s.source_type for s in plan.steps}
    assert "SQL" in sources and "VECTOR" in sources
    assert plan.plan_meta.is_hybrid is True
    assert plan.plan_meta.fusion_required is True


# ── Safety / invariants ───────────────────────────────────────────────────────

def test_owner_id_always_in_vector_filter():
    for query in [
        "Summarize my documents",
        "Hello world",
        "Summarize AAPL 10-K",
        "How does inflation affect bonds?",
    ]:
        plan = build_plan(query, OWNER)
        for s in plan.steps:
            if s.vector_filter is not None:
                assert s.vector_filter.owner_id == OWNER, (
                    f"owner_id missing: query='{query}', step={s.intent_type}"
                )


def test_max_steps_not_exceeded():
    plan = build_plan(
        "What is USD/ILS, inflation, summarize AAPL 10-K and explain the risk?",
        OWNER,
    )
    assert plan.plan_meta.total_steps <= 3


# ── mode_hint ─────────────────────────────────────────────────────────────────

def test_mode_hint_fx_rate():
    plan = build_plan("What is USD to ILS rate?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_price_lookup():
    plan = build_plan("What is the AAPL stock price?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_etf_holdings():
    plan = build_plan("What are the top holdings of SPY ETF?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_portfolio_lookup():
    plan = build_plan("What is in my portfolio?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_macro_series():
    plan = build_plan("What is the current inflation rate?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_document_lookup_is_advisory():
    plan = build_plan("Summarize my uploaded document", OWNER)
    assert plan.plan_meta.mode_hint == "advisory"


def test_mode_hint_no_match_is_advisory():
    plan = build_plan("Hello world", OWNER)
    assert plan.plan_meta.mode_hint == "advisory"


def test_mode_hint_hybrid_sql_plus_vector_is_advisory():
    plan = build_plan("How does inflation affect bond investors?", OWNER)
    assert plan.plan_meta.is_hybrid is True
    assert plan.plan_meta.mode_hint == "advisory"


def test_mode_hint_multiple_factual_sql_only():
    # fx_rate + macro_series — both SQL, both factual → factual
    plan = build_plan("What is USD to EUR rate and the current inflation rate?", OWNER)
    all_sql = all(s.source_type == "SQL" for s in plan.steps)
    assert all_sql
    assert plan.plan_meta.mode_hint == "factual"


def test_mode_hint_invalid_params_become_advisory():
    # portfolio_lookup with no owner_id fails _resolve_sql → NO_MATCH step → advisory
    plan = build_plan("What is in my portfolio?", owner_id="")
    assert plan.plan_meta.mode_hint == "advisory"


# ── Phase 4A: QueryUnderstanding-augmented planner tests ──────────────────────

def test_qu_advisory_tone_entity_not_factual():
    """'מה הסיפור עם אפל?' — advisory tone with entity must not produce factual SQL."""
    plan = build_plan("מה הסיפור עם אפל?", OWNER)
    assert plan.plan_meta.mode_hint == "advisory"
    assert all(s.source_type != "SQL" for s in plan.steps)


def test_qu_advisory_tone_spy_not_etf_holdings():
    """'מה אתה חושב על אסאנפי?' — advisory tone must not produce etf_holdings SQL."""
    plan = build_plan("מה אתה חושב על אסאנפי?", OWNER)
    assert plan.plan_meta.mode_hint == "advisory"
    assert all(s.intent_type != "etf_holdings" for s in plan.steps)


def test_qu_existing_factual_paths_preserved():
    """Existing factual paths must not regress after QU integration."""
    plan = build_plan("What is USD to ILS rate?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    assert plan.steps[0].source_type == "SQL"
    assert plan.steps[0].intent_type == "fx_rate"


def test_qu_existing_price_lookup_preserved():
    plan = build_plan("What is the AAPL stock price?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.intent_type == "price_lookup"
    assert s.parameters["ticker"] == "AAPL"


def test_qu_existing_etf_holdings_preserved():
    plan = build_plan("What are the top holdings of SPY ETF?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.intent_type == "etf_holdings"
    assert s.parameters["symbol"] == "SPY"


def test_qu_vague_query_is_advisory():
    """Highly ambiguous query must remain advisory/no_match."""
    plan = build_plan("תראה לי את זה", OWNER)
    assert plan.plan_meta.mode_hint == "advisory"
    assert all(s.source_type != "SQL" for s in plan.steps)


# ── Phase 4A: free-form runtime regressions ──────────────────────────────────

def test_qu_euro_exchange_eur_ils_factual():
    """'what is the euro exchange rate?' → fx_rate EUR/ILS, factual."""
    plan = build_plan("what is the euro exchange rate?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "fx_rate"
    assert s.parameters["base"] == "EUR"
    assert s.parameters["quote"] == "ILS"


def test_qu_euro_vs_shekel_hebrew_factual():
    """'מה שער החליפין של היורו מול השקל' → fx_rate EUR/ILS, not USD/ILS."""
    plan = build_plan("מה שער החליפין של היורו מול השקל", OWNER)
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "fx_rate"
    assert s.parameters["base"] == "EUR"
    assert s.parameters["quote"] == "ILS"


def test_qu_apple_hebrew_price_lookup():
    """'כמה המנייה של אפל שווה' → SQL price_lookup AAPL, factual."""
    plan = build_plan("כמה המנייה של אפל שווה", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "price_lookup"
    assert s.parameters["ticker"] == "AAPL"


def test_qu_tesla_english_price_lookup():
    """'what is Tesla stock price?' → SQL price_lookup TSLA, factual."""
    plan = build_plan("what is Tesla stock price?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "price_lookup"
    assert s.parameters["ticker"] == "TSLA"


def test_qu_hebrew_spy_holdings_factual():
    """'מה יש בתוך SPY?' → SQL etf_holdings SPY, factual."""
    plan = build_plan("מה יש בתוך SPY?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "etf_holdings"
    assert s.parameters["symbol"] == "SPY"


def test_qu_hebrew_unemployment_macro_factual():
    """'מה קורה עם האבטלה?' → macro_series UNRATE, factual."""
    plan = build_plan("מה קורה עם האבטלה?", OWNER)
    assert plan.plan_meta.mode_hint == "factual"
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "macro_series"
    assert s.parameters["series_id"] == "UNRATE"


def test_qu_uploaded_quarterly_report_routes_to_document():
    """'יש לך גישה לדוח ריבעוני שהעליתי?' → vector/document, not macro/SQL."""
    plan = build_plan("יש לך גישה לדוח ריבעוני שהעליתי?", OWNER)
    assert all(s.source_type != "SQL" for s in plan.steps)
    intents = {s.intent_type for s in plan.steps}
    assert "macro_series" not in intents
    # at least one step routes to document or vector path
    assert any(s.intent_type == "document_lookup" or s.source_type == "VECTOR" for s in plan.steps)


def test_qu_what_do_you_think_nvda_not_factual_price():
    """'what do you think about NVDA?' → not factual price_lookup."""
    plan = build_plan("what do you think about NVDA?", OWNER)
    assert all(s.intent_type != "price_lookup" for s in plan.steps)
    assert plan.plan_meta.mode_hint == "advisory"


def test_qu_existing_usd_to_eur_preserved():
    """'What is USD to EUR rate?' → SQL fx_rate USD/EUR, factual."""
    plan = build_plan("What is USD to EUR rate?", OWNER)
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "fx_rate"
    assert s.parameters["base"] == "USD"
    assert s.parameters["quote"] == "EUR"


# ── Phase 4C: data_availability_lookup ───────────────────────────────────────

def test_data_availability_hebrew_builds_sql_factual():
    plan = build_plan("של איזה מניות כן יש לך?", OWNER)
    assert len(plan.steps) == 1
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "data_availability_lookup"
    assert s.sql_template_id == "data_availability_prices_summary"
    assert s.parameters == {}
    assert plan.plan_meta.mode_hint == "factual"


def test_data_availability_english_builds_sql_factual():
    plan = build_plan("which stock prices are available?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "data_availability_lookup" in intents
    assert all(s.source_type == "SQL" for s in plan.steps)
    assert plan.plan_meta.mode_hint == "factual"


def test_data_availability_does_not_require_ticker_param():
    plan = build_plan("איזה מחירי מניות יש לך?", OWNER)
    s = plan.steps[0]
    assert s.intent_type == "data_availability_lookup"
    assert "ticker" not in (s.parameters or {})
    assert "symbol" not in (s.parameters or {})


def test_data_availability_suppresses_price_lookup():
    # Phrases overlap with price_lookup keywords ("מחיר", "מניה");
    # planner must not also emit price_lookup.
    plan = build_plan("איזה מחירי מניות יש לך?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "price_lookup" not in intents
    assert "etf_holdings" not in intents


# ── Phase 4C.1: Hebrew ETF composition / condensed query phrases ──────────────

def test_etf_holdings_hebrew_condensed_phrase():
    """מהם המרכיבים של קרן SPY? → SQL etf_holdings SPY, factual."""
    plan = build_plan("מהם המרכיבים של קרן SPY?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "etf_holdings" in intents
    for s in plan.steps:
        if s.intent_type == "etf_holdings":
            assert s.source_type == "SQL"
            assert s.sql_template_id == "etf_holdings_top20"
            assert s.parameters.get("symbol") == "SPY"
    assert plan.plan_meta.mode_hint == "factual"


def test_etf_holdings_hebrew_mirkivei():
    """מרכיבי QQQ → SQL etf_holdings QQQ."""
    plan = build_plan("מרכיבי QQQ", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "etf_holdings" in intents
    for s in plan.steps:
        if s.intent_type == "etf_holdings":
            assert s.parameters.get("symbol") == "QQQ"


def test_etf_holdings_hebrew_kollelim():
    """מה כוללים הנכסים או המניות בתוך SPY? → SQL etf_holdings SPY."""
    plan = build_plan("מה כוללים הנכסים או המניות בתוך SPY?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "etf_holdings" in intents
    for s in plan.steps:
        if s.intent_type == "etf_holdings":
            assert s.parameters.get("symbol") == "SPY"
    assert plan.plan_meta.mode_hint == "factual"


def test_etf_holdings_hebrew_eilu_bakeren():
    """אילו מניות יש בקרן SPY? → SQL etf_holdings SPY."""
    plan = build_plan("אילו מניות יש בקרן SPY?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "etf_holdings" in intents
    for s in plan.steps:
        if s.intent_type == "etf_holdings":
            assert s.parameters.get("symbol") == "SPY"
