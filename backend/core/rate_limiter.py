import time
from fastapi import HTTPException, Request, Depends
from core.connections import redis_client
from core.dependencies import get_current_user
from core.logger import get_logger

logger = get_logger(__name__)

# Configurable limits
DEFAULT_LIMIT = 20  # requests
WINDOW_SECONDS = 60 # per minute

async def check_rate_limit(request: Request, user_id: str = Depends(get_current_user)):
    """
    Dependency to enforce rate limiting per user using Redis.
    Key format: rate_limit:{user_id}:{window_timestamp}
    """
    if not redis_client:
        return # Skip if redis is down (fail open for reliability, or change to fail closed)

    # Use a fixed-window approach for simplicity (1-minute buckets)
    # For more precision, a sliding window with ZSET can be used.
    current_minute = int(time.time() // WINDOW_SECONDS)
    key = f"rate_limit:{user_id}:{current_minute}"

    try:
        # Increment and set expiration in a pipeline
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS + 10) # slightly longer than window
        res = await pipe.execute()
        
        count = res[0]
        
        if count > DEFAULT_LIMIT:
            logger.warning(f"Rate limit exceeded for user {user_id}: {count}/{DEFAULT_LIMIT}")
            raise HTTPException(
                status_code=429, 
                detail={
                    "error": "Too Many Requests",
                    "message": f"You have exceeded the rate limit of {DEFAULT_LIMIT} requests per minute.",
                    "retry_after_seconds": WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limiter error: {e}")
        return # Fail open if Redis has issues

    return True
