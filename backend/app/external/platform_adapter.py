"""external/platform_adapter.py — Platform health check + rider status adapters.

FIX: consecutive_failures moved from in-memory dict to Redis so it:
  - Persists across worker restarts
  - Is shared across multiple Celery workers
  - Uses 35-min TTL (7 checks × 5 min) to auto-reset if checks stop
"""
from __future__ import annotations

import httpx
import structlog

from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker
from app.models.common import PlatformType

settings = get_settings()
log = structlog.get_logger()

PLATFORM_HEALTH_URLS = {
    PlatformType.zepto:     settings.zepto_health_url,
    PlatformType.blinkit:   settings.blinkit_health_url,
    PlatformType.instamart: settings.instamart_health_url,
}

PLATFORM_CBS = {
    p: get_circuit_breaker(f"platform_{p.value}") for p in PlatformType
}

# Redis key pattern for consecutive failures — shared across workers
_FAILURES_KEY = "platform_failures:{platform}"
_FAILURES_TTL = 2100  # 35 min = 7 checks × 5 min; auto-reset if checks stop


def _get_failures(platform: str) -> int:
    """Read consecutive failure count from Redis."""
    try:
        from app.core.redis_client import get_sync_redis
        redis = get_sync_redis()
        val = redis.get(_FAILURES_KEY.format(platform=platform))
        return int(val) if val else 0
    except Exception:
        return 0


def _set_failures(platform: str, count: int) -> None:
    """Write consecutive failure count to Redis with TTL."""
    try:
        from app.core.redis_client import get_sync_redis
        redis = get_sync_redis()
        if count == 0:
            redis.delete(_FAILURES_KEY.format(platform=platform))
        else:
            redis.set(_FAILURES_KEY.format(platform=platform), count, ex=_FAILURES_TTL)
    except Exception as exc:
        log.warning("platform_failures_redis_write_failed", error=str(exc))


def check_platform_health(platform: str) -> dict:
    """
    Returns: {is_up: bool, consecutive_failures: int, platform_down_score: float}
    Called every 5 minutes via Celery beat.
    consecutive_failures stored in Redis (shared across workers, persists restarts).
    """
    url = PLATFORM_HEALTH_URLS.get(PlatformType(platform))
    if not url:
        return {"is_up": True, "consecutive_failures": 0, "platform_down_score": 0.0}

    cb = PLATFORM_CBS[PlatformType(platform)]
    failures = _get_failures(platform)

    try:
        def _check():
            with httpx.Client(timeout=8) as client:
                resp = client.get(url)
                return resp.status_code == 200

        is_up = cb.call(_check)
        if is_up:
            _set_failures(platform, 0)
            failures = 0
        else:
            failures += 1
            _set_failures(platform, failures)
    except Exception as exc:
        log.warning("platform_health_check_failed", platform=platform, error=str(exc))
        failures += 1
        _set_failures(platform, failures)
        is_up = False

    score = _score_platform_down(failures)
    return {
        "is_up":                is_up,
        "consecutive_failures": failures,
        "platform_down_score":  score,
    }


def _score_platform_down(consecutive_failures: int) -> float:
    """
    consecutive_failures = count of failed 5-min checks in last 30 min.
    6 failures = 30 min of continuous downtime = full trigger score.
    """
    if consecutive_failures >= 6:
        return 1.00
    elif consecutive_failures >= 3:
        return 0.50
    return 0.00


def get_rider_platform_status(rider_id: str, platform: str) -> dict | None:
    """
    In production: call Zepto/Blinkit B2B partner API.
    Returns None if API unavailable (intent check treats as N/A — soft fail, not hard fail).
    Currently returns mock 'available' for dev/demo — replace with real API call in Phase 2.
    """
    # TODO Phase 2: integrate Zepto/Blinkit B2B partner API for real rider status
    return {
        "status":    "available",
        "last_seen": None,
    }
