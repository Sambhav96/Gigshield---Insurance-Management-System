"""repositories/hub_repo.py — DB operations for hubs."""
from __future__ import annotations

import uuid
from typing import Optional
import asyncpg


async def get_hub_by_id(conn: asyncpg.Connection, hub_id: str) -> Optional[dict]:
    row = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1", uuid.UUID(hub_id))
    return dict(row) if row else None


async def get_hub_by_h3(conn: asyncpg.Connection, h3_index: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT * FROM hubs WHERE h3_index_res9 = $1 OR h3_index_res8 = $1 LIMIT 1",
        h3_index,
    )
    return dict(row) if row else None


async def list_hubs(
    conn: asyncpg.Connection, city: Optional[str] = None
) -> list[dict]:
    if city:
        rows = await conn.fetch("SELECT * FROM hubs WHERE city = $1 ORDER BY name", city)
    else:
        rows = await conn.fetch("SELECT * FROM hubs ORDER BY city, name")
    return [dict(r) for r in rows]


async def is_cold_start(conn: asyncpg.Connection, h3_index: str) -> bool:
    """
    cold_start_mode = True if < 20 confirmed resolved triggers for this zone.
    Uses zone_risk_cache.confirmed_event_count.
    """
    count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM trigger_events
        WHERE h3_index = $1 AND status = 'resolved'
        """,
        h3_index,
    )
    return int(count or 0) < 20
