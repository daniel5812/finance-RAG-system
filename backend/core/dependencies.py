"""
core/dependencies.py — FastAPI Dependencies for injecting external clients and DB pools.

This module centralizes how services and routes acquire resources like database connections,
caches, and machine learning models, making them easily mockable during testing.
"""

from typing import AsyncGenerator, Any
import redis.asyncio as aioredis
import asyncpg
from sentence_transformers import SentenceTransformer, CrossEncoder

import core.db as db
from openai import AsyncOpenAI
from core import connections


from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from core.auth import decode_access_token
from core.rate_limit import RateLimiter
from core.config import RATE_LIMIT_PER_MINUTE

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Provide the asyncpg connection pool."""
    pool = await db.get_pool()
    yield pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Provide the global Redis client."""
    yield connections.redis_client


async def get_current_user_claims(
    token: str = Depends(oauth2_scheme),
    redis: aioredis.Redis = Depends(get_redis)
) -> dict:
    """
    Validate JWT, return all claims (sub, scopes, etc.), and enforce rate limits.
    """
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    
    # Enforce Rate Limiting (Resource Protection)
    # Using the existing sliding-window RateLimiter for better precision
    is_allowed = await RateLimiter.check_rate_limit(redis, user_id, limit=RATE_LIMIT_PER_MINUTE, window=60)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down."
        )
        
    return payload

async def get_current_user(claims: dict = Depends(get_current_user_claims)) -> str:
    """Convenience dependency to just get the user_id (sub)."""
    return claims.get("sub")

def require_scope(required_scope: str):
    """Dependency factory to enforce a specific scope."""
    async def scope_checker(claims: dict = Depends(get_current_user_claims)):
        user_scopes = claims.get("scopes", [])
        if required_scope not in user_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {required_scope}"
            )
        return True
    return scope_checker



def get_pinecone() -> Any:
    """Provide the global Pinecone index."""
    return connections.pinecone_index


def get_embed_model() -> SentenceTransformer | None:
    """Provide the exact-match embedding model."""
    return connections.embed_model


def get_rerank_model() -> CrossEncoder | None:
    """Provide the CrossEncoder reranking model."""
    return connections.rerank_model


def get_openai_client() -> AsyncOpenAI | None:
    """Provide the global OpenAI client."""
    return connections.openai_client
