"""
Phase 4B.2 — Runtime Regression Matrix.

Each row pins the *expected deterministic routing* for a real-world user query.
The matrix is the contract: failures here mean planner/QU regressed.

Anything beyond routing (data coverage, cache, document quality, advisory
wording) is *not* asserted here — those are diagnosed separately in the
companion DB coverage test and reported in Phase 4B.2 notes.

Run:
    cd backend && pytest tests/test_runtime_regression_matrix.py -v

Optional DB-backed coverage test (skipped without DATABASE_URL):
    cd backend && RUN_DB_COVERAGE=1 pytest tests/test_runtime_regression_matrix.py::test_prices_data_coverage -v
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pytest

from rag.planner import build_plan


OWNER = "user_regression"


@dataclass
class ExpectRow:
    query: str
    expected_intents: list[str]
    expected_template_id: Optional[str] = None
    expected_params_subset: dict = field(default_factory=dict)
    expected_mode_hint: Optional[str] = None
    diagnostic_category: str = ""
    notes: str = ""


# ── The matrix ────────────────────────────────────────────────────────────────
# diagnostic_category is the *root cause class* if the live system fails this
# query — used by the report, not by assertions.
MATRIX: list[ExpectRow] = [
    ExpectRow(
        query="כמה המנייה של אפל שווה",
        expected_intents=["price_lookup"],
        expected_template_id="price_lookup_30d",
        expected_params_subset={"ticker": "AAPL"},
        expected_mode_hint="factual",
        diagnostic_category="data_coverage:prices",
        notes="Routing OK — empty rows in live runtime = AAPL missing from prices table.",
    ),
    ExpectRow(
        query="what is Tesla stock price?",
        expected_intents=["price_lookup"],
        expected_template_id="price_lookup_30d",
        expected_params_subset={"ticker": "TSLA"},
        expected_mode_hint="factual",
        diagnostic_category="data_coverage:prices",
        notes="Routing OK — empty rows in live runtime = TSLA missing from prices table.",
    ),
    ExpectRow(
        query="מה יש בתוך SPY?",
        expected_intents=["etf_holdings"],
        expected_template_id="etf_holdings_top20",
        expected_params_subset={"symbol": "SPY"},
        expected_mode_hint="factual",
        diagnostic_category="routing_or_cache_or_holdings_coverage",
        notes=(
            "If /chat/debug shows etf_holdings SPY with rows>0 but live answer is generic, "
            "root cause is cache or PromptAssembler context. If rows=0, holdings ingestion gap."
        ),
    ),
    ExpectRow(
        query="מה שער היורו מול השקל",
        expected_intents=["fx_rate"],
        expected_template_id="fx_rate_latest",
        expected_params_subset={"base": "EUR", "quote": "ILS"},
        expected_mode_hint="factual",
        diagnostic_category="working",
        notes="Working in runtime. Citation spacing ('2026S1') is a separate prompt formatting issue.",
    ),
    ExpectRow(
        query="תסכם לי את הדוח שהעליתי",
        expected_intents=["document_lookup"],
        expected_template_id=None,
        diagnostic_category="document_quality",
        notes="Routes correctly; weak summary = Hebrew RTL/extraction quality (Phase 4D).",
    ),
    ExpectRow(
        query="יש לך גישה לדוח ריבעוני שהעליתי?",
        expected_intents=["document_lookup"],
        expected_template_id=None,
        diagnostic_category="document_quality",
        notes="Routes correctly; same RTL/extraction concern.",
    ),
    ExpectRow(
        query="what do you think about NVDA?",
        expected_intents=[],  # advisory — expect non-factual routing
        diagnostic_category="advisory_routing",
        notes=(
            "Advisory tone + ticker → QU should flag advisory_tone_with_entity and NOT "
            "force factual price_lookup. Asserted indirectly: no price_lookup step."
        ),
    ),
    ExpectRow(
        query="יש מניות ספציפיות שאתה ממליץ עליהם?",
        expected_intents=[],
        diagnostic_category="advisory_policy_risk",
        notes=(
            "Phase 4E — advisory wording guard. RecommendationAgent or LLM should not "
            "produce direct stock picks. Not asserted here; flagged for separate phase."
        ),
    ),
    ExpectRow(
        query="מה כוללים הנכסים או המניות בתוך SPY?",
        expected_intents=["etf_holdings"],
        expected_template_id="etf_holdings_top20",
        expected_params_subset={"symbol": "SPY"},
        expected_mode_hint="factual",
        diagnostic_category="routing_or_cache_or_holdings_coverage",
        notes="Phase 4C.1 — condensed Hebrew ETF phrase with כוללים.",
    ),
    ExpectRow(
        query="מהם המרכיבים של קרן SPY?",
        expected_intents=["etf_holdings"],
        expected_template_id="etf_holdings_top20",
        expected_params_subset={"symbol": "SPY"},
        expected_mode_hint="factual",
        diagnostic_category="routing_or_cache_or_holdings_coverage",
        notes=(
            "Phase 4C.1 — condensed Hebrew ETF phrase. "
            "'מרכיבים' (components) + explicit ticker SPY must route to SQL etf_holdings. "
            "Live answer depends on etf_holdings table coverage for SPY."
        ),
    ),
    ExpectRow(
        query="של איזה מניות כן יש לך?",
        expected_intents=["data_availability_lookup"],
        expected_template_id="data_availability_prices_summary",
        expected_params_subset={},
        expected_mode_hint="factual",
        diagnostic_category="working_if_prices_table_has_rows",
        notes=(
            "Phase 4C — deterministic data_availability_lookup against `prices` "
            "(SELECT symbol, COUNT(*), MAX(date) GROUP BY symbol). Live answer "
            "depends on rows actually present in the prices table."
        ),
    ),
]


def _intent_types(plan) -> list[str]:
    return [s.intent_type for s in plan.steps]


def _params_for(plan, intent_type: str) -> dict:
    for s in plan.steps:
        if s.intent_type == intent_type:
            return dict(s.parameters or {})
    return {}


@pytest.mark.parametrize("row", MATRIX, ids=[r.query for r in MATRIX])
def test_matrix_routing(row: ExpectRow):
    plan = build_plan(row.query, OWNER)
    intents = _intent_types(plan)

    # Expected intents must each appear (subset semantics — extra hybrid steps allowed)
    for expected in row.expected_intents:
        assert expected in intents, (
            f"[{row.diagnostic_category}] expected intent '{expected}' not in {intents} "
            f"for query: {row.query!r}"
        )

    # If row expects advisory routing (empty expected_intents) we assert NO factual
    # SQL step was forced.
    if not row.expected_intents and row.diagnostic_category in (
        "advisory_routing",
        "advisory_policy_risk",
    ):
        forbidden = {"price_lookup", "etf_holdings", "fx_rate", "macro_series"}
        forced = [i for i in intents if i in forbidden]
        assert not forced, (
            f"advisory query {row.query!r} should not force factual SQL, got {forced}"
        )

    # Template id check (only when an SQL intent was expected)
    if row.expected_template_id and row.expected_intents:
        primary = row.expected_intents[0]
        for s in plan.steps:
            if s.intent_type == primary:
                assert s.sql_template_id == row.expected_template_id, (
                    f"template mismatch for {primary}: got {s.sql_template_id} "
                    f"expected {row.expected_template_id}"
                )
                break

    # Params subset check
    if row.expected_params_subset and row.expected_intents:
        params = _params_for(plan, row.expected_intents[0])
        for k, v in row.expected_params_subset.items():
            assert params.get(k) == v, (
                f"params for {row.expected_intents[0]} missing {k}={v}; got {params}"
            )

    # Mode hint
    if row.expected_mode_hint:
        assert plan.plan_meta.mode_hint == row.expected_mode_hint, (
            f"mode_hint mismatch: got {plan.plan_meta.mode_hint} "
            f"expected {row.expected_mode_hint} for {row.query!r}"
        )


def test_matrix_print_diagnosis(capsys):
    """Emits a human-readable matrix snapshot. Useful for the report."""
    lines = ["", "Runtime Regression Matrix snapshot:", ""]
    for row in MATRIX:
        plan = build_plan(row.query, OWNER)
        intents = _intent_types(plan)
        params = [dict(s.parameters or {}) for s in plan.steps]
        lines.append(
            f"- {row.query!r}\n"
            f"    intents={intents} params={params} "
            f"mode={plan.plan_meta.mode_hint} category={row.diagnostic_category}"
        )
    snapshot = "\n".join(lines)
    print(snapshot)
    # Always passes — diagnostic only.
    assert True


# ── Optional DB-backed prices coverage diagnosis ──────────────────────────────

@pytest.mark.asyncio
async def test_prices_data_coverage():
    """
    Diagnose `prices` table coverage. Skipped unless RUN_DB_COVERAGE=1 is set,
    so default test runs stay hermetic.

    Reports symbols, row counts, and latest date — answers:
    - Is AAPL/TSLA missing entirely? → ingestion gap.
    - Is SPY present? → if so, etf_holdings empty result is a holdings table issue.
    """
    if os.getenv("RUN_DB_COVERAGE") != "1":
        pytest.skip("Set RUN_DB_COVERAGE=1 to run DB coverage diagnosis.")

    import asyncpg
    from core.config import DATABASE_URL

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT symbol, COUNT(*) AS row_count, MAX(date) AS latest_date "
            "FROM prices GROUP BY symbol ORDER BY symbol"
        )
        coverage = {r["symbol"]: (r["row_count"], r["latest_date"]) for r in rows}
        print("\nPrices coverage:")
        for sym, (cnt, latest) in coverage.items():
            print(f"  {sym}: rows={cnt} latest={latest}")
        for must in ("AAPL", "TSLA", "SPY"):
            present = must in coverage
            print(f"  diagnosis[{must}]: {'PRESENT' if present else 'MISSING'}")
    finally:
        await conn.close()
