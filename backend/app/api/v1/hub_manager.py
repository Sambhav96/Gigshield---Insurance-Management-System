"""api/v1/hub_manager.py — Hub manager scoped APIs."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_db, get_current_hub_manager

router = APIRouter(prefix="/hub", tags=["hub-manager"])


class IncidentActionRequest(BaseModel):
    action: str


@router.get("/metrics")
async def hub_metrics(
    manager: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_id = manager["hub_id"]
    hub = await conn.fetchrow("SELECT id, name, h3_index_res9, h3_index_res8 FROM hubs WHERE id = $1", hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    active_riders = await conn.fetchval(
        "SELECT COUNT(*) FROM policies WHERE hub_id = $1 AND status = 'active'",
        hub_id,
    )

    open_incidents = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM trigger_events
        WHERE status IN ('active','resolving')
          AND h3_index = ANY($1::text[])
        """,
        [hub["h3_index_res9"], hub["h3_index_res8"]],
    )

    risk_avg = await conn.fetchval(
        "SELECT COALESCE(AVG(risk_score), 0) FROM riders WHERE hub_id = $1",
        hub_id,
    )

    return {
        "active_riders": int(active_riders or 0),
        "open_incidents": int(open_incidents or 0),
        "risk_quotient": float(risk_avg or 0) / 100.0,
        "hub_name": hub["name"],
    }


@router.get("/fleet")
async def hub_fleet(
    manager: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_id = manager["hub_id"]

    rows = await conn.fetch(
        """
        WITH latest_ping AS (
            SELECT DISTINCT ON (rider_id)
                rider_id,
                latitude,
                longitude,
                h3_index_res9,
                synced_at
            FROM telemetry_pings
            ORDER BY rider_id, synced_at DESC
        ),
        latest_shift AS (
            SELECT DISTINCT ON (rider_id)
                rider_id,
                status
            FROM shift_states
            ORDER BY rider_id, started_at DESC
        )
        SELECT
            r.id AS rider_id,
            COALESCE(r.name, 'Unknown Rider') AS name,
            p.plan AS policy_plan,
            (COALESCE(r.effective_income, 0) * COALESCE(p.plan_cap_multiplier, 0))::float AS coverage_cap,
            (COALESCE(ls.status, 'idle') = 'active') AS is_on_shift,
            COALESCE(lp.h3_index_res9, 'Hub Zone') AS last_location,
            r.risk_profile
        FROM riders r
        JOIN policies p ON p.rider_id = r.id AND p.status = 'active'
        LEFT JOIN latest_ping lp ON lp.rider_id = r.id
        LEFT JOIN latest_shift ls ON ls.rider_id = r.id
        WHERE p.hub_id = $1
        ORDER BY r.created_at DESC
        """,
        hub_id,
    )

    fleet = []
    for row in rows:
        d = dict(row)
        fleet.append(
            {
                "rider_id": str(d["rider_id"]),
                "name": d["name"],
                "policy_plan": str(d["policy_plan"] or "").title(),
                "coverage_cap": float(d.get("coverage_cap") or 0),
                "is_on_shift": bool(d.get("is_on_shift")),
                "last_location": d.get("last_location") or "Hub Zone",
                "risk_profile": d.get("risk_profile") or "medium",
            }
        )

    return {"fleet": fleet}


@router.get("/incidents")
async def hub_incidents(
    manager: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_id = manager["hub_id"]
    hub = await conn.fetchrow("SELECT h3_index_res9, h3_index_res8 FROM hubs WHERE id = $1", hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

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
        WHERE te.h3_index = ANY($1::text[])
        ORDER BY te.triggered_at DESC
        LIMIT 50
        """,
        [hub["h3_index_res9"], hub["h3_index_res8"]],
    )

    incidents = []
    for row in rows:
        d = dict(row)
        incidents.append(
            {
                "id": str(d["id"]),
                "trigger_type": d["trigger_type"],
                "triggered_at": d["triggered_at"].isoformat() if d.get("triggered_at") else None,
                "status": d["status"],
                "affected_rider_count": int(d.get("affected_rider_count") or 0),
                "oracle_score": float(d.get("oracle_score") or 0),
            }
        )

    return {"incidents": incidents}


@router.patch("/incidents/{incident_id}")
async def patch_hub_incident(
    incident_id: str,
    body: IncidentActionRequest,
    manager: dict = Depends(get_current_hub_manager),
    conn: asyncpg.Connection = Depends(get_db),
):
    hub_id = manager["hub_id"]
    hub = await conn.fetchrow("SELECT h3_index_res9, h3_index_res8 FROM hubs WHERE id = $1", hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    incident = await conn.fetchrow(
        """
        SELECT id, status
        FROM trigger_events
        WHERE id::text = $1 AND h3_index = ANY($2::text[])
        """,
        incident_id,
        [hub["h3_index_res9"], hub["h3_index_res8"]],
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    action = body.action.lower().strip()
    if action == "acknowledge":
        new_status = "active"
    elif action == "resolve":
        new_status = "resolved"
    elif action == "flag":
        new_status = "resolving"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    await conn.execute(
        "UPDATE trigger_events SET status=$1, resolved_at=CASE WHEN $1='resolved' THEN NOW() ELSE resolved_at END WHERE id=$2",
        new_status,
        incident["id"],
    )

    return {"status": "updated", "incident_id": str(incident["id"]), "new_status": new_status}
