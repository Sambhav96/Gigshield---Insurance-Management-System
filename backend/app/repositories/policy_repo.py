"""repositories/policy_repo.py — All DB operations for policies."""
from __future__ import annotations

import uuid
from typing import Optional
import asyncpg


async def get_policy_by_id(conn: asyncpg.Connection, policy_id: str) -> Optional[dict]:
    row = await conn.fetchrow("SELECT * FROM policies WHERE id = $1", uuid.UUID(policy_id))
    return dict(row) if row else None


async def get_active_policy_for_rider(
    conn: asyncpg.Connection, rider_id: str
) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT * FROM policies WHERE rider_id = $1 AND status = 'active' LIMIT 1",
        uuid.UUID(rider_id),
    )
    return dict(row) if row else None


async def list_policies_for_hub(
    conn: asyncpg.Connection, hub_id: str, status: str = "active"
) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM policies WHERE hub_id = $1 AND status = $2",
        uuid.UUID(hub_id), status,
    )
    return [dict(r) for r in rows]


async def reset_weekly_payout_used(conn: asyncpg.Connection) -> int:
    """Reset weekly_payout_used = 0 for ALL policies every Monday."""
    result = await conn.execute(
        """
        UPDATE policies
        SET weekly_payout_used = 0, week_start_date = date_trunc('week', NOW())::date
        WHERE status IN ('active','paused','lapsed')
        """
    )
    return int(result.split()[-1])


async def update_discount_weeks(
    conn: asyncpg.Connection, policy_id: str, discount_weeks: int
) -> None:
    await conn.execute(
        "UPDATE policies SET discount_weeks = $1 WHERE id = $2",
        discount_weeks, uuid.UUID(policy_id),
    )


async def update_weekly_premium(
    conn: asyncpg.Connection, policy_id: str, new_premium: float
) -> None:
    await conn.execute(
        "UPDATE policies SET weekly_premium = $1 WHERE id = $2",
        new_premium, uuid.UUID(policy_id),
    )
