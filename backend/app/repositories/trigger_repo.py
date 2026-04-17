"""repositories/trigger_repo.py — DB operations for trigger_events."""
from __future__ import annotations

import json
import uuid
from typing import Optional
import asyncpg


async def create_trigger_event(
    conn: asyncpg.Connection,
    trigger_type: str,
    h3_index: str,
    hub_id: str,
    oracle_score: float,
    weight_config: dict,
    signal_scores: dict,
    raw_api_data: dict,
    cold_start_mode: bool,
    cooldown_active: bool,
    cooldown_payout_factor: float,
    correlation_factor: float,
) -> str:
    trigger_id = await conn.fetchval(
        """
        INSERT INTO trigger_events (
            trigger_type, h3_index, hub_id, oracle_score,
            satellite_score, weather_score, traffic_score, peer_score, accel_score,
            weight_config, raw_api_data, status,
            cold_start_mode, cooldown_active, cooldown_payout_factor, correlation_factor
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,'active',$12,$13,$14,$15)
        RETURNING id
        """,
        trigger_type, h3_index, uuid.UUID(hub_id), oracle_score,
        signal_scores.get("satellite"), signal_scores.get("weather"),
        signal_scores.get("traffic"), signal_scores.get("peer"), signal_scores.get("accel"),
        json.dumps(weight_config), json.dumps(raw_api_data),
        cold_start_mode, cooldown_active, cooldown_payout_factor, correlation_factor,
    )
    return str(trigger_id)


async def get_active_triggers_for_hex(
    conn: asyncpg.Connection, h3_index: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT * FROM trigger_events
        WHERE h3_index = $1 AND status IN ('active','resolving')
        ORDER BY triggered_at DESC
        """,
        h3_index,
    )
    return [dict(r) for r in rows]


async def update_trigger_status(
    conn: asyncpg.Connection, trigger_id: str, status: str
) -> None:
    extra = ""
    if status == "resolved":
        extra = ", resolved_at = NOW()"
    await conn.execute(
        f"UPDATE trigger_events SET status = $1{extra} WHERE id = $2",
        status, uuid.UUID(trigger_id),
    )


async def compute_correlation_factor(
    conn: asyncpg.Connection, city: str
) -> float:
    """
    C = active_hexes_in_city / total_hexes_in_city
    platform_down always returns C=1.0
    """
    total_hexes = await conn.fetchval(
        "SELECT COUNT(DISTINCT h3_index_res9) FROM hubs WHERE city = $1", city
    ) or 1

    active_hexes = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT te.h3_index)
        FROM trigger_events te
        JOIN hubs h ON te.hub_id = h.id
        WHERE h.city = $1
          AND te.status IN ('active','resolving')
          AND te.triggered_at >= NOW() - INTERVAL '2 hours'
        """,
        city,
    ) or 0

    return float(active_hexes) / float(total_hexes)


async def check_duplicate_trigger(
    conn: asyncpg.Connection, h3_index: str, trigger_type: str
) -> Optional[str]:
    """Returns existing trigger_id if fired in last 15 min."""
    row = await conn.fetchrow(
        """
        SELECT id FROM trigger_events
        WHERE h3_index = $1 AND trigger_type = $2
          AND triggered_at >= NOW() - INTERVAL '15 minutes'
          AND status != 'cancelled'
        LIMIT 1
        """,
        h3_index, trigger_type,
    )
    return str(row["id"]) if row else None


async def check_cooldown(
    conn: asyncpg.Connection,
    h3_index: str,
    trigger_type: str,
    cooldown_minutes: int,
) -> bool:
    """Returns True if a recent resolved trigger exists (cooldown active)."""
    row = await conn.fetchrow(
        """
        SELECT id FROM trigger_events
        WHERE h3_index = $1 AND trigger_type = $2
          AND status = 'resolved'
          AND resolved_at >= NOW() - ($3 || ' minutes')::interval
        LIMIT 1
        """,
        h3_index, trigger_type, str(cooldown_minutes),
    )
    return row is not None
