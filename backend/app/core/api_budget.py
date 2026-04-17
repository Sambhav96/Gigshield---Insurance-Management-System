"""
core/api_budget.py — Oracle API call budget tracker

Prevents OWM/WAQI/HERE bill shock by tracking daily API calls in Redis.
Each external API has a daily cap; when cap is hit, circuit breaker opens.

Usage:
    from app.core.api_budget import check_and_increment_budget, get_budget_status

    if not await check_and_increment_budget("owm"):
        raise HTTPException(503, "OWM daily budget exhausted")
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
log = structlog.get_logger()

# Daily call limits per API (conservative, adjust based on your plan)
API_DAILY_LIMITS = {
    "owm":           900,    # OWM One Call 3.0: 1000/day free tier
    "waqi":          900,    # WAQI: 1000/day
    "weatherstack":  450,    # Weatherstack: 500/mo → ~16/day, we use 450 buffer
    "here":          9000,   # HERE: 10000/day free
    "earth_engine":  100,    # Earth Engine: conservative
    "ndma":          500,    # NDMA: no published limit, conservative
    "razorpay":      9000,   # Razorpay: high limit
    "platform_zepto":   500,
    "platform_blinkit": 500,
    "platform_instamart": 500,
}

BUDGET_PREFIX = "api_budget:"


def _day_key(api_name: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{BUDGET_PREFIX}{api_name}:{day}"


def check_and_increment_budget(api_name: str, redis_client=None) -> bool:
    """
    Synchronous budget check. Returns True if call is allowed, False if budget exhausted.
    Increments counter atomically.
    """
    if redis_client is None:
        try:
            from app.core.redis_client import get_sync_redis
            redis_client = get_sync_redis()
        except Exception:
            return True  # Fail open: allow call if Redis unavailable

    limit = API_DAILY_LIMITS.get(api_name, 1000)
    key = _day_key(api_name)
    
    try:
        # INCR is atomic
        current = redis_client.incr(key)
        # Set TTL of 25 hours on first call (reset next day with buffer)
        if current == 1:
            redis_client.expire(key, 90000)  # 25 hours
        
        if current > limit:
            log.warning("api_budget_exhausted", api=api_name, current=current, limit=limit)
            # Decrement back since we won't make the call
            redis_client.decr(key)
            return False
        
        return True
    except Exception as exc:
        log.error("api_budget_check_failed", api=api_name, error=str(exc))
        return True  # Fail open


async def async_check_and_increment_budget(api_name: str, redis_client=None) -> bool:
    """Async version for FastAPI endpoints."""
    if redis_client is None:
        try:
            from app.core.redis_client import get_async_redis
            redis_client = get_async_redis()
        except Exception:
            return True

    limit = API_DAILY_LIMITS.get(api_name, 1000)
    key = _day_key(api_name)
    
    try:
        current = await redis_client.incr(key)
        if current == 1:
            await redis_client.expire(key, 90000)
        
        if current > limit:
            log.warning("api_budget_exhausted", api=api_name, current=current, limit=limit)
            await redis_client.decr(key)
            return False
        return True
    except Exception as exc:
        log.error("api_budget_check_failed", api=api_name, error=str(exc))
        return True


def get_budget_status(redis_client=None) -> dict:
    """Get current budget usage for all APIs. Used by admin dashboard."""
    if redis_client is None:
        try:
            from app.core.redis_client import get_sync_redis
            redis_client = get_sync_redis()
        except Exception:
            return {}
    
    status = {}
    for api_name, limit in API_DAILY_LIMITS.items():
        key = _day_key(api_name)
        try:
            used = int(redis_client.get(key) or 0)
            status[api_name] = {
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
                "pct_used": round(used / limit * 100, 1) if limit > 0 else 0,
                "exhausted": used >= limit,
            }
        except Exception:
            status[api_name] = {"used": 0, "limit": limit, "remaining": limit, "pct_used": 0, "exhausted": False}
    
    return status
