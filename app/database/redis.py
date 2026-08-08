"""Redis connection management."""

import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()

redis_client: redis.Redis = None

import logging

logger = logging.getLogger(__name__)

class MockRedis:
    """In-memory mock for local dev without Redis."""
    def __init__(self):
        self.store = {}
    
    async def get(self, key):
        return self.store.get(key)
        
    async def setex(self, key, time, value):
        self.store[key] = str(value)
        
    async def keys(self, pattern="*"):
        import fnmatch
        return [k for k in self.store.keys() if fnmatch.fnmatch(k, pattern)]

    async def delete(self, *keys):
        for key in keys:
            if isinstance(key, (list, tuple, set)):
                for k in key:
                    self.store.pop(k, None)
            else:
                self.store.pop(key, None)

    async def flushdb(self):
        self.store = {}

    async def flushall(self):
        self.store = {}


async def invalidate_shop_cache(shop_id: str, r_client=None):
    """Helper to invalidate all cached menu and shop info keys for a given shop."""
    try:
        if r_client is None:
            r_client = await get_redis()
        
        pattern = f"public:*:{str(shop_id)}:*"
        if hasattr(r_client, "keys"):
            matched_keys = await r_client.keys(pattern)
            if matched_keys:
                if isinstance(matched_keys, list):
                    await r_client.delete(*matched_keys)
                else:
                    await r_client.delete(matched_keys)
    except Exception as e:
        logger.warning(f"Failed to invalidate shop cache for {shop_id}: {e}")
        
    def pipeline(self):
        class Pipe:
            def __init__(self, mock):
                self.mock = mock
            def incr(self, k):
                val = self.mock.store.get(k, 0)
                self.mock.store[k] = str(int(val) + 1)
            def expire(self, k, t):
                pass
            async def execute(self):
                pass
        return Pipe(self)
        
    async def close(self):
        pass


async def init_redis() -> redis.Redis:
    """Initialize Redis connection."""
    global redis_client
    
    # Create the client
    client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    
    try:
        # Check if Redis is actually running
        await client.ping()
        redis_client = client
    except Exception as e:
        logger.warning(f"Redis not available, using in-memory mock: {e}")
        redis_client = MockRedis()
        
    return redis_client


async def get_redis():
    """Dependency that provides a Redis client."""
    if redis_client is None:
        await init_redis()
    return redis_client


async def close_redis():
    """Close Redis connections."""
    global redis_client
    if redis_client:
        try:
            if hasattr(redis_client, "flushall"):
                await redis_client.flushall()
            elif hasattr(redis_client, "flushdb"):
                await redis_client.flushdb()
        except Exception:
            pass
        try:
            if hasattr(redis_client, "close"):
                await redis_client.close()
        except Exception:
            pass
        redis_client = None
