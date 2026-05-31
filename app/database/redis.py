"""Redis connection management."""

import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()

redis_client: redis.Redis = None


async def init_redis() -> redis.Redis:
    """Initialize Redis connection."""
    global redis_client
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    return redis_client


async def get_redis() -> redis.Redis:
    """Dependency that provides a Redis client."""
    if redis_client is None:
        await init_redis()
    return redis_client


async def close_redis():
    """Close Redis connections."""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
