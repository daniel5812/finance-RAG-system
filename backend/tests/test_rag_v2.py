from __future__ import annotations

import importlib
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_v2.normalizer import normalize_question
from rag_v2.planner import build_plan
from rag_v2.schemas import AssembledContextV2, ChatResponseV2, DebugTraceV2, RetrievalResultV2
from rag_v2.service import run_llm_v2_answer, run_llm_v2_debug


def test_normalize_question_simple():
    normalized = normalize_question(" What are the top holdings of SPY? ")
    assert normalized.canonical_question == "what are the top holdings of spy"
    assert "spy" in normalized.tokens


def test_build_plan_etf_holdings():
    normalized = normalize_question("What are the top holdings of SPY?")
    plan = build_plan(normalized)

    assert plan.intent == "etf_holdings"
    assert plan.supported is True
    assert plan.source == "sql"
    assert plan.params["symbol"] == "SPY"
    assert "FROM etf_holdings" in (plan.sql or "")


def test_build_plan_price_lookup():
    normalized = normalize_question("What is the latest price of AAPL?")
    plan = build_plan(normalized)

    assert plan.intent == "price_lookup"
    assert plan.supported is True
    assert plan.source == "sql"
    assert plan.params["symbol"] == "AAPL"
    assert "FROM prices" in (plan.sql or "")


def test_build_plan_fx_rate():
    normalized = normalize_question("What is the USD/ILS exchange rate?")
    plan = build_plan(normalized)

    assert plan.intent == "fx_rate"
    assert plan.supported is True
    assert plan.source == "sql"
    assert plan.params == {"base_currency": "USD", "quote_currency": "ILS"}
    assert "FROM fx_rates" in (plan.sql or "")


def test_build_plan_macro_series():
    normalized = normalize_question("What is the latest inflation reading?")
    plan = build_plan(normalized)

    assert plan.intent == "macro_series"
    assert plan.supported is True
    assert plan.source == "sql"
    assert plan.params["series_id"] == "CPIAUCNS"
    assert "FROM macro_series" in (plan.sql or "")


def test_build_plan_hebrew_fx_rate():
    normalized = normalize_question("מה שער הדולר מול השקל")
    plan = build_plan(normalized)

    assert plan.intent == "fx_rate"
    assert plan.supported is True
    assert plan.params == {"base_currency": "USD", "quote_currency": "ILS"}


def test_build_plan_hebrew_macro_series():
    normalized = normalize_question("מה האינפלציה האחרונה")
    plan = build_plan(normalized)

    assert plan.intent == "macro_series"
    assert plan.supported is True
    assert plan.params["series_id"] == "CPIAUCNS"


def test_ambiguous_query_returns_unsupported():
    normalized = normalize_question("Tell me about the market")
    plan = build_plan(normalized)

    assert plan.intent == "unsupported"
    assert plan.supported is False
    assert plan.source == "none"
    assert plan.sql is None


def test_unclear_query_does_not_auto_fallback_to_any_supported_intent():
    normalized = normalize_question("Compare USD and ILS inflation")
    plan = build_plan(normalized)

    assert plan.intent == "unsupported"
    assert plan.supported is False
    assert plan.reason is not None


@pytest.mark.asyncio
async def test_run_llm_v2_debug_full_trace(monkeypatch):
    async def fake_execute_retrieval(plan, pool):
        return RetrievalResultV2(
            executed=True,
            success=True,
            executed_query=plan.sql,
            row_count=2,
            rows=[
                {"etf_symbol": "SPY", "holding_symbol": "AAPL", "weight": 7.1, "date": "2026-04-13"},
                {"etf_symbol": "SPY", "holding_symbol": "MSFT", "weight": 6.5, "date": "2026-04-13"},
            ],
        )

    monkeypatch.setattr("rag_v2.service.execute_retrieval", fake_execute_retrieval)

    trace = await run_llm_v2_debug("What are the top holdings of SPY?", pool=object())

    assert trace.original_question == "What are the top holdings of SPY?"
    assert trace.canonical_question == "what are the top holdings of spy"
    assert trace.plan.intent == "etf_holdings"
    assert trace.intent == "etf_holdings"
    assert trace.source == "sql"
    assert trace.params == {"symbol": "SPY"}
    assert trace.retrieval.executed is True
    assert trace.executed_query is not None
    assert trace.retrieval.row_count == 2
    assert trace.row_count == 2
    assert trace.success is True
    assert "holding_symbol: AAPL" in trace.assembled_context
    assert trace.context.row_count == 2


