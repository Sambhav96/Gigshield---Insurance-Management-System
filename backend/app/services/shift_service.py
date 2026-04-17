"""services/shift_service.py — Shift state inference from telemetry pings."""
from __future__ import annotations

import uuid
from datetime import datetime

import asyncpg
import structlog

log = structlog.get_logger()

# If no ping for 30 min → idle; 60 min → offline
IDLE_THRESHOLD_MIN = 30
OFFLINE_THRESHOLD_MIN = 60


async def infer_shift_state(
    conn: asyncpg.Connection,
    rider_id: str,
) -> str:
    """
    Infer current shift state from last telemetry ping.
    Returns: 'active' | 'idle' | 'offline'
    """
    last_ping = await conn.fetchrow(
        """
        SELECT recorded_at, speed_kmh, session_active
        FROM telemetry_pings
        WHERE rider_id = $1
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        uuid.UUID(rider_id),
    )
    if not last_ping:
        return "offline"

    db_now: datetime = await conn.fetchval("SELECT NOW()")
    age_min = (db_now - last_ping["recorded_at"]).total_seconds() / 60

    if age_min >= OFFLINE_THRESHOLD_MIN:
        return "offline"
    elif age_min >= IDLE_THRESHOLD_MIN:
        return "idle"
    return "active"


async def upsert_shift_state(
    conn: asyncpg.Connection,
    rider_id: str,
    new_status: str,
    inferred_by: str = "gps",
) -> None:
    """
    Insert a new shift_state row if status changed.
    Closes the previous open row.
    """
    last = await conn.fetchrow(
        """
        SELECT id, status FROM shift_states
        WHERE rider_id = $1
        ORDER BY started_at DESC
        LIMIT 1
        """,
        uuid.UUID(rider_id),
    )

    if last and last["status"] == new_status:
        return  # no change

    # Close previous open row
    if last:
        await conn.execute(
            "UPDATE shift_states SET ended_at = NOW() WHERE id = $1 AND ended_at IS NULL",
            last["id"],
        )

    await conn.execute(
        """
        INSERT INTO shift_states (rider_id, status, started_at, inferred_by)
        VALUES ($1, $2, NOW(), $3)
        """,
        uuid.UUID(rider_id), new_status, inferred_by,
    )
