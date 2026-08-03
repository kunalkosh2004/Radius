from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Process-wide Redis client (asyncio). One connection pool per process."""
    settings = get_settings()
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)
