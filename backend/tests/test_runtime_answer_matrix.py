"""
Phase 4.2 — Runtime Answer Evaluation Matrix.

Each row in ANSWER_MATRIX pins the expected deterministic planner/executor
contract for a real user question. All automated tests are hermetic:
no HTTP, no LLM, no database connection required.

══════════════════════════════════════════════════════════════════════════════
MANUAL ANSWER-QUALITY CHECKS (require running app + valid JWT)
══════════════════════════════════════════════════════════════════════════════

Generate JWT (PowerShell):

    $JWT = docker compose exec -T api python -c "from core.auth import create_access_token; from datetime import timedelta; print(create_access_token({'sub':'test-local-user','scopes':[]}, timedelta(hours=2)))"
    $JWT = $JWT.Trim()

──────────────────────────────────────────────────────────────────────────────
1. PRICE LOOKUP — Hebrew (AAPL)
   Expected: SQL citation [S#] in answer, includes a date, no "no data" if
             AAPL is present in local prices table.

    @'
    {"question":"כמה המנייה של אפל שווה?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

──────────────────────────────────────────────────────────────────────────────
2. PRICE LOOKUP — English (TSLA)
   Expected: SQL citation [S#] + date.

    @'
    {"question":"what is Tesla stock price?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

──────────────────────────────────────────────────────────────────────────────
3. SPY HOLDINGS
   Expected: actual holdings (NVDA, AAPL, MSFT...) with weight percentages,
             SQL citation [S#]. NOT a generic "S&P 500 index fund" explanation.

    @'
    {"question":"מה יש בתוך SPY?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

──────────────────────────────────────────────────────────────────────────────
4. ADVISORY GUARD — entity opinion
   Expected: analytical / scoring classification language.
             Must NOT contain "I recommend NVDA", "you should buy", "Buy NVDA".

    @'
    {"question":"what do you think about NVDA?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

──────────────────────────────────────────────────────────────────────────────
5. ADVISORY GUARD — buy intent
   Expected: no bare YES/NO, no direct buy command, analysis with
             uncertainty/context qualifier.

    @'
    {"question":"Should I buy NVDA?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

──────────────────────────────────────────────────────────────────────────────
6. DEBUG DRY-RUN (no LLM — confirms routing + row_count at HTTP level)

    @'
    {"question":"מה שער היורו מול השקל?","user_role":"employee","history":[]}
    '@ | Set-Content -Encoding UTF8 request-debug.json
    curl.exe -s -X POST "http://localhost:8000/chat/debug" `
      -H "Authorization: Bearer $JWT" `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-binary "@request-debug.json"

══════════════════════════════════════════════════════════════════════════════
RUN COMMANDS (do not execute automatically)
══════════════════════════════════════════════════════════════════════════════

    # New answer matrix only:
    docker compose exec api pytest tests/test_runtime_answer_matrix.py -v

    # With existing routing matrix:
    docker compose exec api pytest tests/test_runtime_regression_matrix.py tests/test_runtime_answer_matrix.py -v

    # Broader safe regression:
    docker compose exec api pytest tests/test_runtime_answer_matrix.py tests/test_runtime_regression_matrix.py tests/test_query_understanding.py tests/test_planner.py -v
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import pytest

from rag.executor import execute_plan
from rag.planner import build_plan


OWNER = "test-local-user"

_FORBIDDEN_FACTUAL_SQL_INTENTS = frozenset({
    "price_lookup",
    "etf_holdings",
    "fx_rate",
    "macro_series",
})


@dataclass
class AnswerExpectRow:
    query: str
    category: str  # "factual_sql" | "advisory" | "document"
    expected_intents: list[str]
    expected_source_types: list[str]
    expected_mode_hint: str
    expected_template_id: Optional[str]
    expected_params_subset: dict = field(default_factory=dict)
    notes: str = ""


# ── Matrix ────────────────────────────────────────────────────────────────────

ANSWER_MATRIX: list[AnswerExpectRow] = [
    # ── Factual SQL ───────────────────────────────────────────────────────────
    AnswerExpectRow(
        query="כמה המנייה של אפל שווה?",
        category="factual_sql",
        expected_intents=["price_lookup"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="price_lookup_30d",
        expected_params_subset={"ticker": "AAPL"},
        notes="Backfilled core symbol; VECTOR must not appear",
    ),
    AnswerExpectRow(
        query="what is Tesla stock price?",
        category="factual_sql",
        expected_intents=["price_lookup"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="price_lookup_30d",
        expected_params_subset={"ticker": "TSLA"},
        notes="Backfilled core symbol; VECTOR must not appear",
    ),
    AnswerExpectRow(
        query="מה יש בתוך SPY?",
        category="factual_sql",
        expected_intents=["etf_holdings"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="etf_holdings_top20",
        expected_params_subset={"symbol": "SPY"},
        notes="ETF holdings should be SQL-only",
    ),
    AnswerExpectRow(
        query="מהם המרכיבים של קרן SPY?",
        category="factual_sql",
        expected_intents=["etf_holdings"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="etf_holdings_top20",
        expected_params_subset={"symbol": "SPY"},
        notes="Hebrew ETF composition variant",
    ),
    AnswerExpectRow(
        query="מה שער היורו מול השקל?",
        category="factual_sql",
        expected_intents=["fx_rate"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="fx_rate_latest",
        expected_params_subset={"base": "EUR", "quote": "ILS"},
        notes="EUR/ILS FX direction must remain stable",
    ),
    AnswerExpectRow(
        query="של איזה מניות כן יש לך?",
        category="factual_sql",
        expected_intents=["data_availability_lookup"],
        expected_source_types=["SQL"],
        expected_mode_hint="factual",
        expected_template_id="data_availability_prices_summary",
        expected_params_subset={},
        notes="Availability lookup should not require ticker",
    ),
    # ── Advisory ──────────────────────────────────────────────────────────────
    AnswerExpectRow(
        query="what do you think about NVDA?",
        category="advisory",
        expected_intents=[],
        expected_source_types=[],
        expected_mode_hint="advisory",
        expected_template_id=None,
        expected_params_subset={},
        notes="Advisory entity question must not be forced into price_lookup",
    ),
    AnswerExpectRow(
        query="יש מניות ספציפיות שאתה ממליץ עליהם?",
        category="advisory",
        expected_intents=[],
        expected_source_types=[],
        expected_mode_hint="advisory",
        expected_template_id=None,
        expected_params_subset={},
        notes="Recommendation-style question should stay advisory",
    ),
    AnswerExpectRow(
        query="Should I buy NVDA?",
        category="advisory",
        expected_intents=[],
        expected_source_types=[],
        expected_mode_hint="advisory",
        expected_template_id=None,
        expected_params_subset={},
        notes="Buy-intent question should not become factual price lookup",
    ),
    # ── Document ──────────────────────────────────────────────────────────────
    AnswerExpectRow(
        query="תסכם לי את הדוח שהעליתי",
        category="document",
        expected_intents=["document_lookup"],
        expected_source_types=["VECTOR"],
        expected_mode_hint="advisory",
        expected_template_id=None,
        expected_params_subset={},
        notes="Uploaded document summary route",
    ),
    AnswerExpectRow(
        query="יש לך גישה לדוח ריבעוני שהעליתי?",
        category="document",
        expected_intents=["document_lookup"],
        expected_source_types=["VECTOR"],
        expected_mode_hint="advisory",
        expected_template_id=None,
        expected_params_subset={},
        notes="Document access question route",
    ),
]

# ── Parametrize subsets ───────────────────────────────────────────────────────

_FACTUAL_ROWS = [r for r in ANSWER_MATRIX if r.category == "factual_sql"]
_ADVISORY_ROWS = [r for r in ANSWER_MATRIX if r.category == "advisory"]
_DOCUMENT_ROWS = [r for r in ANSWER_MATRIX if r.category == "document"]

# Executor empty-path: one row per intent type as specified in the plan
_EXECUTOR_EMPTY_ROWS = [
    r for r in ANSWER_MATRIX
    if r.query in {
        "כמה המנייה של אפל שווה?",       # price_lookup
        "מה יש בתוך SPY?",                 # etf_holdings
        "מה שער היורו מול השקל?",          # fx_rate
        "של איזה מניות כן יש לך?",         # data_availability_lookup
    }
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _intents(plan) -> list[str]:
    return [s.intent_type for s in plan.steps]


def _source_types(plan) -> list[str]:
    return [s.source_type for s in plan.steps]


def _step_for(plan, intent_type: str):
    for s in plan.steps:
        if s.intent_type == intent_type:
            return s
    return None


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("row", ANSWER_MATRIX, ids=[r.query for r in ANSWER_MATRIX])
def test_answer_matrix_routing(row: AnswerExpectRow):
    """Planner contract: intent, source_type, mode_hint, template_id, params."""
    plan = build_plan(row.query, OWNER)
    intents = _intents(plan)

    for expected in row.expected_intents:
        assert expected in intents, (
            f"[{row.category}] expected intent '{expected}' not found in {intents} "
            f"for query: {row.query!r}"
        )

    assert plan.plan_meta.mode_hint == row.expected_mode_hint, (
        f"mode_hint mismatch: got {plan.plan_meta.mode_hint!r} "
        f"expected {row.expected_mode_hint!r} for {row.query!r}"
    )

    if not row.expected_intents:
        return

    primary_intent = row.expected_intents[0]
    step = _step_for(plan, primary_intent)
    assert step is not None, (
        f"no step found for intent '{primary_intent}' in plan for {row.query!r}"
    )

    if row.expected_source_types:
        assert step.source_type == row.expected_source_types[0], (
            f"source_type mismatch on '{primary_intent}': "
            f"got {step.source_type!r} expected {row.expected_source_types[0]!r} "
            f"for {row.query!r}"
        )

    if row.expected_template_id:
        assert step.sql_template_id == row.expected_template_id, (
            f"sql_template_id mismatch on '{primary_intent}': "
            f"got {step.sql_template_id!r} expected {row.expected_template_id!r} "
            f"for {row.query!r}"
        )

    params = dict(step.parameters or {})
    for k, v in row.expected_params_subset.items():
        assert params.get(k) == v, (
            f"params mismatch on '{primary_intent}': "
            f"expected {k}={v!r}, got {params} for {row.query!r}"
        )


@pytest.mark.parametrize("row", _FACTUAL_ROWS, ids=[r.query for r in _FACTUAL_ROWS])
def test_answer_matrix_no_vector_fallback_for_factual(row: AnswerExpectRow):
    """Factual SQL queries must produce no VECTOR steps and at least one SQL step."""
    plan = build_plan(row.query, OWNER)
    source_types = _source_types(plan)

    assert "VECTOR" not in source_types, (
        f"factual SQL query produced a VECTOR step; "
        f"got source_types={source_types} for {row.query!r}"
    )

    non_no_match = [s for s in source_types if s != "NO_MATCH"]
    assert non_no_match, (
        f"expected at least one non-NO_MATCH step for {row.query!r}"
    )
    assert all(s == "SQL" for s in non_no_match), (
        f"all active steps should be SQL; got {non_no_match} for {row.query!r}"
    )


@pytest.mark.parametrize("row", _ADVISORY_ROWS, ids=[r.query for r in _ADVISORY_ROWS])
def test_answer_matrix_advisory_no_factual_sql_forced(row: AnswerExpectRow):
    """Advisory queries must not produce factual SQL intents."""
    plan = build_plan(row.query, OWNER)
    intents = set(_intents(plan))

    forced = intents & _FORBIDDEN_FACTUAL_SQL_INTENTS
    assert not forced, (
        f"advisory query {row.query!r} should not force factual SQL intents; "
        f"found: {forced}"
    )

    assert plan.plan_meta.mode_hint == "advisory", (
        f"mode_hint should be 'advisory', got {plan.plan_meta.mode_hint!r} "
        f"for {row.query!r}"
    )


@pytest.mark.parametrize("row", _DOCUMENT_ROWS, ids=[r.query for r in _DOCUMENT_ROWS])
def test_answer_matrix_document_routes_to_vector(row: AnswerExpectRow):
    """Document queries must produce a document_lookup intent and a VECTOR step."""
    plan = build_plan(row.query, OWNER)
    intents = _intents(plan)
    source_types = _source_types(plan)

    assert "document_lookup" in intents, (
        f"expected document_lookup intent for {row.query!r}; got {intents}"
    )
    assert "VECTOR" in source_types, (
        f"expected at least one VECTOR step for {row.query!r}; got {source_types}"
    )
    assert plan.plan_meta.mode_hint == "advisory", (
        f"document queries should have mode_hint='advisory'; "
        f"got {plan.plan_meta.mode_hint!r} for {row.query!r}"
    )


@pytest.mark.parametrize(
    "row", _EXECUTOR_EMPTY_ROWS, ids=[r.query for r in _EXECUTOR_EMPTY_ROWS]
)
def test_answer_matrix_executor_empty_path(row: AnswerExpectRow):
    """
    Passes an always-empty sql_runner to execute_plan and verifies the
    executor's empty-path contract per intent type.

    price_lookup:
        Emits a structured sentinel row (established in Phase 4C):
        data[0]["rows_found"] == 0 and "no_data" key present.

    etf_holdings / fx_rate / data_availability_lookup:
        result.status == "empty".
        A structured sentinel is not guaranteed for these intents;
        asserting only status avoids coupling to production internals.
        If future phases add structured sentinels here, tighten these assertions.
    """
    async def _empty_sql_runner(*args, **kwargs):
        return []

    plan = build_plan(row.query, OWNER)
    results = asyncio.run(execute_plan(plan, OWNER, sql_runner=_empty_sql_runner))

    assert results, f"execute_plan returned no results for {row.query!r}"

    primary_intent = row.expected_intents[0]
    target = next(
        (r for r in results if r.intent_type == primary_intent), None
    )
    assert target is not None, (
        f"no StepResult for intent '{primary_intent}' in results for {row.query!r}; "
        f"result intents: {[r.intent_type for r in results]}"
    )

    if primary_intent == "price_lookup":
        assert target.data, (
            f"price_lookup empty path should emit a sentinel no_data row, "
            f"got empty data list for {row.query!r}"
        )
        note = target.data[0]
        assert note.get("rows_found") == 0, (
            f"expected rows_found=0 in sentinel row, got {note} for {row.query!r}"
        )
        assert "no_data" in note, (
            f"expected 'no_data' key in sentinel row, got keys={list(note)} "
            f"for {row.query!r}"
        )
    else:
        assert target.status == "empty", (
            f"expected result.status='empty' for '{primary_intent}' with empty runner; "
            f"got status={target.status!r} for {row.query!r}"
        )


def test_answer_matrix_snapshot(capsys):
    """Non-failing diagnostic — prints a readable matrix snapshot. Always passes."""
    lines = ["", "Runtime Answer Matrix snapshot:", ""]
    for row in ANSWER_MATRIX:
        plan = build_plan(row.query, OWNER)
        intents = _intents(plan)
        source_types = _source_types(plan)
        params = [dict(s.parameters or {}) for s in plan.steps]
        lines.append(
            f"[{row.category}] {row.query!r}\n"
            f"    intents      = {intents}\n"
            f"    source_types = {source_types}\n"
            f"    params       = {params}\n"
            f"    mode_hint    = {plan.plan_meta.mode_hint}\n"
            f"    notes        : {row.notes}"
        )
    print("\n".join(lines))
    assert True
