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


async def get_db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Provide the asyncpg connection pool."""
    pool = await db.get_pool()
    yield pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Provide the global Redis client."""
    yield connections.redis_client


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