@pytest.mark.asyncio
async def test_debug_trace_unsupported_query_skips_retrieval(monkeypatch):
    async def fail_if_called(plan, pool):
        raise AssertionError("retrieval should not run for unsupported queries")

    monkeypatch.setattr("rag_v2.service.execute_retrieval", fail_if_called)

    trace = await run_llm_v2_debug("Tell me something useful", pool=object())

    assert trace.intent == "unsupported"
    assert trace.success is False
    assert trace.executed_query is None


@pytest.mark.asyncio
async def test_debug_trace_structure_for_unsupported_query(monkeypatch):
    async def fake_execute_retrieval(plan, pool):
        return RetrievalResultV2(
            executed=False,
            success=False,
            executed_query=None,
            row_count=0,
            rows=[],
            error=plan.reason,
        )

    monkeypatch.setattr("rag_v2.service.execute_retrieval", fake_execute_retrieval)

    trace = await run_llm_v2_debug("Tell me something useful", pool=object())

    assert trace.original_question == "Tell me something useful"
    assert trace.canonical_question == "tell me something useful"
    assert trace.intent == "unsupported"
    assert trace.source == "none"
    assert trace.params == {}
    assert trace.executed_query is None
    assert trace.row_count == 0
    assert trace.success is False
    assert trace.assembled_context == "No rows returned."


@pytest.mark.asyncio
async def test_answer_unsupported_returns_early_without_llm(monkeypatch):
    async def fail_llm(messages):
        raise AssertionError("llm should not run for unsupported queries")

    monkeypatch.setattr("rag_v2.service._generate_answer", fail_llm)

    response = await run_llm_v2_answer("Tell me something useful", pool=object())

    assert response.source_type == "unsupported"
    assert response.answer == "This question is unsupported by rag_v2."
    assert response.citations == []
    assert response.debug_trace is not None
    assert response.debug_trace.intent == "unsupported"


@pytest.mark.asyncio
async def test_answer_no_data_returns_early_without_llm(monkeypatch):
    async def fake_pipeline(question, pool):
        return DebugTraceV2(
            original_question=question,
            canonical_question="what is the latest price of aapl",
            intent="price_lookup",
            source="sql",
            params={"symbol": "AAPL"},
            executed_query="SELECT symbol, close, date FROM prices WHERE symbol='AAPL' ORDER BY date DESC LIMIT 5",
            row_count=0,
            success=False,
            assembled_context="No rows returned.",
            normalized_question=normalize_question(question),
            plan=build_plan(normalize_question(question)),
            retrieval=RetrievalResultV2(
                executed=True,
                success=False,
                executed_query="SELECT symbol, close, date FROM prices WHERE symbol='AAPL' ORDER BY date DESC LIMIT 5",
                row_count=0,
                rows=[],
                error=None,
            ),
            context=AssembledContextV2(
                text="No rows returned.",
                row_count=0,
                truncated=False,
            ),
        )

    async def fail_llm(messages):
        raise AssertionError("llm should not run when retrieval has no rows")

    monkeypatch.setattr("rag_v2.service._run_pipeline", fake_pipeline)
    monkeypatch.setattr("rag_v2.service._generate_answer", fail_llm)

    response = await run_llm_v2_answer("What is the latest price of AAPL?", pool=object())

    assert response.source_type == "sql"
    assert response.answer == "No SQL data was found for this question."
    assert response.citations == []
    assert response.debug_trace is not None
    assert response.debug_trace.row_count == 0


@pytest.mark.asyncio
async def test_answer_supported_query_uses_mocked_llm(monkeypatch):
    async def fake_llm(messages):
        assert messages[0]["role"] == "system"
        assert "answer only from the provided sql context" in messages[0]["content"].lower()
        assert "SQL Context [S1]:" in messages[1]["content"]
        return "The top holding is AAPL at 7.1% [S1]"

    async def fake_execute_retrieval(plan, pool):
        return RetrievalResultV2(
            executed=True,
            success=True,
            executed_query=plan.sql,
            row_count=2,
            rows=[
                {"etf_symbol": "SPY", "holding_symbol": "AAPL", "weight": 7.1, "date": "2026-04-13"},
                {"etf_symbol": "SPY", "holding_symbol": "MSFT", "weight": 6.5, "date": "2026-04-13"},
            ],
        )

    monkeypatch.setattr("rag_v2.service.execute_retrieval", fake_execute_retrieval)
    monkeypatch.setattr("rag_v2.service._generate_answer", fake_llm)

    response = await run_llm_v2_answer("What are the top holdings of SPY?", pool=object())

    assert response.source_type == "sql"
    assert response.answer == "The top holding is AAPL at 7.1% [S1]"
    assert response.citations == ["[S1]"]
    assert response.debug_trace is not None
    assert response.debug_trace.intent == "etf_holdings"


