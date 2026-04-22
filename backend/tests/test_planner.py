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
