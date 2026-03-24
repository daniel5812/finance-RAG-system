import json
import asyncpg
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.logger import get_logger
from core.security import detect_prompt_injection
from core.middleware import verify_prompt_injection
import core.state as state
from core.config import MAX_CONCURRENT_STREAMS

from rag.schemas import ChatQuery
from rag.services import chat_service

logger = get_logger(__name__)
# Apply the security check globally to all endpoints in this router
from fastapi import Depends
from core.dependencies import get_db_pool, get_pinecone, get_embed_model, get_rerank_model
from typing import Any
from sentence_transformers import SentenceTransformer

router = APIRouter(dependencies=[Depends(verify_prompt_injection)])


@router.post("/chat")
async def chat_with_data(
    query: ChatQuery,
    pool: asyncpg.Pool = Depends(get_db_pool),
    pinecone_index: Any = Depends(get_pinecone),
    embed_model: SentenceTransformer = Depends(get_embed_model),
    rerank_model: Any = Depends(get_rerank_model)
):
    """Sync endpoint — returns full response JSON."""
    return await chat_service.generate_chat_response(pool, pinecone_index, embed_model, rerank_model, query)


@router.post("/chat/stream")
async def chat_stream(
    query: ChatQuery,
    pool: asyncpg.Pool = Depends(get_db_pool),
    pinecone_index: Any = Depends(get_pinecone),
    embed_model: SentenceTransformer = Depends(get_embed_model),
    rerank_model: Any = Depends(get_rerank_model)
):
    """SSE streaming endpoint — tokens sent as they arrive."""

    # 🛡️ DoS protection: limit concurrent streams
    if await state.get_active_streams() >= MAX_CONCURRENT_STREAMS:
        raise HTTPException(
            status_code=503,
            detail=f"Too many concurrent streams ({await state.get_active_streams()}/{MAX_CONCURRENT_STREAMS})"
        )
    
    await state.incr_active_streams()

    # The streaming service function handles its own decrements and yields
    return StreamingResponse(
        chat_service.generate_stream_response(pool, pinecone_index, embed_model, rerank_model, query), 
        media_type="text/event-stream"
    )
