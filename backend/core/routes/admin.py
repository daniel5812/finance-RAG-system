import asyncpg
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core import db
from core.dependencies import get_db_pool, require_scope, get_current_user
from core.audit import log_audit_event
from core.state import get_state_metrics, SERVER_START_TIME
import time

router = APIRouter(prefix="/admin", tags=["admin"])

# 🛡️ All routes in this router require admin:read at minimum
ADMIN_READ_DEPENDENCY = Depends(require_scope("admin:read"))

@router.get("/audit-events", dependencies=[ADMIN_READ_DEPENDENCY])
async def get_audit_events(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Fetch paginated audit events for the dashboard."""
    query = "SELECT * FROM audit_events"
    filters = []
    params = []
    
    if event_type:
        filters.append(f"event_type = ${len(params) + 1}")
        params.append(event_type)
    if user_id:
        filters.append(f"user_id = ${len(params) + 1}")
        params.append(user_id)
        
    if filters:
        query += " WHERE " + " AND ".join(filters)
        
    query += f" ORDER BY timestamp DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    params.extend([limit, offset])
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

@router.get("/users", dependencies=[Depends(require_scope("admin:users"))])
async def list_admin_users(
    limit: int = Query(50),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """List users for management."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, email, full_name, role, scopes, created_at 
            FROM users 
            ORDER BY created_at DESC LIMIT $1
        """, limit)
        return [dict(r) for r in rows]

@router.patch("/users/{target_user_id}/role", dependencies=[Depends(require_scope("admin:users"))])
async def update_user_role(
    target_user_id: str,
    role: str,
    scopes: List[str],
    current_admin_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Update a user's role and scopes (logged)."""
    async with pool.acquire() as conn:
        # Check if user exists
        exists = await conn.fetchval("SELECT id FROM users WHERE id = $1", target_user_id)
        if not exists:
            raise HTTPException(404, "User not found")
            
        await conn.execute("""
            UPDATE users SET role = $1, scopes = $2 WHERE id = $3
        """, role, scopes, target_user_id)
        
        # Log the admin action
        await log_audit_event(
            pool=pool,
            event_type="admin_action",
            user_id=current_admin_id,
            resource_id=target_user_id,
            action="update",
            status="success",
            metadata={"updated_role": role, "updated_scopes": scopes}
        )
        
        return {"status": "success"}

@router.get("/metrics/summary", dependencies=[Depends(require_scope("admin:metrics"))])
async def get_admin_metrics_summary():
    """Aggregated system performance metrics for admins."""
    metrics = await get_state_metrics()
    
    # Calculate more advanced stats for admin
    lats = metrics["latencies"]
    sorted_lats = sorted(lats) if lats else [0]
    
    return {
        "throughput": {
            "total_queries": metrics["total_queries"],
            "cache_hit_rate": round(metrics["cache_hits"] / metrics["total_queries"], 3) if metrics["total_queries"] > 0 else 0,
            "active_streams": metrics["active_streams"]
        },
        "performance": {
            "p50": round(sorted_lats[len(sorted_lats)//2], 3) if sorted_lats else 0,
            "p95": round(sorted_lats[int(len(sorted_lats)*0.95)], 3) if len(sorted_lats) > 1 else 0,
            "p99": round(sorted_lats[-1], 3) if sorted_lats else 0
        },
        "health": {
            "uptime_hours": round((time.time() - SERVER_START_TIME) / 3600, 2),
            "low_similarity_rate": round(metrics["low_similarity_count"] / metrics["total_queries"], 3) if metrics["total_queries"] > 0 else 0
        }
    }
