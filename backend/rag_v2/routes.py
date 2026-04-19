from __future__ import annotations

import asyncpg
import json
from fastapi import APIRouter, Depends

from core.logger import get_logger
from core.dependencies import get_current_user, get_db_pool
from rag_v2.schemas import ChatResponseV2, DebugQueryV2, DebugTraceV2
from rag_v2.service import run_llm_v2_answer, run_llm_v2_debug


router = APIRouter(prefix="/chat-v2", tags=["chat-v2"])
logger = get_logger(__name__)


@router.post("", response_model=ChatResponseV2)
async def chat_v2_answer(
    query: DebugQueryV2,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> ChatResponseV2:
    del user_id
    logger.info(json.dumps({
        "event": "rag_v2_request_received",
        "path": "/chat-v2",
        "mode": "answer",
        "question": query.question,
    }, ensure_ascii=False))
    response = await run_llm_v2_answer(query.question, pool)
    logger.info(json.dumps({
        "event": "rag_v2_request_complete",
        "path": "/chat-v2",
        "mode": "answer",
        "intent": response.debug_trace.intent if response.debug_trace else "unknown",
        "source": response.debug_trace.source if response.debug_trace else "unknown",
        "row_count": response.debug_trace.row_count if response.debug_trace else 0,
        "llm_called": response.citations == ["[S1]"],
    }, ensure_ascii=False))
    return response


@router.post("/debug", response_model=DebugTraceV2)
async def chat_v2_debug(
    query: DebugQueryV2,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> DebugTraceV2:
    del user_id
    logger.info(json.dumps({
        "event": "rag_v2_request_received",
        "path": "/chat-v2/debug",
        "mode": "debug",
        "question": query.question,
    }, ensure_ascii=False))
    response = await run_llm_v2_debug(query.question, pool)
    logger.info(json.dumps({
        "event": "rag_v2_request_complete",
        "path": "/chat-v2/debug",
        "mode": "debug",
        "intent": response.intent,
        "source": response.source,
        "row_count": response.row_count,
        "llm_called": False,
    }, ensure_ascii=False))
    return response
