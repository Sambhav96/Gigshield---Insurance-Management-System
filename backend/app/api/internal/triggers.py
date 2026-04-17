"""api/internal/triggers.py — Oracle trigger evaluation (called by Celery workers)."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_db
from app.services.oracle_service import compute_oracle_score
from app.repositories.trigger_repo import (
    create_trigger_event, check_duplicate_trigger, check_cooldown,
    compute_correlation_factor
)
from app.repositories.hub_repo import get_hub_by_h3, is_cold_start
from app.utils.mu_table import COOLDOWN_MINUTES, PLAN_TRIGGERS
from app.workers.oracle_worker import initiate_claims_for_hex

router = APIRouter(prefix="/triggers", tags=["internal"])


class TriggerEvalRequest(BaseModel):
    h3_index: str
    trigger_type: str
    lat: float
    lng: float
    hub_id: str | None = None
    peer_active: bool = False
    accel_active: bool = False
    peer_score: float = 0.0
    accel_score: float = 0.0


@router.post("/evaluate")
async def evaluate_trigger(
    body: TriggerEvalRequest,
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Full oracle evaluation for a hex zone.
    Fires trigger if oracle_score >= threshold.
    Returns trigger_id if fired, None if not.
    """
    hub = await get_hub_by_h3(conn, body.h3_index)
    if not hub and body.hub_id:
        from app.repositories.hub_repo import get_hub_by_id
        hub = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1", body.hub_id)
        hub = dict(hub) if hub else None

    if not hub:
        raise HTTPException(status_code=404, detail="No hub found for this H3 index")

    hub_threshold = float(hub.get("rain_threshold_mm", 35.0))
    cold_start = await is_cold_start(conn, body.h3_index)
    oracle_threshold = 0.75 if cold_start else 0.65

    # Read from experiments table if rider group has custom threshold
    exp_threshold = await conn.fetchval(
        """
        SELECT parameter_value::float FROM experiments
        WHERE parameter_name = 'oracle_threshold' AND active = true
        ORDER BY created_at DESC LIMIT 1
        """
    )
    if exp_threshold:
        oracle_threshold = float(exp_threshold)

    # Check duplicate trigger (fired in last 15 min)
    existing = await check_duplicate_trigger(conn, body.h3_index, body.trigger_type)
    if existing:
        return {"status": "duplicate", "trigger_id": existing}

    # Check cooldown
    cooldown_mins = COOLDOWN_MINUTES.get(body.trigger_type, 120)
    in_cooldown = await check_cooldown(conn, body.h3_index, body.trigger_type, cooldown_mins)

    # Compute oracle score
    result = compute_oracle_score(
        trigger_type=body.trigger_type,
        lat=body.lat,
        lng=body.lng,
        h3_index=body.h3_index,
        hub_threshold_mm=hub_threshold,
        peer_active=body.peer_active,
        accel_active=body.accel_active,
        peer_score=body.peer_score,
        accel_score=body.accel_score,
    )

    oracle_score = result["oracle_score"]

    # Save snapshot for backtesting
    import json
    await conn.execute(
        """
        INSERT INTO oracle_api_snapshots (h3_index, trigger_type, api_source, raw_value, signal_score)
        VALUES ($1, $2, $3, $4, $5)
        """,
        body.h3_index, body.trigger_type, "oracle_engine",
        oracle_score, oracle_score,
    )

    if oracle_score >= oracle_threshold:
        # Compute correlation factor
        city = hub.get("city", "")
        correlation = await compute_correlation_factor(conn, city)

        from app.utils.mu_table import get_correlation_payout_factor
        corr_payout_factor = get_correlation_payout_factor(correlation)
        # platform_down is always C=1.0
        if body.trigger_type == "platform_down":
            correlation = 1.0
            corr_payout_factor = 0.70

        trigger_id = await create_trigger_event(
            conn,
            trigger_type=body.trigger_type,
            h3_index=body.h3_index,
            hub_id=str(hub["id"]),
            oracle_score=oracle_score,
            weight_config=result.get("weight_config", {}),
            signal_scores=result.get("signal_scores", {}),
            raw_api_data=result.get("raw_api_data", {}),
            cold_start_mode=cold_start,
            cooldown_active=in_cooldown,
            cooldown_payout_factor=0.50 if in_cooldown else 1.00,
            correlation_factor=corr_payout_factor,
        )

        # Queue claims for all active policies in hex
        initiate_claims_for_hex.delay(body.h3_index, trigger_id, body.trigger_type)

        return {
            "status": "triggered",
            "trigger_id": trigger_id,
            "oracle_score": oracle_score,
            "cold_start": cold_start,
            "cooldown": in_cooldown,
        }

    elif 0.30 <= oracle_score < oracle_threshold:
        # VOV zone prompt
        from app.workers.vov_worker import prompt_vov_for_hex
        prompt_vov_for_hex.delay(body.h3_index, body.trigger_type, oracle_score)
        return {
            "status": "uncertain_vov_prompted",
            "oracle_score": oracle_score,
        }

    return {"status": "below_threshold", "oracle_score": oracle_score}