@pytest.mark.asyncio
async def test_debug_path_remains_unchanged_with_answer_mode_added(monkeypatch):
    async def fake_execute_retrieval(plan, pool):
        return RetrievalResultV2(
            executed=True,
            success=True,
            executed_query=plan.sql,
            row_count=1,
            rows=[
                {"etf_symbol": "SPY", "holding_symbol": "AAPL", "weight": 7.1, "date": "2026-04-13"},
            ],
        )

    monkeypatch.setattr("rag_v2.service.execute_retrieval", fake_execute_retrieval)

    trace = await run_llm_v2_debug("What are the top holdings of SPY?", pool=object())

    assert trace.intent == "etf_holdings"
    assert trace.source == "sql"
    assert trace.row_count == 1
    assert trace.assembled_context.startswith("- etf_symbol: SPY")


def test_chat_v2_debug_route_hits_rag_v2_not_legacy(monkeypatch):
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = object
    sentence_transformers.CrossEncoder = object
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)

    dependencies_stub = types.ModuleType("core.dependencies")

    async def get_current_user():
        return "test-user"

    async def get_db_pool():
        yield object()

    dependencies_stub.get_current_user = get_current_user
    dependencies_stub.get_db_pool = get_db_pool
    monkeypatch.setitem(sys.modules, "core.dependencies", dependencies_stub)

    routes = importlib.import_module("rag_v2.routes")

    app = FastAPI()
    app.include_router(routes.router)

    async def fake_debug(question, pool):
        return DebugTraceV2(
            original_question=question,
            canonical_question="what are the top holdings of spy",
            intent="etf_holdings",
            source="sql",
            params={"symbol": "SPY"},
            executed_query="SELECT ...",
            row_count=1,
            success=True,
            assembled_context="- etf_symbol: SPY, holding_symbol: AAPL, weight: 7.1",
            normalized_question=normalize_question(question),
            plan=build_plan(normalize_question(question)),
            retrieval=RetrievalResultV2(
                executed=True,
                success=True,
                executed_query="SELECT ...",
                row_count=1,
                rows=[{"etf_symbol": "SPY", "holding_symbol": "AAPL", "weight": 7.1}],
                error=None,
            ),
            context=AssembledContextV2(
                text="- etf_symbol: SPY, holding_symbol: AAPL, weight: 7.1",
                row_count=1,
                truncated=False,
            ),
        )

    async def fail_legacy(*args, **kwargs):
        raise AssertionError("legacy chat_service should not be called")

    monkeypatch.setattr(routes, "run_llm_v2_debug", fake_debug)

    client = TestClient(app)
    response = client.post("/chat-v2/debug", json={"question": "What are the top holdings of SPY?"})

    assert response.status_code == 200
    assert response.json()["intent"] == "etf_holdings"


def test_chat_v2_answer_route_hits_rag_v2_not_legacy(monkeypatch):
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = object
    sentence_transformers.CrossEncoder = object
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)

    dependencies_stub = types.ModuleType("core.dependencies")

    async def get_current_user():
        return "test-user"

    async def get_db_pool():
        yield object()

    dependencies_stub.get_current_user = get_current_user
    dependencies_stub.get_db_pool = get_db_pool
    monkeypatch.setitem(sys.modules, "core.dependencies", dependencies_stub)

    routes = importlib.import_module("rag_v2.routes")

    app = FastAPI()
    app.include_router(routes.router)

    async def fake_answer(question, pool):
        normalized = normalize_question(question)
        plan = build_plan(normalized)
        return ChatResponseV2(
            answer="The top holding is AAPL [S1]",
            source_type="sql",
            citations=["[S1]"],
            debug_trace=DebugTraceV2(
                original_question=question,
                canonical_question="what are the top holdings of spy",
                intent="etf_holdings",
                source="sql",
                params={"symbol": "SPY"},
                executed_query="SELECT ...",
                row_count=1,
                success=True,
                assembled_context="- etf_symbol: SPY, holding_symbol: AAPL, weight: 7.1",
                normalized_question=normalized,
                plan=plan,
                retrieval=RetrievalResultV2(
                    executed=True,
                    success=True,
                    executed_query="SELECT ...",
                    row_count=1,
                    rows=[{"etf_symbol": "SPY", "holding_symbol": "AAPL", "weight": 7.1}],
                    error=None,
                ),
                context=AssembledContextV2(
                    text="- etf_symbol: SPY, holding_symbol: AAPL, weight: 7.1",
                    row_count=1,
                    truncated=False,
                ),
            ),
        )

    monkeypatch.setattr(routes, "run_llm_v2_answer", fake_answer)

    client = TestClient(app)
    response = client.post("/chat-v2", json={"question": "What are the top holdings of SPY?"})

    assert response.status_code == 200
    assert response.json()["source_type"] == "sql"
    assert response.json()["debug_trace"]["intent"] == "etf_holdings"
