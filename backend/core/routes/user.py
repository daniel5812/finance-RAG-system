from fastapi import APIRouter, Depends, HTTPException, status
from core.dependencies import get_current_user
from typing import Optional
import asyncpg
from core import db
from core.logger import get_logger
from financial.services.user_profile_service import UserProfileService
from financial.crud import upsert_user_profile
from rag.schemas import UserProfileUpdate, UserProfileResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/user", tags=["user"])

@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile_api(user_id: str = Depends(get_current_user), pool: asyncpg.Pool = Depends(db.get_pool)):
    """Fetch complete user profile (risk, interests, persona)."""
    try:
        profile = await UserProfileService.get_profile(pool, user_id)
        return profile
    except Exception as e:
        logger.error(f"Error fetching user profile: {e}")
        raise HTTPException(500, "Database error")

@router.put("/profile", response_model=UserProfileResponse)
async def update_user_profile_api(profile: UserProfileUpdate, user_id: str = Depends(get_current_user), pool: asyncpg.Pool = Depends(db.get_pool)):
    """Update user profile fields. Only supplied (non-null) fields are overwritten."""
    try:
        existing = await UserProfileService.get_profile(pool, user_id)
        update_fields = profile.model_dump(exclude_none=True)
        merged = {**existing, **update_fields}
        await upsert_user_profile(pool, user_id, merged)
        logger.info(f"profile_updated user_id={user_id} fields={list(update_fields.keys())}")
        return await UserProfileService.get_profile(pool, user_id)
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(500, "Database error")


# Legacy compatibility for /settings if needed
@router.post("/settings")
async def update_user_settings_legacy(settings: dict, user_id: str = Depends(get_current_user), pool: asyncpg.Pool = Depends(db.get_pool)):
    # Map custom_persona to profile
    profile = await UserProfileService.get_profile(pool, user_id)
    profile["custom_persona"] = settings.get("custom_persona")
    await upsert_user_profile(pool, user_id, profile)
    return profile
