"""
core/dependencies.py — FastAPI Dependencies for injecting external clients and DB pools.

This module centralizes how services and routes acquire resources like database connections,
caches, and machine learning models, making them easily mockable during testing.
"""

from typing import AsyncGenerator
import redis.asyncio as aioredis
import asyncpg
from sentence_transformers import SentenceTransformer, CrossEncoder
from pinecone import Index

import core.db as db
from core.connections import redis_client, pinecone_index, embed_model, rerank_model


async def get_db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Provide the asyncpg connection pool."""
    pool = await db.get_pool()
    yield pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Provide the global Redis client."""
    yield redis_client


def get_pinecone() -> Index | None:
    """Provide the global Pinecone index."""
    return pinecone_index


def get_embed_model() -> SentenceTransformer | None:
    """Provide the exact-match embedding model."""
    return embed_model


def get_rerank_model() -> CrossEncoder | None:
    """Provide the CrossEncoder reranking model."""
    return rerank_model
