import os

import redis.asyncio as aioredis

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            os.environ["REDIS_URL"],
            encoding="utf-8",
            decode_responses=False,
        )
    return _redis


async def cache_get(key: str) -> str | None:
    r = await get_redis()
    val = await r.get(key)
    return val.decode() if val else None


async def cache_set(key: str, value: str, ttl: int = 3600) -> None:
    r = await get_redis()
    await r.setex(key, ttl, value)
