import time
import json
import redis.asyncio as aioredis
from core.logger import get_logger

logger = get_logger(__name__)

class RateLimiter:
    """
    Redis-backed sliding window rate limiter and token quota manager.
    """
    
    @staticmethod
    async def check_rate_limit(redis: aioredis.Redis, user_id: str, limit: int = 10, window: int = 60) -> bool:
        """
        Sliding window rate limit: limit requests per window (seconds).
        Returns True if allowed, False if blocked.
        """
        key = f"rate_limit:{user_id}"
        now = time.time()
        
        async with redis.pipeline(transaction=True) as pipe:
            # Remove old entries
            pipe.zremrangebyscore(key, 0, now - window)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count current window
            pipe.zcard(key)
            # Set expiration for the key
            pipe.expire(key, window)
            
            results = await pipe.execute()
            count = results[2]
            
            if count > limit:
                logger.warning(f"Rate limit exceeded for user {user_id}: {count}/{limit}")
                return False
            return True

    @staticmethod
    async def update_token_quota(redis: aioredis.Redis, user_id: str, tokens: int, daily_limit: int = 50000) -> bool:
        """
        Track and enforce daily token quota.
        Returns True if within quota, False if exceeded.
        """
        today = time.strftime("%Y-%m-%d")
        key = f"token_quota:{user_id}:{today}"
        
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incrby(key, tokens)
            pipe.expire(key, 86400) # 24 hours
            
            results = await pipe.execute()
            current_total = results[0]
            
            if current_total > daily_limit:
                logger.error(f"Token quota exceeded for user {user_id}: {current_total}/{daily_limit}")
                return False
            return True

    @staticmethod
    async def get_remaining_quota(redis: aioredis.Redis, user_id: str, daily_limit: int = 50000) -> int:
        today = time.strftime("%Y-%m-%d")
        key = f"token_quota:{user_id}:{today}"
        val = await redis.get(key)
        if val is None:
            return daily_limit
        return max(0, daily_limit - int(val))
