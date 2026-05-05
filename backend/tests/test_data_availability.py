"""
Phase 4C — data_availability_lookup intent.

Deterministic, no LLM. Verifies:
  - QueryUnderstanding routes availability questions to data_availability_lookup
  - Planner emits a single SQL step with the prices-summary template
  - Executor injects a clear no-data note when price_lookup returns 0 rows
  - Optional DB-backed coverage check (skipped without RUN_DB_COVERAGE=1)

Run:
    docker compose exec api pytest tests/test_data_availability.py -v
"""
from __future__ import annotations

import asyncio
import os

import pytest

from rag.executor import execute_plan
from rag.planner import build_plan
from rag.query_understanding import understand_query
from rag.schemas import HybridQueryPlan, PlanMeta, PlanStep


OWNER = "user_avail_test"


# ── QueryUnderstanding ────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "של איזה מניות כן יש לך?",
    "איזה מחירי מניות יש לך?",
    "אילו סימבולים זמינים?",
    "which stock prices are available?",
    "what symbols do you have prices for?",
    "what tickers do you have?",
])
def test_qu_routes_to_data_availability(query: str):
    r = understand_query(query)
    assert r.primary_intent == "data_availability_lookup", (
        f"expected data_availability_lookup, got {r.primary_intent} for {query!r}"
    )


@pytest.mark.parametrize("query, ticker", [
    ("מה שווי המניה של אפל?", "AAPL"),
    ("what is Tesla stock price?", "TSLA"),
])
def test_qu_specific_price_query_remains_price_lookup(query: str, ticker: str):
    r = understand_query(query)
    assert r.primary_intent == "price_lookup"
    assert r.slots.get("ticker") == ticker


# ── Planner ───────────────────────────────────────────────────────────────────

def test_planner_data_availability_factual_sql():
    plan = build_plan("של איזה מניות כן יש לך?", OWNER)
    assert len(plan.steps) == 1
    s = plan.steps[0]
    assert s.source_type == "SQL"
    assert s.intent_type == "data_availability_lookup"
    assert s.sql_template_id == "data_availability_prices_summary"
    assert s.parameters == {}
    assert plan.plan_meta.mode_hint == "factual"


def test_planner_no_required_ticker_for_availability():
    plan = build_plan("what symbols do you have prices for?", OWNER)
    s = plan.steps[0]
    assert s.intent_type == "data_availability_lookup"
    assert "ticker" not in (s.parameters or {})


def test_planner_does_not_double_route_with_price_lookup():
    plan = build_plan("איזה מחירי מניות יש לך?", OWNER)
    intents = [s.intent_type for s in plan.steps]
    assert "data_availability_lookup" in intents
    assert "price_lookup" not in intents


# ── Executor: empty price_lookup behavior ─────────────────────────────────────

def _price_plan(ticker: str) -> HybridQueryPlan:
    step = PlanStep(
        step_id=1,
        source_type="SQL",
        intent_type="price_lookup",
        parameters={"ticker": ticker},
        sql_template_id="price_lookup_30d",
        vector_filter=None,
        priority=1,
        execution_mode="sequential",
    )
    return HybridQueryPlan(
        steps=[step],
        plan_meta=PlanMeta(
            total_steps=1,
            is_hybrid=False,
            fusion_required=False,
            mode_hint="factual",
        ),
    )


def test_executor_empty_price_lookup_emits_no_data_note():
    async def empty_runner(_template_id: str, _params: dict):
        return []

    plan = _price_plan("AAPL")
    results = asyncio.run(execute_plan(plan, OWNER, sql_runner=empty_runner))
    assert len(results) == 1
    r = results[0]
    assert r.intent_type == "price_lookup"
    assert r.data, "expected deterministic no_data row, got empty data"
    note_row = r.data[0]
    assert note_row.get("ticker") == "AAPL"
    assert note_row.get("rows_found") == 0
    assert "AAPL" in note_row.get("no_data", "")
    assert "local database" in note_row.get("no_data", "").lower()


def test_executor_non_empty_price_lookup_unchanged():
    async def populated_runner(_template_id: str, _params: dict):
        return [{"symbol": "SPY", "date": "2026-04-28", "close": 500.0}]

    plan = _price_plan("SPY")
    results = asyncio.run(execute_plan(plan, OWNER, sql_runner=populated_runner))
    assert results[0].data == [{"symbol": "SPY", "date": "2026-04-28", "close": 500.0}]


# ── Optional DB-backed coverage probe ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_availability_db_returns_seed_symbols():
    """
    With RUN_DB_COVERAGE=1, run the actual data_availability template against
    the live DB and confirm SPY/QQQ are present (seeded at startup).
    """
    if os.getenv("RUN_DB_COVERAGE") != "1":
        pytest.skip("Set RUN_DB_COVERAGE=1 to run the DB-backed availability check.")

    import asyncpg
    from core.config import DATABASE_URL

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT symbol, COUNT(*) AS row_count, MAX(date) AS latest_date "
            "FROM prices GROUP BY symbol ORDER BY symbol"
        )
        symbols = {r["symbol"] for r in rows}
        for required in ("SPY", "QQQ"):
            assert required in symbols, f"{required} should be seeded in prices table"
    finally:
        await conn.close()
