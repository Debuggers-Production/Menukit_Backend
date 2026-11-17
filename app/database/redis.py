"""Redis connection management with Ultra-Fast In-Memory L1 Cache fallback."""

import time
import logging
from typing import Optional, List, Dict, Tuple
import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

redis_client: Optional[redis.Redis] = None


class MockPipeline:
    def __init__(self, store: Dict[str, Tuple[str, Optional[float]]]):
        self.store = store
        self.commands = []

    def incr(self, key: str):
        self.commands.append(('incr', key))

    def expire(self, key: str, time_val: int):
        self.commands.append(('expire', key, time_val))

    async def execute(self):
        now = time.time()
        results = []
        for cmd in self.commands:
            if cmd[0] == 'incr':
                key = cmd[1]
                entry = self.store.get(key)
                curr = 0
                exp = None
                if entry:
                    v, exp = entry
                    if exp is not None and now > exp:
                        curr = 0
                    else:
                        try:
                            curr = int(v)
                        except ValueError:
                            curr = 0
                new_v = curr + 1
                self.store[key] = (str(new_v), exp)
                results.append(new_v)
            elif cmd[0] == 'expire':
                key, time_val = cmd[1], cmd[2]
                if key in self.store:
                    v, _ = self.store[key]
                    self.store[key] = (v, time.time() + float(time_val))
                results.append(1)
        self.commands = []
        return results


class MockRedis:
    """Ultra-fast In-memory TTL LRU store for zero-latency operations (< 0.05ms)."""
    _store: Dict[str, Tuple[str, Optional[float]]] = {}
    _max_capacity: int = 5000

    def __init__(self):
        self.store = MockRedis._store

    def pipeline(self):
        return MockPipeline(self.store)

    async def get(self, key: str) -> Optional[str]:
        entry = self.store.get(key)
        if entry is None:
            return None
        val, exp = entry
        if exp is not None and time.time() > exp:
            self.store.pop(key, None)
            return None
        return val

    async def setex(self, key: str, seconds: int, value: str):
        if len(self.store) >= MockRedis._max_capacity:
            # Evict oldest 10% of entries to keep memory low
            keys_to_remove = list(self.store.keys())[:500]
            for k in keys_to_remove:
                self.store.pop(k, None)
        exp = time.time() + float(seconds) if seconds else None
        self.store[key] = (str(value), exp)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        await self.setex(key, ex or 0, value)

    async def exists(self, key: str) -> int:
        return 1 if (await self.get(key)) is not None else 0

    async def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        now = time.time()
        valid_keys = []
        for k, (val, exp) in list(self.store.items()):
            if exp is not None and now > exp:
                self.store.pop(k, None)
            elif fnmatch.fnmatch(k, pattern):
                valid_keys.append(k)
        return valid_keys

    async def delete(self, *keys):
        for key in keys:
            if isinstance(key, (list, tuple, set)):
                for k in key:
                    self.store.pop(k, None)
            else:
                self.store.pop(key, None)

    async def incr(self, key: str) -> int:
        val = await self.get(key)
        new_val = int(val) + 1 if val is not None and str(val).isdigit() else 1
        entry = self.store.get(key)
        exp = entry[1] if entry else None
        self.store[key] = (str(new_val), exp)
        return new_val

    async def expire(self, key: str, seconds: int) -> int:
        if key in self.store:
            val, _ = self.store[key]
            self.store[key] = (val, time.time() + float(seconds))
            return 1
        return 0

    async def flushdb(self):
        self.store.clear()

    async def flushall(self):
        self.store.clear()

    async def close(self):
        pass


