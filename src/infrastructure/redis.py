import logging

import redis.asyncio as aioredis

from ..config import get_settings

logger = logging.getLogger(__name__)

_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.ConnectionPool.from_url(settings.redis_url, max_connections=50, decode_responses=True)
        logger.info(f"Initialized Redis connection pool for {settings.redis_url}")
    return _redis_pool


def get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        pool = get_redis_pool()
        _redis_client = aioredis.Redis(connection_pool=pool)
    return _redis_client


async def check_redis_health() -> bool:
    """Executes PING to verify Redis connectivity."""
    try:
        client = get_redis_client()
        pong = await client.ping()
        return bool(pong)
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        return False


async def close_redis_pool() -> None:
    """Closes Redis pool during application shutdown."""
    global _redis_client, _redis_pool
    if _redis_client is not None:
        logger.info("Closing Redis connection client...")
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool is not None:
        logger.info("Disconnecting Redis connection pool...")
        await _redis_pool.disconnect()
        _redis_pool = None
        logger.info("Redis connection pool closed.")
