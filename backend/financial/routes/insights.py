from fastapi import APIRouter, Depends, HTTPException, status
from core.dependencies import get_current_user
import asyncpg
from core import db
from financial.crud import get_recent_insights
from financial.services.proactive_insights_service import ProactiveInsightEngine
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/insights", tags=["insights"])

@router.get("/")
async def get_insights(user_id: str = Depends(get_current_user), pool: asyncpg.Pool = Depends(db.get_pool)):
    """Fetch latest proactive insights for a user."""
    try:
        insights = await get_recent_insights(pool, user_id)
        return {"user_id": user_id, "insights": insights}
    except Exception as e:
        logger.error(f"Error fetching insights: {e}")
        raise HTTPException(500, "Database error")

@router.post("/trigger")
async def trigger_insights(user_id: str = Depends(get_current_user), pool: asyncpg.Pool = Depends(db.get_pool)):
    """Manually trigger proactive insight generation (for testing/immediate feedback)."""
    try:
        await ProactiveInsightEngine.generate_insights(pool, user_id)
        insights = await get_recent_insights(pool, user_id, limit=1)
        return {"status": "success", "latest_insight": insights[0] if insights else None}
    except Exception as e:
        logger.error(f"Error triggering insights: {e}")
        raise HTTPException(500, "Insight generation failed")
