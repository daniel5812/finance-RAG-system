"""
Tests for the /chat/debug dry-run service function.
No LLM, no DB, no network — runners and condense_question are patched.

Run: cd backend && pytest tests/test_chat_debug_endpoint.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from rag.schemas import ChatQuery


OWNER = "user_debug_test"
SQL_ROW = {"symbol": "SPY", "close": 500.0, "date": "2024-01-01"}


@pytest.mark.asyncio
async def test_debug_dry_run_sql_only():
    """SQL-only query returns correct shape and fusion summary; no LLM called."""
    from rag.services.chat_service import run_debug_dry_run

    query = ChatQuery(question="What is SPY price?", owner_id=OWNER, history=[])

    mock_pool = MagicMock()
    sql_runner = AsyncMock(return_value=[SQL_ROW])
    vector_runner = AsyncMock(return_value=[])

    with (
        patch("rag.services.chat_service.condense_question", new=AsyncMock(return_value="What is SPY price?")),
        patch("rag.services.chat_service._make_sql_runner", return_value=sql_runner),
        patch("rag.services.chat_service._make_vector_runner", return_value=vector_runner),
    ):
        result = await run_debug_dry_run(mock_pool, None, None, None, query)

    assert result.standalone_question == "What is SPY price?"
    assert result.plan_meta.total_steps >= 1
    assert any(s.source_type == "SQL" for s in result.plan_steps)
    assert result.fusion_summary.has_sql is True
    assert all(r.error_message is None for r in result.step_results)
    assert result.latency_ms.total_ms >= 0
    assert result.latency_ms.plan_ms >= 0
    assert result.latency_ms.execute_ms >= 0


@pytest.mark.asyncio
async def test_debug_dry_run_no_match():
    """Unrecognised question produces no_match plan; is_partial=False, has_sql=False."""
    from rag.services.chat_service import run_debug_dry_run

    query = ChatQuery(question="hello there", owner_id=OWNER, history=[])

    mock_pool = MagicMock()
    vector_runner = AsyncMock(return_value=[])

    with (
        patch("rag.services.chat_service.condense_question", new=AsyncMock(return_value="hello there")),
        patch("rag.services.chat_service._make_sql_runner", return_value=AsyncMock(return_value=[])),
        patch("rag.services.chat_service._make_vector_runner", return_value=vector_runner),
    ):
        result = await run_debug_dry_run(mock_pool, None, None, None, query)

    assert result.standalone_question == "hello there"
    assert result.plan_steps[0].intent_type == "no_match"
    assert result.fusion_summary.has_sql is False
    assert result.fusion_summary.is_partial is False
