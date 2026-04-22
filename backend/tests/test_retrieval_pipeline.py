"""
Retrieval pipeline integration tests: planner → executor → fusion.
No DB, no network, no LLM. Fake runners only.
Run: cd backend && pytest tests/test_retrieval_pipeline.py -v
"""
import pytest
from rag.planner import build_plan
from rag.executor import execute_plan
from rag.fusion import fuse
from rag.schemas import VectorFilter

OWNER = "user_test_123"

SQL_ROW  = {"base": "USD", "quote": "ILS", "rate": 3.7}
VEC_ROW  = {"text": "AAPL 10-K excerpt"}


async def _sql_runner(template_id: str, params: dict) -> list:
    return [SQL_ROW]

async def _vector_runner(vf: VectorFilter) -> list:
    return [VEC_ROW]


# ── 1. SQL-only flow ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sql_only_pipeline():
    plan    = build_plan("What is USD to ILS rate?", OWNER)
    results = await execute_plan(plan, OWNER, sql_runner=_sql_runner)
    fr      = fuse(plan, results)

    assert fr.structured_data.get("fx_rate") == [SQL_ROW]
    assert fr.supporting_context == []
    assert fr.retrieval_summary.has_sql is True
    assert fr.retrieval_summary.has_vector is False


# ── 2. VECTOR-only flow ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vector_only_pipeline():
    plan    = build_plan("Summarize AAPL 10-K filing", OWNER)
    results = await execute_plan(plan, OWNER, vector_runner=_vector_runner)
    fr      = fuse(plan, results)

    assert fr.supporting_context == [VEC_ROW]
    assert fr.structured_data == {}
    assert fr.retrieval_summary.has_vector is True
    assert fr.retrieval_summary.has_sql is False


# ── 3. HYBRID flow ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hybrid_pipeline():
    plan    = build_plan("How does inflation affect bond investors?", OWNER)
    results = await execute_plan(plan, OWNER,
                                 sql_runner=_sql_runner,
                                 vector_runner=_vector_runner)
    fr      = fuse(plan, results)

    assert fr.structured_data        # at least one SQL intent key
    assert fr.supporting_context     # at least one vector doc
    assert fr.retrieval_summary.has_sql is True
    assert fr.retrieval_summary.has_vector is True
    # strict separation: no vector rows inside structured_data values
    for rows in fr.structured_data.values():
        assert VEC_ROW not in rows
    # no SQL rows inside supporting_context
    assert SQL_ROW not in fr.supporting_context
