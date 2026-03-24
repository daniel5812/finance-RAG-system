from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from rag.schemas import UserSettings
from core import db
import asyncpg
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user", tags=["user"])

@router.get("/settings/{user_id}", response_model=UserSettings)
async def get_user_settings(user_id: str, pool: asyncpg.Pool = Depends(db.get_pool)):
    """Fetch user-specific persona instructions."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, custom_persona, updated_at FROM user_settings WHERE user_id = $1",
                user_id
            )
            if not row:
                return UserSettings(user_id=user_id, custom_persona=None)
            return UserSettings(**row)
    except Exception as e:
        logger.error(f"Error fetching user settings: {e}")
        raise HTTPException(500, "Database error")

@router.post("/settings", response_model=UserSettings)
async def update_user_settings(settings: UserSettings, pool: asyncpg.Pool = Depends(db.get_pool)):
    """Update user-specific persona instructions."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO user_settings (user_id, custom_persona, updated_at) "
                "VALUES ($1, $2, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE "
                "SET custom_persona = EXCLUDED.custom_persona, updated_at = NOW() "
                "RETURNING user_id, custom_persona, updated_at",
                settings.user_id, settings.custom_persona
            )
            return UserSettings(**row)
    except Exception as e:
        logger.error(f"Error updating user settings: {e}")
        raise HTTPException(500, "Database error")
