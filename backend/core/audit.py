import json
import asyncpg
from typing import Optional, Any
from core.logger import get_logger

logger = get_logger(__name__)

async def log_audit_event(
    pool: asyncpg.Pool,
    event_type: str,        # login, chat, admin_action, error, security
    action: str,            # read, write, update, delete, access
    status: str,            # success, failure
    user_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict] = None
):
    """
    Persist a structured audit event to the database.
    Does NOT store sensitive content by default.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_events 
                (event_type, user_id, resource_id, action, status, request_id, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, event_type, user_id, resource_id, action, status, request_id, json.dumps(metadata or {}))
    except Exception as e:
        # We don't want audit failure to crash the main request, but we must log it
        logger.error(f"AUDIT LOGGING FAILED: {e}")
