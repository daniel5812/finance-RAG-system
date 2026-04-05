from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg
from core import db
from core.auth import verify_google_token, create_access_token
from core.audit import log_audit_event
from core.logger import get_logger
from pydantic import BaseModel

from typing import Optional

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

class GoogleLoginRequest(BaseModel):
    id_token: str

@router.post("/login/google")
async def login_google(req: GoogleLoginRequest, pool: asyncpg.Pool = Depends(db.get_pool)):
    """
    Exchange a Google ID Token for a local JWT.
    This creates the user in our DB if they don't exist.
    """
    logger.info("login_google called")
    idinfo = verify_google_token(req.id_token)

    user_id = idinfo['sub']
    email = idinfo.get('email')
    name = idinfo.get('name')

    logger.info(f"Google token verified for user {user_id}")
    async with pool.acquire() as conn:

        # Create or update user
        await conn.execute("""
            INSERT INTO users (id, email, full_name, hashed_password)
            VALUES ($1, $2, $3, 'GOOGLE_AUTH')
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, full_name = EXCLUDED.full_name
        """, user_id, email, name)
        
        # Fetch actual role and scopes from DB (in case they were changed by an admin)
        row = await conn.fetchrow("SELECT role, scopes FROM users WHERE id = $1", user_id)
        role = row['role'] if row else 'user'
        scopes = row['scopes'] if row else []
        
        # Ensure profile exists
        await conn.execute("INSERT INTO user_profiles (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
        
        # Log Audit Event
        await log_audit_event(
            pool=pool,
            event_type="login",
            user_id=user_id,
            action="access",
            status="success",
            metadata={"email": email, "method": "google_oauth"}
        )
        
    # Generate our own stateless JWT including scopes
    access_token = create_access_token(data={"sub": user_id, "scopes": scopes})
    
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "user_id": user_id,
        "email": email,
        "name": name,
        "role": role,
        "scopes": scopes
    }

