from __future__ import annotations

import asyncio
import asyncpg
import json
from typing import List

from core.logger import get_logger
from rag_v2.assembler import assemble_context
from rag_v2.normalizer import normalize_question
from rag_v2.planner import build_plans
from rag_v2.prompts import build_answer_messages
from rag_v2.retriever import execute_retrieval
from rag_v2.schemas import ChatResponseV2, DebugTraceV2, QueryPlanV2, RetrievalResultV2

logger = get_logger(__name__)


async def _generate_answer(messages: list[dict]) -> str:
    from core.llm_client import ChatAgentClient

    return await ChatAgentClient.generate(messages, temperature=0)


async def _run_pipeline(question: str, pool: asyncpg.Pool) -> DebugTraceV2:
    normalized_question = normalize_question(question)
    plans: List[QueryPlanV2] = build_plans(normalized_question)

    logger.info(json.dumps({
        "event": "rag_v2_plans_built",
        "question": question,
        "plan_count": len(plans),
        "intents": [p.intent for p in plans],
    }, ensure_ascii=False))

    if not plans:
        # No intent matched — produce a structured "data not available" trace
        # without using a legacy fallback or raising an error.
        empty_retrieval = RetrievalResultV2(
            executed=False,
            success=False,
            executed_query=None,
            row_count=0,
            rows=[],
            error="no supported intent matched this question",
        )
        empty_context = assemble_context([])
        # Represent the no-match state using a minimal placeholder plan
        placeholder_plan = QueryPlanV2(
            intent="no_match",
            source="none",
            supported=False,
            reason="no supported intent matched this question",
        )
        return DebugTraceV2(
            original_question=normalized_question.original_question,
            canonical_question=normalized_question.canonical_question,
            intent="no_match",
            source="none",
            params={},
            executed_query=None,
            row_count=0,
            success=False,
            assembled_context=empty_context.text,
            normalized_question=normalized_question,
            plan=placeholder_plan,
            retrieval=empty_retrieval,
            context=empty_context,
        )

    # Execute all matching plans concurrently
    retrievals: List[RetrievalResultV2] = await asyncio.gather(
        *[execute_retrieval(plan, pool) for plan in plans]
    )

    # Merge rows from all successful retrievals + track failed plans
    merged_rows = []
    failed_intents = []
    for plan, retrieval in zip(plans, retrievals):
        if retrieval.success:
            merged_rows.extend(retrieval.rows)
        else:
            failed_intents.append(plan.intent)

    context = assemble_context(merged_rows, failed_intents if failed_intents else None)

    # Primary plan and retrieval are the first for backward-compat trace fields
    primary_plan = plans[0]
    primary_retrieval = retrievals[0]
    any_success = any(r.success for r in retrievals)
    total_rows = sum(r.row_count for r in retrievals)

    logger.info(json.dumps({
        "event": "rag_v2_retrieval_complete",
        "plan_count": len(plans),
        "any_success": any_success,
        "total_rows": total_rows,
    }, ensure_ascii=False))

    return DebugTraceV2(
        original_question=normalized_question.original_question,
        canonical_question=normalized_question.canonical_question,
        intent=primary_plan.intent,
        source=primary_plan.source,
        params=primary_plan.params,
        executed_query=primary_retrieval.executed_query,
        row_count=total_rows,
        success=any_success,
        assembled_context=context.text,
        normalized_question=normalized_question,
        plan=primary_plan,
        retrieval=primary_retrieval,
        context=context,
    )


async def run_llm_v2_debug(question: str, pool: asyncpg.Pool) -> DebugTraceV2:
    trace = await _run_pipeline(question, pool)
    logger.info(json.dumps({
        "event": "rag_v2_service_complete",
        "mode": "debug",
        "intent": trace.intent,
        "source": trace.source,
        "row_count": trace.row_count,
        "llm_called": False,
    }, ensure_ascii=False))
    return trace


async def run_llm_v2_answer(question: str, pool: asyncpg.Pool) -> ChatResponseV2:
    trace = await _run_pipeline(question, pool)
    llm_called = False

    # When no rows came back (either no plan matched or SQL returned nothing),
    # return a clear "data not available" answer. Never return "unsupported by rag_v2".
    if not trace.success or trace.row_count == 0:
        answer = (
            "No data is currently available for this question. "
            "The requested data may not be in the database."
        )
        response = ChatResponseV2(
            answer=answer,
            source_type="none",
            citations=[],
            debug_trace=trace,
        )
        logger.info(json.dumps({
            "event": "rag_v2_service_complete",
            "mode": "answer",
            "intent": trace.intent,
            "source": trace.source,
            "row_count": trace.row_count,
            "llm_called": llm_called,
        }, ensure_ascii=False))
        return response

    if not trace.assembled_context or trace.assembled_context == "No rows returned.":
        response = ChatResponseV2(
            answer="No data is currently available for this question.",
            source_type="none",
            citations=[],
            debug_trace=trace,
        )
        logger.info(json.dumps({
            "event": "rag_v2_service_complete",
            "mode": "answer",
            "intent": trace.intent,
            "source": trace.source,
            "row_count": trace.row_count,
            "llm_called": llm_called,
        }, ensure_ascii=False))
        return response

    messages = build_answer_messages(trace.original_question, trace.assembled_context)
    answer = await _generate_answer(messages)
    llm_called = True

    response = ChatResponseV2(
        answer=answer,
        source_type="sql",
        citations=["[S1]"],
        debug_trace=trace,
    )
    logger.info(json.dumps({
        "event": "rag_v2_service_complete",
        "mode": "answer",
        "intent": trace.intent,
        "source": trace.source,
        "row_count": trace.row_count,
        "llm_called": llm_called,
    }, ensure_ascii=False))
    return response
