"""
core/db.py — Async PostgreSQL connection pool.
All database access goes through this module.

Uses asyncpg for high-performance async queries.
Connection pool is shared across the entire application.
"""

import asyncpg
from core.config import DATABASE_URL
from core.logger import get_logger

logger = get_logger(__name__)

# ── Module-level pool (initialized on first use) ──
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool. Call this at app startup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,       # keep 2 connections warm
            max_size=10,      # max 10 concurrent DB connections
            command_timeout=10
        )
        logger.info("PostgreSQL connection pool created")
    return _pool


async def close_pool():
    """Close the pool gracefully. Call this at app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


async def fetch(query: str, *args) -> list[dict]:
    """Run a SELECT and return rows as list of dicts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]


async def fetchrow(query: str, *args) -> dict | None:
    """Run a SELECT and return a single row as dict (or None)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def execute(query: str, *args) -> str:
    """Run INSERT/UPDATE/DELETE. Returns status string (e.g. 'INSERT 0 1')."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, args: list) -> None:
    """Run a batch of INSERT/UPDATE/DELETE with multiple arg sets."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(query, args)
