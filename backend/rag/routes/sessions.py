from fastapi import APIRouter, Depends, HTTPException
from typing import List
from uuid import uuid4, UUID
from rag.schemas import ChatSession, ChatMessagesResponse
from core import db
import asyncpg
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/chat/sessions", tags=["chat"])

@router.post("/", response_model=ChatSession)
async def create_session(user_id: str, pool: asyncpg.Pool = Depends(db.get_pool)):
    """Start a new chat session."""
    session_id = str(uuid4())
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO chat_sessions (id, user_id, title) VALUES ($1, $2, $3) "
                "RETURNING id, user_id, title, created_at, updated_at",
                UUID(session_id), user_id, "New Conversation"
            )
            data = dict(row)
            data["id"] = str(data["id"])
            return ChatSession(**data)
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(500, "Database error")

@router.get("/{user_id}", response_model=List[ChatSession])
async def list_sessions(user_id: str, pool: asyncpg.Pool = Depends(db.get_pool)):
    """List all chat sessions for a user."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, user_id, title, created_at, updated_at FROM chat_sessions "
                "WHERE user_id = $1 ORDER BY updated_at DESC",
                user_id
            )
            sessions = []
            for r in rows:
                d = dict(r)
                d["id"] = str(d["id"])
                sessions.append(ChatSession(**d))
            return sessions
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(500, "Database error")

@router.get("/{session_id}/messages", response_model=ChatMessagesResponse)
async def get_session_messages(session_id: str, pool: asyncpg.Pool = Depends(db.get_pool)):
    """Fetch all messages for a specific session."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content, citations, latency, created_at FROM chat_messages "
                "WHERE session_id = $1 ORDER BY created_at ASC",
                UUID(session_id)
            )
            # Convert citations/latency from JSONB to dict explicitly if needed
            return ChatMessagesResponse(messages=[dict(r) for r in rows])
    except Exception as e:
        logger.error(f"Failed to fetch messages: {e}")
        raise HTTPException(500, "Database error")

@router.delete("/{session_id}")
async def delete_session(session_id: str, pool: asyncpg.Pool = Depends(db.get_pool)):
    """Delete a chat session."""
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM chat_sessions WHERE id = $1", UUID(session_id))
            return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        raise HTTPException(500, "Database error")
