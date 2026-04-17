"""api/v1/hub.py — Hub manager scoped dashboard endpoints."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_db, get_current_hub_manager

router = APIRouter(prefix="/hub", tags=["hub-manager"])


class HubIncidentAction(BaseModel):
    action: str


@router.get("/metrics")
async def get_hub_metrics(
    hub_ctx: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_ids = hub_ctx["hub_ids"]

    active_riders = await conn.fetchval(
        """
        WITH latest_shift AS (
            SELECT DISTINCT ON (rider_id) rider_id, status
            FROM shift_states
            ORDER BY rider_id, started_at DESC
        )
        SELECT COUNT(*)
        FROM riders r
        LEFT JOIN latest_shift ls ON ls.rider_id = r.id
        WHERE r.hub_id = ANY($1::uuid[])
          AND COALESCE(ls.status, 'idle') = 'active'
        """,
        hub_ids,
    )

    open_incidents = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM trigger_events te
        WHERE te.hub_id = ANY($1::uuid[])
          AND te.status IN ('detected', 'active', 'resolving')
        """,
        hub_ids,
    )

    risk_quotient = await conn.fetchval(
        """
        SELECT COALESCE(AVG(te.oracle_score), 0)
        FROM trigger_events te
        WHERE te.hub_id = ANY($1::uuid[])
          AND te.status IN ('detected', 'active', 'resolving')
        """,
        hub_ids,
    )

    hubs = await conn.fetch(
        "SELECT name FROM hubs WHERE id = ANY($1::uuid[]) ORDER BY name",
        hub_ids,
    )
    hub_name = "Multi-Hub Zone" if len(hubs) > 1 else (hubs[0]["name"] if hubs else "Hub Zone")

    return {
        "active_riders": int(active_riders or 0),
        "open_incidents": int(open_incidents or 0),
        "risk_quotient": round(float(risk_quotient or 0), 2),
        "hub_name": hub_name,
    }


@router.get("/fleet")
async def get_hub_fleet(
    hub_ctx: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_ids = hub_ctx["hub_ids"]

    rows = await conn.fetch(
        """
        WITH latest_shift AS (
            SELECT DISTINCT ON (rider_id) rider_id, status, started_at
            FROM shift_states
            ORDER BY rider_id, started_at DESC
        ),
        latest_ping AS (
            SELECT DISTINCT ON (rider_id) rider_id, h3_index_res9, synced_at
            FROM telemetry_pings
            ORDER BY rider_id, synced_at DESC
        )
        SELECT
            r.id AS rider_id,
            COALESCE(r.name, 'Unknown Rider') AS name,
            CASE
                WHEN COALESCE(ls.status, 'idle') = 'active' THEN 'Active Shift'
                ELSE 'Idle'
            END AS status,
            COALESCE(lp.h3_index_res9, 'Hub Zone') AS last_location,
            COALESCE(INITCAP(p.plan), 'None') AS policy_plan,
            COALESCE((r.effective_income * p.plan_cap_multiplier)::numeric, 0)::float AS coverage_cap,
            (COALESCE(ls.status, 'idle') = 'active') AS is_on_shift
        FROM riders r
        LEFT JOIN latest_shift ls ON ls.rider_id = r.id
        LEFT JOIN policies p ON p.rider_id = r.id AND p.status = 'active'
        LEFT JOIN latest_ping lp ON lp.rider_id = r.id
        WHERE r.hub_id = ANY($1::uuid[])
        ORDER BY r.created_at DESC
        """,
        hub_ids,
    )

    return [dict(row) for row in rows]


@router.get("/incidents")
async def get_hub_incidents(
    hub_ctx: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_ids = hub_ctx["hub_ids"]

    rows = await conn.fetch(
        """
        SELECT
            te.id,
            te.trigger_type,
            te.triggered_at,
            te.status,
            COALESCE(te.oracle_score, 0)::float AS oracle_score,
            COALESCE((
                SELECT COUNT(DISTINCT c.rider_id)
                FROM claims c
                WHERE c.trigger_id = te.id
            ), 0) AS affected_rider_count
        FROM trigger_events te
        WHERE te.hub_id = ANY($1::uuid[])
        ORDER BY te.triggered_at DESC
        LIMIT 100
        """,
        hub_ids,
    )

    return [dict(row) for row in rows]


@router.patch("/incidents/{incident_id}")
async def patch_hub_incident(
    incident_id: str,
    body: HubIncidentAction,
    hub_ctx: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_ids = hub_ctx["hub_ids"]
    incident = await conn.fetchrow(
        "SELECT id, status FROM trigger_events WHERE id::text = $1 AND hub_id = ANY($2::uuid[])",
        incident_id,
        hub_ids,
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    action = body.action.lower().strip()
    current_status = incident["status"]

    if action == "triage":
        new_status = "active"
    elif action == "resolve":
        new_status = "resolving" if current_status == "active" else "resolved"
    elif action == "cancel":
        new_status = "cancelled"
    elif action == "reopen":
        new_status = "active"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    await conn.execute(
        "UPDATE trigger_events SET status = $1, resolved_at = CASE WHEN $1='resolved' THEN NOW() ELSE resolved_at END WHERE id = $2",
        new_status,
        incident["id"],
    )

    return {"status": "updated", "incident_id": incident_id, "incident_status": new_status}
