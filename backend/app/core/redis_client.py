"""core/redis_client.py — Redis connection singleton used by all services."""
from __future__ import annotations

import redis.asyncio as aioredis
import redis as syncredis
from app.config import get_settings

settings = get_settings()

_async_client: aioredis.Redis | None = None
_sync_client: syncredis.Redis | None = None


def get_async_redis() -> aioredis.Redis:
    global _async_client
    if _async_client is None:
        _async_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _async_client


def get_sync_redis() -> syncredis.Redis:
    """Used by Celery workers (sync context)."""
    global _sync_client
    if _sync_client is None:
        _sync_client = syncredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _sync_client
