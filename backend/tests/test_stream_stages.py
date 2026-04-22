"""
Contract tests for generate_stream_response stage helpers.
No DB, no network, no LLM — all external dependencies are stubbed.
Run: cd backend && pytest tests/test_stream_stages.py -v
"""
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from rag.services.chat_service import (
    _prepare_or_short_circuit_stream,
    _run_retrieval_stage,
    _build_guidance_stage,
    _build_prompt_stage,
    _stream_llm_stage,
    _finalize_result_stage,
    _finalize_observability_stage,
    _fusion_to_context,
    NUMERIC_SHORTCUT_RESPONSE,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _q(question="What is USD/ILS?", owner_id=None, session_id=None, history=None):
    return SimpleNamespace(
        question=question, owner_id=owner_id, session_id=session_id,
        user_role="employee", history=history or [], document_ids=[],
    )


def _fusion(sql_data=None, vector_chunks=None):
    return SimpleNamespace(
        structured_data=sql_data or {},
        supporting_context=vector_chunks or [],
        retrieval_summary=SimpleNamespace(has_sql=False, has_vector=False),
    )


def _pkt_type(sse_line: str) -> str:
    return json.loads(sse_line.split("data: ")[1])["type"]


def _pkt(sse_line: str) -> dict:
    return json.loads(sse_line.split("data: ")[1])


# ── Stage 1: _prepare_or_short_circuit_stream ─────────────────────────────────

@pytest.mark.asyncio
async def test_stage1_numeric_shortcut():
    with (
        patch("rag.services.chat_service.state.incr_metric", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.decr_active_streams", new_callable=AsyncMock),
    ):
        r = await _prepare_or_short_circuit_stream(MagicMock(), _q("1"), None, time.time())

    assert r["short_circuit"] is True
    types = [_pkt_type(p) for p in r["packets"]]
    assert types == ["meta", "token", "done"]
    assert NUMERIC_SHORTCUT_RESPONSE in r["packets"][1]


@pytest.mark.asyncio
async def test_stage1_exact_cache_hit():
    cached_data = {"answer": "cached", "sources": [], "citations": {}}
    entry = {"timestamp": time.time(), "data": cached_data}
    with (
        patch("rag.services.chat_service.state.incr_metric", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.decr_active_streams", new_callable=AsyncMock),
        patch("rag.services.chat_service.redis_get", new_callable=AsyncMock, return_value=entry),
    ):
        r = await _prepare_or_short_circuit_stream(MagicMock(), _q(), MagicMock(), time.time())

    assert r["short_circuit"] is True
    assert _pkt(r["packets"][0])["source_type"] == "cache"


@pytest.mark.asyncio
async def test_stage1_stale_cache_returns_stale_source_type():
    cached_data = {"answer": "old", "sources": [], "citations": {}}
    entry = {"timestamp": time.time() - 9999, "data": cached_data}  # definitely stale
    with (
        patch("rag.services.chat_service.state.incr_metric", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.decr_active_streams", new_callable=AsyncMock),
        patch("rag.services.chat_service.redis_get", new_callable=AsyncMock, return_value=entry),
        patch("rag.services.chat_service.regenerate_response", new_callable=AsyncMock),
    ):
        r = await _prepare_or_short_circuit_stream(MagicMock(), _q(), MagicMock(), time.time())

    assert r["short_circuit"] is True
    assert _pkt(r["packets"][0])["source_type"] == "stale"


@pytest.mark.asyncio
async def test_stage1_no_pinecone_error_packet():
    with (
        patch("rag.services.chat_service.state.incr_metric", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.decr_active_streams", new_callable=AsyncMock),
        patch("rag.services.chat_service.redis_get", new_callable=AsyncMock, return_value=None),
    ):
        r = await _prepare_or_short_circuit_stream(MagicMock(), _q(), None, time.time())

    assert r["short_circuit"] is True
    assert _pkt(r["packets"][0])["type"] == "error"


@pytest.mark.asyncio
async def test_stage1_clean_path_continues():
    with (
        patch("rag.services.chat_service.state.incr_metric", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.decr_active_streams", new_callable=AsyncMock),
        patch("rag.services.chat_service.redis_get", new_callable=AsyncMock, return_value=None),
        patch("rag.services.chat_service.semantic_cache_lookup", new_callable=AsyncMock, return_value=None),
        patch("rag.services.chat_service.load_session_summary", new_callable=AsyncMock, return_value=None),
        patch("rag.services.chat_service.condense_question", new_callable=AsyncMock, return_value="What is USD/ILS?"),
        patch("rag.services.chat_service.cached_embed", new_callable=AsyncMock, return_value=[0.1] * 8),
    ):
        r = await _prepare_or_short_circuit_stream(MagicMock(), _q(), MagicMock(), time.time())

    assert r["short_circuit"] is False
    assert "cache_key" in r and "standalone_question" in r and "query_vector" in r and "loop" in r


# ── _fusion_to_context contracts ──────────────────────────────────────────────

def test_fusion_to_context_empty():
    ctxs, srcs, cits, metrics = _fusion_to_context(_fusion())
    assert ctxs == [] and srcs == [] and isinstance(cits, dict) and isinstance(metrics, dict)


def test_fusion_to_context_sql_tag():
    fr = _fusion(sql_data={"fx_rate": [{"rate": 3.7}]})
    ctxs, srcs, cits, _ = _fusion_to_context(fr)
    assert len(ctxs) == 1 and "[S1]" in ctxs[0]
    assert cits["[S1]"]["source_type"] == "sql"


def test_fusion_to_context_vector_tag():
    chunk = {"metadata": {"text": "hello", "document_id": "d1", "filename": "f.pdf"}, "score": 0.9, "rerank_score": 0.8}
    fr = _fusion(vector_chunks=[chunk])
    ctxs, srcs, cits, _ = _fusion_to_context(fr)
    assert len(ctxs) == 1 and "[D1]" in ctxs[0]
    assert cits["[D1]"]["source_type"] == "document"


def test_fusion_to_context_skips_chunk_without_text():
    fr = _fusion(vector_chunks=[{"no_metadata": True}])
    ctxs, srcs, cits, _ = _fusion_to_context(fr)
    assert ctxs == [] and srcs == []


# ── Stage 5: _stream_llm_stage ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_llm_filters_metadata_blocks():
    tokens = ["Hello ", '[[SuggestedQuestions:["Q1"]', "]]", " world"]

    async def _fake_stream(messages):
        for t in tokens:
            yield t

    result_bag = {}
    with patch("rag.services.chat_service.ChatAgentClient.generate_stream", side_effect=_fake_stream):
        yielded = []
        async for pkt in _stream_llm_stage([{"role": "user", "content": "x"}], time.time() + 30, result_bag):
            yielded.append(_pkt(pkt))

    token_text = "".join(p["content"] for p in yielded if p["type"] == "token")
    assert "[[" not in token_text
    assert "Hello" in token_text
    assert "world" in token_text
    assert "full_answer" in result_bag
    assert "[[SuggestedQuestions:" in result_bag["full_answer"]


@pytest.mark.asyncio
async def test_stream_llm_timeout_yields_error():
    async def _slow_stream(messages):
        yield "token"
        # deadline already past — simulated by passing deadline=0
    result_bag = {}
    with patch("rag.services.chat_service.ChatAgentClient.generate_stream", side_effect=_slow_stream):
        pkts = []
        async for pkt in _stream_llm_stage([{}], deadline=0.0, result_bag=result_bag):
            pkts.append(_pkt(pkt))
    assert any(p["type"] == "error" for p in pkts)


# ── Stage 6: _finalize_result_stage ──────────────────────────────────────────

_BASE_RETRIEVAL = {
    "sources": [], "citations": {},
    "metrics": {"sql": 0, "embed": 0, "routing": 0, "rerank": 0},
    "plan_time": 0.1, "retrieval_time": 0.2,
}
_BASE_GUIDANCE = {"pipeline_confidence": "high", "intent": "factual"}


@pytest.mark.asyncio
async def test_finalize_parses_suggested_questions():
    full = 'Answer text [[SuggestedQuestions:["Q1","Q2"]]]'
    with (
        patch("rag.services.chat_service.redis_set", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.record_value", new_callable=AsyncMock),
        patch("rag.services.chat_service.content_filter", return_value=("Answer text", [])),
    ):
        result, _ = await _finalize_result_stage(
            MagicMock(), _q(), full, _BASE_RETRIEVAL, _BASE_GUIDANCE, 1.0, time.time() - 2, "key")

    assert result["suggested_questions"] == ["Q1", "Q2"]
    assert "[[SuggestedQuestions:" not in result["answer"]


@pytest.mark.asyncio
async def test_finalize_sources_always_list_when_none():
    retrieval = {**_BASE_RETRIEVAL, "sources": None}
    with (
        patch("rag.services.chat_service.redis_set", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.record_value", new_callable=AsyncMock),
        patch("rag.services.chat_service.content_filter", return_value=("answer", [])),
    ):
        result, _ = await _finalize_result_stage(
            MagicMock(), _q(), "answer", retrieval, _BASE_GUIDANCE, 0.5, time.time() - 1, "key")

    assert isinstance(result["sources"], list)
    assert isinstance(result["citations"], dict)


@pytest.mark.asyncio
async def test_finalize_latency_keys_present():
    with (
        patch("rag.services.chat_service.redis_set", new_callable=AsyncMock),
        patch("rag.services.chat_service.state.record_value", new_callable=AsyncMock),
        patch("rag.services.chat_service.content_filter", return_value=("a", [])),
    ):
        result, _ = await _finalize_result_stage(
            MagicMock(), _q(), "a", _BASE_RETRIEVAL, _BASE_GUIDANCE, 1.0, time.time() - 2, "key")

    lb = result["latency_breakdown"]
    for key in ("planning", "sql", "embedding", "routing", "retrieval", "rerank", "generation", "total"):
        assert key in lb, f"Missing latency key: {key}"
