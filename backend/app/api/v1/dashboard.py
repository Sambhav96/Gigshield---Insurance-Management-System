"""api/v1/dashboard.py — Live rider dashboard data."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_db, get_current_rider
from app.core.time_authority import get_db_now_ist_hour
from app.utils.mu_table import get_mu, get_mu_label, get_min_duration, get_plan_coverage, PLAN_CAP_MULTIPLIER

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/live")
async def live_dashboard(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    from app.repositories.policy_repo import get_active_policy_for_rider

    policy = await get_active_policy_for_rider(conn, str(rider["id"]))

    if not policy:
        return {
            "active_trigger": None,
            "weekly_remaining": 0,
            "expected_payout_now": 0,
            "mu_label": "No active policy",
            "policy_status": "none",
            "discount_weeks": 0,
            "next_debit": "N/A",
        }

    effective_income = float(rider["effective_income"])
    coverage_pct = float(policy["coverage_pct"])
    plan_cap_mult = int(policy["plan_cap_multiplier"])
    weekly_used = float(policy["weekly_payout_used"] or 0)
    max_weekly = effective_income * plan_cap_mult
    weekly_remaining = max(0.0, max_weekly - weekly_used)

    # Current MU
    ist_hour = await get_db_now_ist_hour(conn)
    mu = get_mu(ist_hour)
    mu_label = get_mu_label(ist_hour)

    # Active trigger in rider's hub zone
    hub = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1", policy["hub_id"])
    active_trigger = None
    expected_payout_now = 0.0

    if hub:
        # Use inline PLAN_TRIGGERS map (plan_config table removed — was never in migrations)
        from app.utils.mu_table import PLAN_TRIGGERS
        plan_trigger_list = PLAN_TRIGGERS.get(policy["plan"], PLAN_TRIGGERS["basic"])

        trigger = await conn.fetchrow(
            """
            SELECT te.* FROM trigger_events te
            WHERE te.h3_index = $1
              AND te.status IN ('active', 'resolving')
              AND te.trigger_type = ANY($2::text[])
            ORDER BY te.triggered_at DESC
            LIMIT 1
            """,
            hub["h3_index_res9"], plan_trigger_list,
        )

        if trigger:
            duration_since = await conn.fetchval(
                "SELECT EXTRACT(EPOCH FROM (NOW() - $1)) / 60",
                trigger["triggered_at"],
            )
            min_duration = get_min_duration(trigger["trigger_type"])
            expected_payout_now = effective_income * coverage_pct * (min_duration / 8) * mu

            # Total paid for this trigger event
            paid_for_trigger = await conn.fetchval(
                """
                SELECT COALESCE(SUM(p.amount), 0)
                FROM payouts p JOIN claims c ON p.claim_id = c.id
                WHERE c.trigger_id = $1 AND c.rider_id = $2
                """,
                trigger["id"], rider["id"],
            ) or 0

            event_cap = max_weekly * 0.50

            active_trigger = {
                "type": trigger["trigger_type"],
                "duration_mins": round(float(duration_since or 0), 1),
                "paid_so_far": float(paid_for_trigger),
                "event_cap_remaining": max(0.0, float(event_cap) - float(paid_for_trigger)),
                "trigger_id": str(trigger["id"]),
            }

    # Next debit Monday
    from datetime import date, timedelta
    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + timedelta(days=days_to_monday)

    return {
        "active_trigger": active_trigger,
        "weekly_remaining": weekly_remaining,
        "expected_payout_now": round(expected_payout_now, 2),
        "mu_label": mu_label,
        "policy_status": policy["status"],
        "discount_weeks": policy["discount_weeks"],
        "next_debit": next_monday.isoformat(),
    }


@router.get("/zone-metrics")
async def zone_metrics(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    # Demo-safe defaults when oracle streams are not populated.
    aqi_index = 0.0
    precipitation_pct = 0
    storm_risk = 0.0

    hub_id = rider.get("hub_id")
    if hub_id:
        hub = await conn.fetchrow("SELECT h3_index_res9 FROM hubs WHERE id = $1", hub_id)
        if hub:
            latest = await conn.fetchrow(
                """
                SELECT trigger_type, oracle_score
                FROM trigger_events
                WHERE h3_index = $1
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                hub["h3_index_res9"],
            )
            if latest:
                if latest["trigger_type"] == "aqi":
                    aqi_index = float(latest.get("oracle_score") or 0)
                if latest["trigger_type"] in ("rain", "flood"):
                    precipitation_pct = int(float(latest.get("oracle_score") or 0) * 100)
                if latest["trigger_type"] in ("storm", "rain", "flood"):
                    storm_risk = float(latest.get("oracle_score") or 0)

    return {
        "aqi_index": float(aqi_index),
        "precipitation_pct": int(precipitation_pct),
        "storm_risk": float(storm_risk),
        "data_freshness": "seeded",
    }
