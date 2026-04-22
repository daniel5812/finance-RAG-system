"""
Critical Fusion MVP tests — pure unit, no DB, no network, no async.
Run: cd backend && pytest tests/test_fusion.py -v
"""
from rag.fusion import fuse
from rag.schemas import (
    HybridQueryPlan, PlanMeta, PlanStep,
    StepResult, VectorFilter,
)

# ── Minimal builders ──────────────────────────────────────────────────────────

def _plan(*source_types: str) -> HybridQueryPlan:
    steps = [
        PlanStep(step_id=i, source_type=st, intent_type=f"intent_{i}")
        for i, st in enumerate(source_types, 1)
    ]
    return HybridQueryPlan(
        steps=steps,
        plan_meta=PlanMeta(total_steps=len(steps), is_hybrid=False, fusion_required=False),
    )

def _sql_ok(intent="fx_rate", data=None) -> StepResult:
    return StepResult(step_id=1, source_type="SQL", intent_type=intent,
                      data=data or [{"rate": 3.7}], status="ok")

def _vector_ok(intent="filing_lookup", data=None) -> StepResult:
    return StepResult(step_id=2, source_type="VECTOR", intent_type=intent,
                      data=data or [{"text": "doc"}], status="ok")

def _empty(source="SQL", intent="macro_series") -> StepResult:
    return StepResult(step_id=3, source_type=source, intent_type=intent,
                      data=[], status="empty")

def _error(source="SQL", intent="price_lookup") -> StepResult:
    return StepResult(step_id=4, source_type=source, intent_type=intent,
                      data=[], status="error", error_message="timeout")


# ── 1. SQL-only ───────────────────────────────────────────────────────────────

def test_sql_only():
    fr = fuse(_plan("SQL"), [_sql_ok()])
    assert fr.structured_data == {"fx_rate": [{"rate": 3.7}]}
    assert fr.supporting_context == []
    assert fr.retrieval_summary.has_sql is True
    assert fr.retrieval_summary.has_vector is False


# ── 2. VECTOR-only ────────────────────────────────────────────────────────────

def test_vector_only():
    fr = fuse(_plan("VECTOR"), [_vector_ok()])
    assert fr.supporting_context == [{"text": "doc"}]
    assert fr.structured_data == {}
    assert fr.retrieval_summary.has_vector is True
    assert fr.retrieval_summary.has_sql is False


# ── 3. HYBRID — strict separation ────────────────────────────────────────────

def test_hybrid_separation():
    fr = fuse(_plan("SQL", "VECTOR"), [_sql_ok(), _vector_ok()])
    assert "fx_rate" in fr.structured_data
    assert fr.supporting_context == [{"text": "doc"}]
    # nothing bleeds across the boundary
    assert "fx_rate" not in fr.supporting_context
    assert fr.structured_data.get("filing_lookup") is None


# ── 4. empty / error → missing_data_notes, is_partial ────────────────────────

def test_empty_and_error_go_to_notes():
    fr = fuse(_plan("SQL", "SQL"), [_empty(), _error()])
    assert fr.structured_data == {}
    assert fr.supporting_context == []
    assert len(fr.missing_data_notes) == 2
    assert any("empty" in n for n in fr.missing_data_notes)
    assert any("timeout" in n for n in fr.missing_data_notes)
    assert fr.retrieval_summary.is_partial is True


# ── 5. plan-aware: fewer results than planned steps → is_partial ──────────────

def test_plan_aware_partial_when_results_missing():
    # Plan has 2 steps; only 1 result delivered
    fr = fuse(_plan("SQL", "VECTOR"), [_sql_ok()])
    assert fr.retrieval_summary.is_partial is True
    # Plan declared VECTOR even though no VECTOR result came back
    assert fr.retrieval_summary.has_vector is True


# ── 6. user_profile → advisory_context only ──────────────────────────────────

def test_profile_advisory_only():
    profile = {"risk_tolerance": "low", "experience_level": "beginner"}
    fr = fuse(_plan("SQL"), [_sql_ok()], user_profile=profile)
    assert fr.retrieval_summary.advisory_context == profile
    # profile must not appear anywhere in data
    assert "risk_tolerance" not in fr.structured_data
    assert not any("risk_tolerance" in str(item) for item in fr.supporting_context)
