"""api/v1/telemetry.py — GAP-10 FIX: bundle fraud validation added."""
from __future__ import annotations

from datetime import datetime
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_db, get_current_rider
from app.repositories.telemetry_repo import insert_telemetry_ping
from app.services.shift_service import infer_shift_state, upsert_shift_state
from app.services.vov_service import validate_bundle_integrity

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class PingRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed_kmh: float = Field(0.0, ge=0)
    accuracy_m: float = Field(10.0, ge=0)
    network_type: str = "4G"
    platform_status: str = "available"
    session_active: bool = True
    recorded_at: datetime


class BundlePing(PingRequest):
    pass


class BundleRequest(BaseModel):
    pings: list[BundlePing] = Field(..., max_length=288)
    bundle_hash: str  # GAP-10: client must send SHA-256 of sorted timestamps


@router.post("/ping", status_code=202)
async def ingest_ping(
    body: PingRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    ping_id = await insert_telemetry_ping(
        conn,
        rider_id=str(rider["id"]),
        latitude=body.latitude, longitude=body.longitude,
        speed_kmh=body.speed_kmh, accuracy_m=body.accuracy_m,
        network_type=body.network_type, platform_status=body.platform_status,
        session_active=body.session_active,
        recorded_at=body.recorded_at.isoformat(),
    )
    shift = await infer_shift_state(conn, str(rider["id"]))
    await upsert_shift_state(conn, str(rider["id"]), shift, inferred_by="gps")
    return {"accepted": True, "ping_id": ping_id}


@router.post("/bundle", status_code=202)
async def ingest_bundle(
    body: BundleRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """GAP-10 FIX: Full bundle fraud validation before accepting pings."""
    pings_data = [p.model_dump() for p in body.pings]
    for p in pings_data:
        p["recorded_at"] = p["recorded_at"].isoformat()

    # GAP-10: validate hash integrity, interval uniformity, H3 consistency
    valid, reason = await validate_bundle_integrity(str(rider["id"]), pings_data, body.bundle_hash)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Bundle validation failed: {reason}")

    from app.repositories.telemetry_repo import insert_bundle_pings
    inserted = await insert_bundle_pings(conn, str(rider["id"]), pings_data)
    return {"accepted": True, "inserted": inserted, "total": len(pings_data)}


@router.get("/latest-zone")
async def get_latest_zone(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    GET /api/v1/telemetry/latest-zone
    Returns latest oracle telemetry data for the rider's hub zone.
    Called by rider home dashboard for the Oracle Telemetry card.
    """
    hub_id = rider.get("hub_id")
    if not hub_id:
        return {
            "aqi": None, "precipitation": None,
            "storm_cell": None, "storm": None,
            "active_trigger_type": None, "trigger_score": None,
            "zone_status": "no_hub",
        }

    hub = await conn.fetchrow(
        "SELECT h3_index_res9, name FROM hubs WHERE id = $1", hub_id
    )
    if not hub:
        return {
            "aqi": None, "precipitation": None,
            "storm_cell": None, "storm": None,
            "active_trigger_type": None, "trigger_score": None,
            "zone_status": "hub_not_found",
        }

    h3 = hub["h3_index_res9"]

    # Check for active trigger in this zone
    active_trigger = await conn.fetchrow(
        """
        SELECT trigger_type, oracle_score, triggered_at, status
        FROM trigger_events
        WHERE h3_index = $1
          AND status IN ('active', 'resolving', 'detected')
        ORDER BY triggered_at DESC
        LIMIT 1
        """,
        h3,
    )

    result = {
        "aqi": None,
        "precipitation": None,
        "storm_cell": None,
        "storm": None,
        "active_trigger_type": active_trigger["trigger_type"] if active_trigger else None,
        "trigger_score": float(active_trigger["oracle_score"] or 0) if active_trigger else None,
        "zone_status": "active_event" if active_trigger else "clear",
        "hub_name": hub["name"],
    }

    if active_trigger:
        t = active_trigger["trigger_type"]
        score = float(active_trigger["oracle_score"] or 0)
        if t == "aqi":
            result["aqi"] = round(score * 500, 1)
        elif t in ("rain", "flood"):
            result["precipitation"] = round(score * 100, 1)
            result["storm_cell"] = round(score, 3)
            result["storm"] = round(score, 3)
        elif t == "heat":
            result["aqi"] = None

    return result
