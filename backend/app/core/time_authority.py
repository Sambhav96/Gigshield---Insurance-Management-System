"""
core/time_authority.py

RULE: All timestamps from PostgreSQL NOW() only.
Never use datetime.now(), time.time() for business logic timestamps.
This module is the SINGLE place NOW() is called for all services.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import asyncpg
import structlog

from app.core.database import get_pool

log = structlog.get_logger()

# Max allowed drift in milliseconds before we refuse to start
MAX_DRIFT_MS = 30_000
WARN_DRIFT_MS = 5_000


async def get_db_now(conn: asyncpg.Connection | None = None) -> datetime:
    """Return current time from PostgreSQL. This is the canonical 'now'."""
    if conn:
        return await conn.fetchval("SELECT NOW()")  # type: ignore[return-value]
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetchval("SELECT NOW()")  # type: ignore[return-value]


async def get_db_now_ist_hour(conn: asyncpg.Connection | None = None) -> int:
    """Return current IST hour (0-23) from DB — used for MU_TABLE lookup."""
    if conn:
        return await conn.fetchval(
            "SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int"
        )  # type: ignore[return-value]
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetchval(
            "SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int"
        )  # type: ignore[return-value]


async def check_clock_drift() -> None:
    """Check drift between DB time and local system time on startup."""
    import time

    pool = await get_pool()
    async with pool.acquire() as conn:
        db_time: datetime = await conn.fetchval("SELECT NOW()")

    local_ts = time.time()
    db_ts = db_time.timestamp()
    drift_ms = abs(db_ts - local_ts) * 1000

    if drift_ms > MAX_DRIFT_MS:
        log.critical(
            "clock_drift_critical",
            drift_ms=drift_ms,
            message="DB-local clock drift exceeds 30s — refusing to start",
        )
        raise RuntimeError(f"Clock drift too large: {drift_ms:.0f}ms")
    elif drift_ms > WARN_DRIFT_MS:
        log.warning("clock_drift_warning", drift_ms=drift_ms)
    else:
        log.info("clock_drift_ok", drift_ms=drift_ms)
