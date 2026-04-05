import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi import HTTPException, status

from core.config import GOOGLE_CLIENT_ID, JWT_SECRET_KEY, ALGORITHM
from core.logger import get_logger

logger = get_logger(__name__)

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours


def verify_google_token(token: str) -> dict:
    """
    Verify the Google ID Token sent from the frontend.
    Returns the decoded user info if valid.
    """
    try:
        # In development, you might want to skip verification if no CLIENT_ID is set
        # But for professional use, it's always required.
        if not GOOGLE_CLIENT_ID:
            # Fallback for local testing if explicitly allowed
            if os.getenv("ALLOW_INSECURE_AUTH") == "true":
                return {"sub": "test_advisor_user", "email": "test@example.com"}
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="GOOGLE_CLIENT_ID not configured"
            )

        idinfo = id_token.verify_oauth2_token(
            token, 
            google_requests.Request(), 
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )


        return idinfo
    except ValueError as e:
        logger.warning("google_token_verification_failed")
        # Check if the error is due to Client ID mismatch
        if "Wrong recipient" in str(e):
             raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mismatched Client ID. Check frontend vs backend .env files.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google Token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Ensure scopes are always a list in the token
    if "scopes" not in to_encode:
        to_encode["scopes"] = []
        
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

