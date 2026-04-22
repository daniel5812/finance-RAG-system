"""
Critical Executor MVP tests — pure unit, no DB, no network, no LLM.
Run: cd backend && pytest tests/test_executor.py -v
"""
import pytest
from rag.executor import execute_plan
from rag.schemas import HybridQueryPlan, PlanStep, PlanMeta, VectorFilter

OWNER = "user_test_123"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _plan(*steps: PlanStep) -> HybridQueryPlan:
    return HybridQueryPlan(
        steps=list(steps),
        plan_meta=PlanMeta(total_steps=len(steps), is_hybrid=False, fusion_required=False),
    )

def _sql_step(step_id=1, template_id="fx_rate_latest", priority=1) -> PlanStep:
    return PlanStep(
        step_id=step_id, source_type="SQL", intent_type="fx_rate",
        parameters={"base": "USD", "quote": "ILS"},
        sql_template_id=template_id, priority=priority,
    )

def _vector_step(step_id=1, owner_id=OWNER, doc_type="filing", priority=1) -> PlanStep:
    return PlanStep(
        step_id=step_id, source_type="VECTOR", intent_type="filing_lookup",
        vector_filter=VectorFilter(owner_id=owner_id, doc_type=doc_type),
        priority=priority,
    )

def _no_match_step(step_id=1, priority=1) -> PlanStep:
    return PlanStep(
        step_id=step_id, source_type="NO_MATCH", intent_type="no_match",
        vector_filter=VectorFilter(owner_id=OWNER),
        priority=priority,
    )

async def _raising_runner(*args, **kwargs):
    raise RuntimeError("boom")


# ── 1. SQL step, no runner → empty ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_sql_no_runner_returns_empty():
    results = await execute_plan(_plan(_sql_step()), OWNER, sql_runner=None)
    assert results[0].status == "empty"
    assert results[0].data == []


# ── 2. SQL step missing sql_template_id → error ───────────────────────────────

@pytest.mark.asyncio
async def test_sql_missing_template_id_returns_error():
    step = _sql_step(template_id=None)
    results = await execute_plan(_plan(step), OWNER)
    assert results[0].status == "error"
    assert results[0].error_message is not None


# ── 3. VECTOR step enforces owner_id ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_vector_enforces_owner_id():
    captured = {}

    async def capture_runner(vf: VectorFilter):
        captured["owner_id"] = vf.owner_id
        return [{"text": "doc"}]

    step = _vector_step(owner_id="wrong_owner")
    results = await execute_plan(_plan(step), OWNER, vector_runner=capture_runner)
    assert captured["owner_id"] == OWNER
    assert results[0].status == "ok"


# ── 4. NO_MATCH uses VECTOR path with owner-scoped filter ─────────────────────

@pytest.mark.asyncio
async def test_no_match_uses_vector_path():
    captured = {}

    async def capture_runner(vf: VectorFilter):
        captured["owner_id"] = vf.owner_id
        captured["doc_type"] = vf.doc_type
        return []

    results = await execute_plan(_plan(_no_match_step()), OWNER, vector_runner=capture_runner)
    assert captured["owner_id"] == OWNER
    assert captured.get("doc_type") is None   # broad filter, no doc_type restriction
    assert results[0].status == "empty"


# ── 5. One failing step does not abort full execution ─────────────────────────

@pytest.mark.asyncio
async def test_failing_step_does_not_abort():
    steps = [_vector_step(step_id=1), _vector_step(step_id=2)]
    call_count = {"n": 0}

    async def flaky_runner(vf: VectorFilter):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient failure")
        return [{"text": "ok"}]

    results = await execute_plan(_plan(*steps), OWNER, vector_runner=flaky_runner)
    assert len(results) == 2
    assert results[0].status == "error"
    assert results[1].status == "ok"


# ── 6. Steps processed in priority order ──────────────────────────────────────

@pytest.mark.asyncio
async def test_steps_processed_in_priority_order():
    order = []

    async def tracking_runner(vf: VectorFilter):
        order.append(vf.doc_type)
        return []

    low  = PlanStep(step_id=1, source_type="VECTOR", intent_type="filing_lookup",
                    vector_filter=VectorFilter(owner_id=OWNER, doc_type="filing"), priority=2)
    high = PlanStep(step_id=2, source_type="VECTOR", intent_type="knowledge_query",
                    vector_filter=VectorFilter(owner_id=OWNER, doc_type="knowledge"), priority=1)

    results = await execute_plan(_plan(low, high), OWNER, vector_runner=tracking_runner)
    assert order == ["knowledge", "filing"]   # priority 1 before 2