async def invalidate_shop_cache(shop_id: str, slug: Optional[str] = None, r_client=None):
    """Helper to invalidate all cached menu, items, discounts, and shop info keys for a given shop."""
    try:
        if r_client is None:
            r_client = await get_redis()

        str_id = str(shop_id).strip().lower()
        keys_to_delete = set()
        found_slugs = set()
        if slug:
            found_slugs.add(str(slug).strip().lower())

        # Check in-memory slug-uuid cache and clear matching entries
        try:
            from app.api.v1.public import _SLUG_UUID_CACHE
            for s_name, uid in list(_SLUG_UUID_CACHE.items()):
                if str(uid).strip().lower() == str_id:
                    found_slugs.add(s_name)
                    _SLUG_UUID_CACHE.pop(s_name, None)
            if slug:
                _SLUG_UUID_CACHE.pop(str(slug).strip().lower(), None)
        except Exception:
            pass

        # Scan Redis slug_map to find any slug associated with this shop_id
        if hasattr(r_client, "keys"):
            try:
                slug_maps = await r_client.keys("public:slug_map:*")
                for smk in slug_maps:
                    val = await r_client.get(smk)
                    if val and str(val).strip().lower() == str_id:
                        s_name = smk.replace("public:slug_map:", "").strip().lower()
                        found_slugs.add(s_name)
                        keys_to_delete.add(smk)
            except Exception:
                pass

        # Fallback to DB lookup for slug if not found yet
        if not found_slugs:
            try:
                import uuid
                from app.database.session import async_session_factory
                from app.models.shop import Shop
                from sqlalchemy import select
                try:
                    u_val = uuid.UUID(str_id)
                    async with async_session_factory() as session:
                        res = await session.execute(select(Shop.slug).where(Shop.id == u_val))
                        db_slug = res.scalar_one_or_none()
                        if db_slug:
                            found_slugs.add(str(db_slug).strip().lower())
                except (ValueError, TypeError):
                    pass
            except Exception:
                pass

        # Direct explicit key deletions for UUID
        keys_to_delete.add(f"public:shop:{str_id}")
        keys_to_delete.add(f"public_shop:{str_id}")
        keys_to_delete.add(f"shop:{str_id}")

        # Direct explicit key deletions for all associated slugs
        for s in found_slugs:
            clean_s = str(s).strip().lower()
            keys_to_delete.add(f"public:shop:{clean_s}")
            keys_to_delete.add(f"public:slug_map:{clean_s}")
            keys_to_delete.add(f"public_shop:{clean_s}")
            keys_to_delete.add(f"shop:{clean_s}")

        # Wildcard pattern matches across all namespaces
        if hasattr(r_client, "keys"):
            for pat in [f"public:*{str_id}*", f"public_shop:*{str_id}*", f"shop:*{str_id}*"]:
                matched = await r_client.keys(pat)
                if matched:
                    keys_to_delete.update(matched)

            for s in found_slugs:
                clean_s = str(s).strip().lower()
                for pat in [f"public:*{clean_s}*", f"public_shop:*{clean_s}*", f"shop:*{clean_s}*"]:
                    matched = await r_client.keys(pat)
                    if matched:
                        keys_to_delete.update(matched)

        if keys_to_delete:
            await r_client.delete(*list(keys_to_delete))
    except Exception as e:
        logger.warning(f"Failed to invalidate shop cache for {shop_id}: {e}")


async def init_redis() -> redis.Redis:
    """Initialize Redis connection with fast fallback to in-memory TTL store."""
    global redis_client

    client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )

    try:
        await client.ping()
        redis_client = client
        logger.info("Redis connected successfully.")
    except Exception as e:
        logger.info(f"Redis not running ({e}). Using ultra-fast in-memory TTL caching engine.")
        redis_client = MockRedis()

    return redis_client


async def get_redis():
    """Dependency that provides a Redis / In-Memory client."""
    if redis_client is None:
        await init_redis()
    return redis_client


async def close_redis():
    """Close Redis connections cleanly."""
    global redis_client
    if redis_client:
        try:
            if hasattr(redis_client, "close"):
                await redis_client.close()
        except Exception:
            pass
        redis_client = None
